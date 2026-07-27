<script>
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getLogs, getTraces, getTraceSteps } from "../lib/api.js";
  import { openRunDetail } from "../lib/router.js";

  let { project = null, selectedRuns = [] } = $props();

  const PAGE_SIZE = 25;
  let loading = $state(false);
  let search = $state("");
  let page = $state(0);
  let traces = $state([]);
  let evalResults = $state({});
  let selectedId = $state(null);
  let activeBranchIndex = $state(0);
  let totalCount = $state(0);
  let loadId = 0;

  function runsKey(runs) {
    return runs.map((run) => `${run.id || ""}:${run.name || ""}`).join("|");
  }

  function runKey(run) {
    return run?.id || run?.name || String(run || "");
  }

  function summarizeEvalLogs(logs) {
    const result = {};
    for (const row of logs || []) {
      for (const [key, value] of Object.entries(row)) {
        if (key.startsWith("eval/") && typeof value === "number") result[key] = value;
      }
    }
    return result;
  }

  function textContent(content) {
    if (typeof content === "string") return content;
    if (!Array.isArray(content)) return "";
    return content
      .map((part) => part?.text || part?.content || "")
      .filter(Boolean)
      .join("\n");
  }

  function totalReward(payload, metadata) {
    if (typeof metadata?.reward === "number") return metadata.reward;
    return Object.values(payload?.rewards || {}).reduce(
      (sum, value) => sum + (typeof value === "number" ? value : 0),
      0,
    );
  }

  function traceStatus(payload, metadata) {
    if ((payload?.errors || []).length) return "error";
    if (metadata?.is_truncated) return "truncated";
    if (payload?.is_completed || metadata?.is_completed) return "complete";
    return "incomplete";
  }

  function normalizeTrace(trace, runLabel) {
    const payload = trace.payload || {};
    const messages = Array.isArray(trace.messages) ? trace.messages : [];
    const user = messages.find((message) => message?.role === "user");
    return {
      ...trace,
      payload,
      run: trace.run || runLabel,
      prompt: textContent(user?.content) || "(no prompt)",
      model: trace.metadata?.model || payload.agent?.model || "—",
      task: trace.metadata?.task_type || payload.task?.type || "—",
      reward: totalReward(payload, trace.metadata),
      status: traceStatus(payload, trace.metadata),
    };
  }

  async function load() {
    const requestId = ++loadId;
    if (!project || selectedRuns.length === 0) {
      traces = [];
      evalResults = {};
      selectedId = null;
      totalCount = 0;
      return;
    }
    loading = true;
    try {
      const [counts, runLogs] = await Promise.all([
        Promise.all(
        selectedRuns.map((run) =>
          getTraceSteps(project, run, { trace_type: "verifiers" }),
        ),
        ),
        Promise.all(
          selectedRuns.map(async (run) => ({
            key: runKey(run),
            metrics: summarizeEvalLogs(
              await getLogs(project, run, { scalar_only: true }),
            ),
          })),
        ),
      ]);
      const offset = page * PAGE_SIZE;
      const singleRun = selectedRuns.length === 1;
      const batches = await Promise.all(
        selectedRuns.map(async (run) => {
          const rows = await getTraces(project, run, {
            trace_type: "verifiers",
            search: search.trim(),
            sort: "request_time_desc",
            limit: singleRun ? PAGE_SIZE : offset + PAGE_SIZE,
            offset: singleRun ? offset : 0,
          });
          return rows.map((trace) => normalizeTrace(trace, run.name));
        }),
      );
      if (requestId !== loadId) return;
      evalResults = Object.fromEntries(
        runLogs.map(({ key, metrics }) => [key, metrics]),
      );
      totalCount = counts.reduce((sum, result) => sum + (result?.total || 0), 0);
      let merged = batches
        .flat()
        .sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || "")));
      if (!singleRun) merged = merged.slice(offset, offset + PAGE_SIZE);
      traces = merged;
      if (!traces.some((trace) => trace.id === selectedId)) {
        selectedId = traces[0]?.id || null;
      }
    } catch (error) {
      if (requestId === loadId) {
        console.error("Failed to load Verifiers traces:", error);
        traces = [];
      }
    } finally {
      if (requestId === loadId) loading = false;
    }
  }

  let lastScope = "";
  let lastSearch = "";
  $effect(() => {
    const scope = `${project || ""}:${runsKey(selectedRuns)}`;
    const query = search.trim();
    if (scope !== lastScope || query !== lastSearch) {
      page = 0;
      lastScope = scope;
      lastSearch = query;
    }
    const timeout = setTimeout(load, 150);
    return () => clearTimeout(timeout);
  });

  let selected = $derived(traces.find((trace) => trace.id === selectedId) || null);
  let selectedEvalResult = $derived(
    selected
      ? (evalResults[selected.run_id] || evalResults[selected.run] || {})
      : {},
  );
  let hasEvalResult = $derived(Object.keys(selectedEvalResult).length > 0);
  let totalPages = $derived(Math.max(1, Math.ceil(totalCount / PAGE_SIZE)));

  function traceBranches(payload) {
    const nodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
    if (!nodes.length) return [];
    const parents = new Set(
      nodes.map((node) => node?.parent).filter((parent) => Number.isInteger(parent)),
    );
    return nodes
      .map((_, index) => index)
      .filter((index) => !parents.has(index))
      .map((leaf) => {
        const path = [];
        const seen = new Set();
        let index = leaf;
        while (Number.isInteger(index) && nodes[index] && !seen.has(index)) {
          seen.add(index);
          path.unshift(index);
          index = nodes[index]?.parent;
        }
        return {
          leaf,
          indices: path,
          messages: path.map((nodeIndex) => nodes[nodeIndex]?.message).filter(Boolean),
        };
      });
  }

  let selectedBranches = $derived(selected ? traceBranches(selected.payload) : []);
  let activeBranch = $derived(selectedBranches[activeBranchIndex] || null);
  let displayedMessages = $derived(
    activeBranch?.messages?.length ? activeBranch.messages : (selected?.messages || []),
  );

  let previousSelectedId = null;
  $effect(() => {
    if (selectedId !== previousSelectedId) {
      activeBranchIndex = Math.max(0, selectedBranches.length - 1);
      previousSelectedId = selectedId;
    }
  });

  function branchCount(payload) {
    const nodes = payload?.nodes || [];
    const parents = new Set(
      nodes.map((node) => node?.parent).filter((parent) => Number.isInteger(parent)),
    );
    return nodes.filter((_, index) => !parents.has(index)).length;
  }

  function duration(span) {
    if (typeof span?.duration === "number") return span.duration;
    if (typeof span?.start === "number" && typeof span?.end === "number") {
      return span.end - span.start;
    }
    return null;
  }

  function formatDuration(span) {
    const seconds = duration(span);
    if (seconds == null) return "—";
    if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
    return `${seconds.toFixed(2)} s`;
  }

  function formatNumber(value) {
    return typeof value === "number" ? value.toLocaleString() : "—";
  }

  function formatDecimal(value, digits = 3) {
    return typeof value === "number" ? value.toFixed(digits) : "—";
  }

  function formatPercent(value) {
    return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
  }

  function formatCost(value) {
    return typeof value === "number" ? `$${value.toFixed(4)}` : "—";
  }

  function prefixedMetrics(result, prefix) {
    return Object.entries(result)
      .filter(([key]) => key.startsWith(prefix))
      .map(([key, value]) => [key.slice(prefix.length), value]);
  }

  function entries(value) {
    return Object.entries(value || {});
  }

  function phases(payload) {
    const timing = payload?.timing || {};
    return ["boot", "setup", "generation", "finalize", "scoring"].map((name) => ({
      name,
      value: timing[name],
    }));
  }

  function stopRowClick(event) {
    event.stopPropagation();
  }
</script>

<div class="verifiers-page">
  {#if !project || selectedRuns.length === 0}
    <div class="empty-state">
      <h2>Open Verifiers rollouts</h2>
      <p>Select one or more experiment runs in the sidebar.</p>
    </div>
  {:else}
    <header class="page-header">
      <div>
        <h1>Verifiers rollouts</h1>
        <p>Inspect task trajectories, scoring, model calls, and environment timing.</p>
      </div>
      <div class="header-count">{totalCount} rollout{totalCount === 1 ? "" : "s"}</div>
    </header>

    <div class="toolbar">
      <input bind:value={search} placeholder="Search prompts, model, task, or metadata" />
    </div>

    {#if loading && traces.length === 0}
      <LoadingTrackio />
    {:else if traces.length === 0}
      <div class="empty-state"><h2>No Verifiers rollouts found</h2></div>
    {:else}
      <div class="workspace" class:dim={loading}>
        <aside class="rollout-list">
          {#each traces as trace (trace.id)}
            <button
              class="rollout-card"
              class:active={trace.id === selectedId}
              onclick={() => (selectedId = trace.id)}
            >
              <div class="card-topline">
                <span class="status" data-status={trace.status}>{trace.status}</span>
                <span class="reward">reward {trace.reward.toFixed(3)}</span>
              </div>
              <div class="task">{trace.task}</div>
              <div class="prompt">{trace.prompt}</div>
              <div class="card-meta">
                <span>{trace.model}</span>
                <span>step {trace.step ?? "—"}</span>
              </div>
            </button>
          {/each}
        </aside>

        {#if selected}
          <main class="rollout-detail">
            <div class="detail-heading">
              <div>
                <div class="eyebrow">{selected.task}</div>
                <h2>{selected.external_id || selected.id}</h2>
              </div>
              <button
                class="experiment-link"
                onclick={(event) => {
                  stopRowClick(event);
                  openRunDetail(selected.run, selected.run_id);
                }}
              >Open experiment ↗</button>
            </div>

            <section class="summary-grid">
              <div><span>Status</span><strong>{selected.status}</strong></div>
              <div><span>Total reward</span><strong>{selected.reward.toFixed(3)}</strong></div>
              <div><span>Stop condition</span><strong>{selected.payload.stop_condition || "—"}</strong></div>
              <div><span>Branches</span><strong>{branchCount(selected.payload)}</strong></div>
              <div><span>Model calls</span><strong>{selected.payload.calls?.length || 0}</strong></div>
              <div><span>Model</span><strong>{selected.model}</strong></div>
            </section>

            {#if hasEvalResult}
              <section class="eval-result">
                <div class="section-heading">
                  <div>
                    <div class="eyebrow">Producing run</div>
                    <h3>Evaluation result</h3>
                  </div>
                  <span class="result-scope">aggregate across {formatNumber(selectedEvalResult["eval/rollouts"])} rollouts</span>
                </div>
                <div class="result-grid">
                  <div><span>Mean reward</span><strong>{formatDecimal(selectedEvalResult["eval/mean_reward"])}</strong></div>
                  <div><span>Completed</span><strong>{formatNumber(selectedEvalResult["eval/completed"])} / {formatNumber(selectedEvalResult["eval/rollouts"])}</strong></div>
                  <div><span>Error rate</span><strong>{formatPercent(selectedEvalResult["eval/error_rate"])}</strong></div>
                  <div><span>Truncated</span><strong>{formatPercent(selectedEvalResult["eval/truncated_rollout_rate"])}</strong></div>
                  <div><span>Call p95</span><strong>{formatDecimal(selectedEvalResult["eval/model_call_latency_p95_seconds"], 2)} s</strong></div>
                  <div><span>Total tokens</span><strong>{formatNumber((selectedEvalResult["eval/input_tokens"] || 0) + (selectedEvalResult["eval/output_tokens"] || 0))}</strong></div>
                  <div><span>Provider cost</span><strong>{formatCost(selectedEvalResult["eval/provider_cost"])}</strong></div>
                  <div><span>Trace sync</span><strong>{selectedEvalResult["eval/trace_sync_complete"] === 1 ? "complete" : "partial"}</strong></div>
                </div>
                <div class="two-column result-components">
                  <div>
                    <h4>Average verifier rewards</h4>
                    <div class="kv-list">
                      {#each prefixedMetrics(selectedEvalResult, "eval/reward/") as [name, value]}
                        <div><span>{name}</span><strong>{formatDecimal(value)}</strong></div>
                      {:else}<p class="muted">No aggregate reward components.</p>{/each}
                    </div>
                  </div>
                  <div>
                    <h4>Average environment metrics</h4>
                    <div class="kv-list">
                      {#each prefixedMetrics(selectedEvalResult, "eval/environment_metric/") as [name, value]}
                        <div><span>{name}</span><strong>{formatDecimal(value)}</strong></div>
                      {:else}<p class="muted">No aggregate environment metrics.</p>{/each}
                    </div>
                  </div>
                </div>
              </section>
            {/if}

            <section>
              <div class="section-heading">
                <h3>{activeBranchIndex === selectedBranches.length - 1 ? "Final trajectory" : `Branch ${activeBranchIndex + 1}`}</h3>
                {#if selectedBranches.length > 1}
                  <div class="branch-tabs" aria-label="Rollout branches">
                    {#each selectedBranches as _, index}
                      <button
                        class:active={index === activeBranchIndex}
                        onclick={() => (activeBranchIndex = index)}
                      >{index === selectedBranches.length - 1 ? "Final" : `Branch ${index + 1}`}</button>
                    {/each}
                  </div>
                {/if}
              </div>
              <div class="trajectory">
                {#each displayedMessages as message}
                  <article class="message" data-role={message.role || "unknown"}>
                    <div class="message-role">{message.role || "message"}</div>
                    {#if textContent(message.content)}
                      <pre>{textContent(message.content)}</pre>
                    {/if}
                    {#if message.tool_calls?.length}
                      <div class="tool-calls">
                        {#each message.tool_calls as call}
                          <div class="tool-call">
                            <strong>{call.function?.name || call.name || "tool"}</strong>
                            <code>{call.function?.arguments || call.arguments || ""}</code>
                          </div>
                        {/each}
                      </div>
                    {/if}
                  </article>
                {/each}
              </div>
            </section>

            {#if selected.payload.tools?.length}
              <section>
                <h3>Available tools</h3>
                <div class="tool-inventory">
                  {#each selected.payload.tools as tool}
                    <article>
                      <strong>{tool.function?.name || tool.name || "tool"}</strong>
                      {#if tool.function?.description || tool.description}
                        <p>{tool.function?.description || tool.description}</p>
                      {/if}
                    </article>
                  {/each}
                </div>
              </section>
            {/if}

            <section class="two-column">
              <div>
                <h3>Rewards</h3>
                <div class="kv-list">
                  {#each entries(selected.payload.rewards) as [name, value]}
                    <div><span>{name}</span><strong>{value}</strong></div>
                  {:else}<p class="muted">No reward components.</p>{/each}
                </div>
              </div>
              <div>
                <h3>Environment metrics</h3>
                <div class="kv-list">
                  {#each entries(selected.payload.metrics) as [name, value]}
                    <div><span>{name}</span><strong>{value}</strong></div>
                  {:else}<p class="muted">No environment metrics.</p>{/each}
                </div>
              </div>
            </section>

            <section>
              <h3>Model calls</h3>
              <div class="calls">
                {#each selected.payload.calls || [] as call, index}
                  <article class="call-card">
                    <div class="call-heading">
                      <strong>Call {index + 1}</strong>
                      <span>{call.finish_reason || (call.error ? "error" : "—")}</span>
                    </div>
                    <div class="call-grid">
                      <div><span>Endpoint</span><strong>{call.endpoint || "—"}</strong></div>
                      <div><span>Duration</span><strong>{formatDuration(call.time)}</strong></div>
                      <div><span>Input tokens</span><strong>{formatNumber(call.usage?.prompt_tokens)}</strong></div>
                      <div><span>Output tokens</span><strong>{formatNumber(call.usage?.completion_tokens)}</strong></div>
                    </div>
                    {#if call.error}<div class="error-panel">{call.error.message || call.error}</div>{/if}
                  </article>
                {:else}<p class="muted">No model calls recorded.</p>{/each}
              </div>
            </section>

            <section>
              <h3>Rollout timing</h3>
              <div class="phase-grid">
                {#each phases(selected.payload) as phase}
                  <div><span>{phase.name}</span><strong>{formatDuration(phase.value)}</strong></div>
                {/each}
              </div>
            </section>

            {#if selected.payload.errors?.length}
              <section>
                <h3>Errors</h3>
                {#each selected.payload.errors as error}
                  <div class="error-panel"><strong>{error.type || "Error"}</strong><p>{error.message || ""}</p></div>
                {/each}
              </section>
            {/if}
          </main>
        {/if}
      </div>

      <div class="pagination">
        <button disabled={page === 0 || loading} onclick={() => (page -= 1)}>← Previous</button>
        <span>Page {page + 1} of {totalPages}</span>
        <button disabled={page >= totalPages - 1 || loading} onclick={() => (page += 1)}>Next →</button>
      </div>
    {/if}
  {/if}
</div>

<style>
  .verifiers-page { padding: 24px; overflow-y: auto; flex: 1; background: var(--background-fill-secondary, #f7f8fa); color: var(--body-text-color, #18202a); }
  .page-header, .detail-heading, .card-topline, .card-meta, .call-heading, .pagination, .section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .page-header h1 { margin: 0; font-size: 24px; }
  .page-header p, .muted { color: var(--body-text-color-subdued, #667085); }
  .header-count { font-weight: 600; }
  .toolbar { margin: 18px 0; }
  .toolbar input { width: 100%; padding: 11px 14px; border: 1px solid var(--border-color-primary, #d9dee7); border-radius: 8px; background: var(--background-fill-primary, white); color: inherit; }
  .workspace { display: grid; grid-template-columns: minmax(280px, 360px) minmax(0, 1fr); min-height: 620px; border: 1px solid var(--border-color-primary, #d9dee7); border-radius: 10px; overflow: hidden; background: var(--background-fill-primary, white); transition: opacity .15s; }
  .workspace.dim { opacity: .65; }
  .rollout-list { border-right: 1px solid var(--border-color-primary, #d9dee7); overflow-y: auto; max-height: 78vh; background: var(--background-fill-secondary, #f8fafc); }
  .rollout-card { width: 100%; padding: 14px; border: 0; border-bottom: 1px solid var(--border-color-primary, #e6eaf0); background: transparent; color: inherit; text-align: left; cursor: pointer; }
  .rollout-card:hover, .rollout-card.active { background: var(--background-fill-primary, white); }
  .rollout-card.active { box-shadow: inset 3px 0 0 var(--color-accent, #6d5efc); }
  .status { padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; text-transform: uppercase; background: #eef2f6; }
  .status[data-status="complete"] { background: #dcfce7; color: #166534; }
  .status[data-status="error"] { background: #fee2e2; color: #991b1b; }
  .status[data-status="truncated"] { background: #fef3c7; color: #92400e; }
  .reward { font-variant-numeric: tabular-nums; font-size: 12px; }
  .task { margin-top: 10px; font-weight: 650; }
  .prompt { margin: 6px 0 10px; color: var(--body-text-color-subdued, #667085); line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .card-meta { font-size: 11px; color: var(--body-text-color-subdued, #667085); }
  .rollout-detail { padding: 22px; overflow-y: auto; max-height: 78vh; }
  .eyebrow { color: var(--body-text-color-subdued, #667085); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
  .detail-heading h2 { margin: 4px 0 0; font-size: 16px; font-family: ui-monospace, monospace; word-break: break-all; }
  .experiment-link, .pagination button { border: 1px solid var(--border-color-primary, #d9dee7); border-radius: 7px; padding: 8px 12px; background: var(--background-fill-primary, white); color: inherit; cursor: pointer; }
  section { margin-top: 24px; }
  section h3 { margin: 0 0 10px; font-size: 15px; }
  .section-heading h3 { margin: 0; }
  .branch-tabs { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
  .branch-tabs button { border: 1px solid var(--border-color-primary, #d9dee7); border-radius: 999px; padding: 5px 10px; background: transparent; color: inherit; cursor: pointer; font-size: 12px; }
  .branch-tabs button.active { border-color: var(--color-accent, #6d5efc); background: color-mix(in srgb, var(--color-accent, #6d5efc) 12%, transparent); }
  .summary-grid, .phase-grid, .call-grid, .result-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
  .summary-grid > div, .phase-grid > div, .call-grid > div, .result-grid > div { border: 1px solid var(--border-color-primary, #e2e6ec); border-radius: 7px; padding: 10px; display: flex; flex-direction: column; gap: 5px; }
  .summary-grid span, .phase-grid span, .call-grid span, .result-grid span { color: var(--body-text-color-subdued, #667085); font-size: 11px; text-transform: uppercase; }
  .eval-result { padding: 16px; border: 1px solid color-mix(in srgb, var(--color-accent, #6d5efc) 35%, var(--border-color-primary, #e2e6ec)); border-radius: 10px; background: color-mix(in srgb, var(--color-accent, #6d5efc) 4%, var(--background-fill-primary, white)); }
  .eval-result .section-heading { margin-bottom: 12px; }
  .eval-result h3 { margin: 3px 0 0; }
  .result-scope { color: var(--body-text-color-subdued, #667085); font-size: 12px; }
  .result-components { margin-top: 14px; }
  .result-components h4 { margin: 0 0 6px; font-size: 13px; }
  .trajectory, .calls { display: flex; flex-direction: column; gap: 10px; }
  .message, .call-card { border: 1px solid var(--border-color-primary, #e2e6ec); border-radius: 8px; padding: 12px; }
  .message-role { color: var(--body-text-color-subdued, #667085); font-size: 11px; font-weight: 700; text-transform: uppercase; margin-bottom: 7px; }
  .message pre { margin: 0; white-space: pre-wrap; word-break: break-word; font: inherit; line-height: 1.5; }
  .tool-calls { margin-top: 10px; display: grid; gap: 8px; }
  .tool-call { padding: 9px; border-radius: 6px; background: var(--background-fill-secondary, #f6f8fa); display: flex; flex-direction: column; gap: 5px; }
  .tool-call code { white-space: pre-wrap; word-break: break-word; }
  .tool-inventory { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
  .tool-inventory article { border: 1px solid var(--border-color-primary, #e2e6ec); border-radius: 8px; padding: 12px; }
  .tool-inventory p { margin: 6px 0 0; color: var(--body-text-color-subdued, #667085); line-height: 1.4; }
  .two-column { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  .kv-list > div { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border-color-primary, #edf0f3); }
  .call-heading { margin-bottom: 10px; }
  .error-panel { margin-top: 10px; padding: 10px; border: 1px solid #fecaca; border-radius: 7px; background: #fff1f2; color: #991b1b; white-space: pre-wrap; }
  .pagination { justify-content: center; margin-top: 16px; }
  .pagination button:disabled { opacity: .45; cursor: not-allowed; }
  .empty-state { padding: 48px 24px; }
  @media (max-width: 980px) { .workspace { grid-template-columns: 1fr; } .rollout-list { border-right: 0; border-bottom: 1px solid var(--border-color-primary, #d9dee7); max-height: 320px; } .rollout-detail { max-height: none; } .two-column { grid-template-columns: 1fr; } }
</style>
