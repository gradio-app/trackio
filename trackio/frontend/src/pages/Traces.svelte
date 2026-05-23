<script>
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getMediaUrl, getTraces, getTraceSteps } from "../lib/api.js";

  let {
    project = null,
    selectedRuns = [],
  } = $props();

  const PAGE_SIZE = 50;

  let loading = $state(false);
  let search = $state("");
  let sortBy = $state("request_time_desc");
  let stepFilter = $state("all");
  let page = $state(0);
  let expandedTraceId = $state(null);
  let traces = $state([]);
  let availableSteps = $state([]);
  let totalCount = $state(0);
  let loadRequestId = 0;
  let summaryRequestId = 0;

  function runsKey(runs) {
    return runs.map((r) => `${r.id || ""}:${r.name || ""}`).join("|");
  }

  function textFromContent(content) {
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      return content
        .map((part) => {
          if (typeof part === "string") return part;
          if (typeof part?.text === "string") return part.text;
          if (typeof part?.content === "string") return part.content;
          if (part?._type === "trackio.image" || part?.type === "image") return "[image]";
          return "";
        })
        .filter(Boolean)
        .join(" ");
    }
    if (typeof content?.text === "string") return content.text;
    return "";
  }

  function normalizeTrace(trace, runLabel) {
    const messages = Array.isArray(trace.messages) ? trace.messages : [];
    const firstUser = messages.find((message) => message?.role === "user");
    const firstAssistant = messages.find((message) => message?.role === "assistant");
    return {
      ...trace,
      run: trace.run || runLabel,
      request: textFromContent(firstUser?.content) || "(no user message)",
      preview: textFromContent(firstAssistant?.content) || "(no assistant response)",
    };
  }

  function mergeSortedTraces(items, sort) {
    return [...items].sort((left, right) => {
      switch (sort) {
        case "step_asc":
          return (left.step ?? 0) - (right.step ?? 0);
        case "step_desc":
          return (right.step ?? 0) - (left.step ?? 0);
        case "request_time_asc":
          return String(left.timestamp || "").localeCompare(String(right.timestamp || ""));
        case "request_time_desc":
        default:
          return String(right.timestamp || "").localeCompare(String(left.timestamp || ""));
      }
    });
  }

  async function loadSummary() {
    const requestId = ++summaryRequestId;
    if (!project || selectedRuns.length === 0) {
      availableSteps = [];
      totalCount = 0;
      return;
    }
    try {
      const results = await Promise.all(
        selectedRuns.map((run) => getTraceSteps(project, run)),
      );
      if (requestId !== summaryRequestId) return;
      const merged = new Map();
      let total = 0;
      for (const result of results) {
        total += result?.total || 0;
        for (const entry of result?.steps || []) {
          merged.set(entry.step, (merged.get(entry.step) || 0) + entry.count);
        }
      }
      availableSteps = [...merged.entries()]
        .map(([step, count]) => ({ step, count }))
        .sort((a, b) => (a.step ?? 0) - (b.step ?? 0));
      totalCount = total;
    } catch (error) {
      if (requestId !== summaryRequestId) return;
      console.error("Failed to load trace summary:", error);
      availableSteps = [];
      totalCount = 0;
    }
  }

  async function loadTraces(searchQuery, sort, stepValue, currentPage) {
    const requestId = ++loadRequestId;
    if (!project || selectedRuns.length === 0) {
      traces = [];
      expandedTraceId = null;
      return;
    }

    loading = true;
    try {
      const stepNum = stepValue === "all" ? null : Number(stepValue);
      const offset = currentPage * PAGE_SIZE;
      const isSingleRun = selectedRuns.length === 1;
      const perRunLimit = isSingleRun ? PAGE_SIZE : offset + PAGE_SIZE;
      const perRunOffset = isSingleRun ? offset : 0;

      const batches = await Promise.all(
        selectedRuns.map(async (run) => {
          const runTraces = await getTraces(project, run, {
            search: searchQuery,
            sort,
            step: stepNum,
            limit: perRunLimit,
            offset: perRunOffset,
          });
          return runTraces.map((trace) => normalizeTrace(trace, run.name));
        }),
      );
      if (requestId !== loadRequestId) return;
      let merged = mergeSortedTraces(batches.flat(), sort);
      if (!isSingleRun) {
        merged = merged.slice(offset, offset + PAGE_SIZE);
      }
      traces = merged;
      if (!traces.find((trace) => trace.id === expandedTraceId)) {
        expandedTraceId = null;
      }
    } catch (error) {
      if (requestId !== loadRequestId) return;
      console.error("Failed to load traces:", error);
      traces = [];
    } finally {
      if (requestId === loadRequestId) {
        loading = false;
      }
    }
  }

  let lastScopeKey = "";
  let lastSearch = "";
  let lastSort = "";
  let lastStep = "all";

  $effect(() => {
    const scopeKey = `${project || ""}::${runsKey(selectedRuns)}`;
    if (scopeKey !== lastScopeKey) {
      lastScopeKey = scopeKey;
      page = 0;
      stepFilter = "all";
      expandedTraceId = null;
      traces = [];
      loadSummary();
    }
  });

  $effect(() => {
    project;
    runsKey(selectedRuns);
    const trimmed = search.trim();
    if (trimmed !== lastSearch || sortBy !== lastSort || stepFilter !== lastStep) {
      if (lastSearch !== "" || trimmed !== "" || sortBy !== lastSort || stepFilter !== lastStep) {
        page = 0;
      }
      lastSearch = trimmed;
      lastSort = sortBy;
      lastStep = stepFilter;
    }

    const timeout = setTimeout(() => {
      loadTraces(trimmed, sortBy, stepFilter, page);
    }, 150);
    return () => clearTimeout(timeout);
  });

  function toggleTrace(traceId) {
    expandedTraceId = expandedTraceId === traceId ? null : traceId;
  }

  function handleRowKeydown(event, traceId) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggleTrace(traceId);
    }
  }

  function formatRelativeTime(timestamp) {
    if (!timestamp) return "—";
    const then = new Date(timestamp);
    if (Number.isNaN(then.getTime())) return timestamp;

    const now = new Date();
    const diffMs = now.getTime() - then.getTime();
    const diffSeconds = Math.max(0, Math.round(diffMs / 1000));

    if (diffSeconds < 5) return "just now";
    if (diffSeconds < 60) return `${diffSeconds} sec ago`;

    const diffMinutes = Math.round(diffSeconds / 60);
    if (diffMinutes < 60) return `${diffMinutes} min ago`;

    const diffHours = Math.round(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours} hr ago`;

    const diffDays = Math.round(diffHours / 24);
    if (diffDays < 7) return `${diffDays} day${diffDays === 1 ? "" : "s"} ago`;

    const diffWeeks = Math.round(diffDays / 7);
    if (diffWeeks < 5) return `${diffWeeks} wk ago`;

    const diffMonths = Math.round(diffDays / 30);
    if (diffMonths < 12) return `${diffMonths} mo ago`;

    const diffYears = Math.round(diffDays / 365);
    return `${diffYears} yr ago`;
  }

  function renderableParts(message) {
    const content = message?.content;
    if (typeof content === "string" || content == null) return [];
    if (Array.isArray(content)) return content;
    return [content];
  }

  function hasRenderableParts(message) {
    return renderableParts(message).length > 0;
  }

  function isImagePart(part) {
    return (
      part?._type === "trackio.image" ||
      part?.type === "image" ||
      part?.type === "input_image" ||
      part?.type === "image_url"
    );
  }

  function imageSrc(part) {
    if (part?.file_path) return getMediaUrl(part.file_path);
    if (part?.image_url?.url) return part.image_url.url;
    if (typeof part?.url === "string") return part.url;
    return "";
  }

  function imageAlt(part) {
    return part?.caption || part?.alt || "Trace image";
  }

  function longText(text) {
    return typeof text === "string" && text.length > 500;
  }

  function publicTraceId(id) {
    if (!id) return "";
    const parts = String(id).split(":");
    if (parts.length >= 4) {
      const logId = parts[1];
      const index = parts[parts.length - 1];
      return index !== "" && !Number.isNaN(Number(index)) ? `${logId}:${index}` : logId;
    }
    return String(id);
  }

  function traceHash(id) {
    if (!id) return "";
    const parts = String(id).split(":");
    const source = parts.length >= 4 ? parts[1] || parts[0] : String(id);
    return source.replace(/[^a-zA-Z0-9]/g, "").slice(0, 7) || source.slice(0, 7);
  }

  function traceIndex(id) {
    if (!id) return null;
    const parts = String(id).split(":");
    if (parts.length >= 4) {
      const last = parts[parts.length - 1];
      if (last !== "" && !Number.isNaN(Number(last))) return last;
    }
    return null;
  }


  function formatMetadataValue(value) {
    if (value == null) return "—";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }

  function metadataEntries(trace) {
    return Object.entries(trace.metadata || {});
  }

  let activeTotal = $derived.by(() => {
    if (stepFilter === "all") return totalCount;
    const stepNum = Number(stepFilter);
    const entry = availableSteps.find((s) => s.step === stepNum);
    return entry ? entry.count * Math.max(1, selectedRuns.length) : 0;
  });

  let totalPages = $derived(Math.max(1, Math.ceil(activeTotal / PAGE_SIZE)));

  function gotoPrev() {
    if (page > 0) page -= 1;
  }
  function gotoNext() {
    if (page < totalPages - 1) page += 1;
  }
</script>

<div class="traces-page">
  {#if !project}
    <div class="empty-state">
      <h2>Select a project</h2>
      <p>Pick a project to browse trace logs.</p>
    </div>
  {:else if selectedRuns.length === 0}
    <div class="empty-state">
      <h2>No runs selected</h2>
      <p>Select one or more runs in the sidebar to browse traces.</p>
    </div>
  {:else}
    <div class="toolbar">
      <div class="search-wrap">
        <input type="text" bind:value={search} placeholder="Search traces by request" />
      </div>
      <label class="filter-wrap">
        <span>Step:</span>
        <select bind:value={stepFilter}>
          <option value="all">All steps ({totalCount})</option>
          {#each availableSteps as entry}
            <option value={String(entry.step)}>Step {entry.step} ({entry.count})</option>
          {/each}
        </select>
      </label>
      <label class="filter-wrap">
        <span>Sort:</span>
        <select bind:value={sortBy}>
          <option value="request_time_desc">Request time</option>
          <option value="request_time_asc">Oldest first</option>
          <option value="step_desc">Step descending</option>
          <option value="step_asc">Step ascending</option>
        </select>
      </label>
      <div class="count">
        {activeTotal} trace{activeTotal === 1 ? "" : "s"}
      </div>
    </div>

    {#if loading && traces.length === 0}
      <LoadingTrackio />
    {:else if traces.length === 0}
      <div class="empty-state">
        <h2>No traces match the current filters</h2>
        <p>Try a different search query, step, or run selection.</p>
      </div>
    {:else}
      <div class="traces-table-wrap" class:dim={loading}>
        <table class="traces-table">
          <colgroup>
            <col class="trace-id-col" />
            <col class="request-col" />
            <col class="run-col" />
            <col class="step-col" />
            <col class="request-time-col" />
          </colgroup>
          <thead>
            <tr>
              <th>Trace ID</th>
              <th>Request</th>
              <th>Run</th>
              <th>Step</th>
              <th>Request time</th>
            </tr>
          </thead>
          <tbody>
            {#each traces as trace (trace.id)}
              <tr
                class="trace-row"
                role="button"
                tabindex="0"
                aria-expanded={expandedTraceId === trace.id}
                onclick={() => toggleTrace(trace.id)}
                onkeydown={(event) => handleRowKeydown(event, trace.id)}
              >
                <td class="trace-id-cell">
                  <span class="trace-id-chip" title={publicTraceId(trace.id)}
                    >{traceHash(trace.id)}{traceIndex(trace.id) !== null
                      ? `:${traceIndex(trace.id)}`
                      : ""}</span
                  >
                </td>
                <td class="request-cell">
                  <div class="request">{trace.request}</div>
                  <div class="preview">{trace.preview}</div>
                </td>
                <td>{trace.run || "—"}</td>
                <td>{trace.step ?? "—"}</td>
                <td>{formatRelativeTime(trace.timestamp)}</td>
              </tr>
              {#if expandedTraceId === trace.id}
                <tr class="expanded-row">
                  <td colspan="5">
                    <div class="trace-detail">
                      <div class="detail-meta">
                        <span>Trace ID: {publicTraceId(trace.id)}</span>
                        <span>Logged as: {trace.key}</span>
                        <span>Timestamp: {trace.timestamp || "—"}</span>
                        {#each metadataEntries(trace) as [key, value]}
                          <span>{key}: {formatMetadataValue(value)}</span>
                        {/each}
                      </div>

                      <div class="conversation">
                        {#each trace.messages as message}
                          <div class="message" data-role={message.role || "unknown"}>
                            <div class="message-role">
                              {message.role || "message"}
                              {#if message.tool_calls?.length}
                                <span class="message-tag">tool calls</span>
                              {/if}
                              {#if message.function_call}
                                <span class="message-tag">function call</span>
                              {/if}
                            </div>

                            {#if typeof message.content === "string"}
                              {#if longText(message.content)}
                                <details class="message-details">
                                  <summary>Expand content</summary>
                                  <pre class="message-content">{message.content}</pre>
                                </details>
                              {:else}
                                <pre class="message-content">{message.content}</pre>
                              {/if}
                            {:else if hasRenderableParts(message)}
                              <div class="message-parts">
                                {#each renderableParts(message) as part}
                                  {#if isImagePart(part)}
                                    <img class="trace-image" src={imageSrc(part)} alt={imageAlt(part)} />
                                  {:else}
                                    <pre class="message-content">{JSON.stringify(part, null, 2)}</pre>
                                  {/if}
                                {/each}
                              </div>
                            {/if}

                            {#if message.tool_calls?.length}
                              <div class="tool-blocks">
                                {#each message.tool_calls as toolCall}
                                  <pre class="tool-block">{JSON.stringify(toolCall, null, 2)}</pre>
                                {/each}
                              </div>
                            {/if}

                            {#if message.function_call}
                              <pre class="tool-block">{JSON.stringify(message.function_call, null, 2)}</pre>
                            {/if}
                          </div>
                        {/each}
                      </div>
                    </div>
                  </td>
                </tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>

      <div class="pagination">
        <button type="button" onclick={gotoPrev} disabled={page === 0 || loading}>
          ← Previous
        </button>
        <span class="page-info">
          Page {page + 1} of {totalPages}
        </span>
        <button
          type="button"
          onclick={gotoNext}
          disabled={page >= totalPages - 1 || loading}
        >
          Next →
        </button>
      </div>
    {/if}
  {/if}
</div>

<style>
  .traces-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
    background: var(--background-fill-primary, white);
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }
  .search-wrap {
    flex: 1;
  }
  .search-wrap input,
  .filter-wrap select {
    width: 100%;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
    font-size: 14px;
    padding: 10px 12px;
    font-family: inherit;
  }
  .filter-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--body-text-color, #1f2937);
    font-size: 14px;
    white-space: nowrap;
  }
  .count {
    margin-left: auto;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 14px;
    white-space: nowrap;
  }
  .traces-table-wrap {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    overflow: hidden;
    transition: opacity 0.15s ease;
  }
  .traces-table-wrap.dim {
    opacity: 0.55;
  }
  .traces-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    table-layout: fixed;
  }
  .trace-id-col {
    width: 140px;
  }
  .request-col {
    width: auto;
  }
  .run-col {
    width: 180px;
  }
  .step-col {
    width: 76px;
  }
  .request-time-col {
    width: 150px;
  }
  .traces-table th {
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background: var(--background-fill-primary, white);
  }
  .traces-table td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color, #1f2937);
    vertical-align: top;
  }
  .trace-row {
    cursor: pointer;
  }
  .trace-row:hover {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .trace-id-chip {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 13px;
    color: #000;
  }
  .request {
    font-weight: 500;
    margin-bottom: 4px;
  }
  .preview {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 13px;
    line-height: 1.45;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .expanded-row td {
    padding: 0;
    background: var(--background-fill-secondary, #fafafa);
  }
  .trace-detail {
    padding: 16px 18px 18px;
  }
  .detail-meta {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 13px;
    margin-bottom: 14px;
  }
  .conversation {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .message {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, white);
    padding: 12px;
  }
  .message-role {
    margin-bottom: 8px;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .message-tag {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: 999px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 500;
    text-transform: none;
    letter-spacing: 0;
  }
  .message-content,
  .tool-block {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: inherit;
    color: var(--body-text-color, #1f2937);
    line-height: 1.5;
  }
  .message-details summary {
    cursor: pointer;
    margin-bottom: 8px;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .tool-blocks {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 10px;
  }
  .tool-block {
    background: var(--background-fill-secondary, #f9fafb);
    border-radius: var(--radius-md, 6px);
    padding: 10px;
    overflow-x: auto;
  }
  .message-parts {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .trace-image {
    max-width: 100%;
    max-height: 360px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
  }
  .empty-state {
    max-width: 640px;
    padding: 40px 24px;
    color: var(--body-text-color, #1f2937);
  }
  .empty-state h2 {
    margin: 0 0 8px;
    font-size: 20px;
    font-weight: 700;
  }
  .empty-state p {
    margin: 12px 0 8px;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 16px 0 4px;
  }
  .pagination button {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
    font-size: 14px;
    padding: 8px 14px;
    cursor: pointer;
    font-family: inherit;
  }
  .pagination button:hover:not(:disabled) {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .pagination button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .page-info {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 14px;
    min-width: 120px;
    text-align: center;
  }
  @media (max-width: 1100px) {
    .toolbar {
      flex-wrap: wrap;
    }
    .count {
      margin-left: 0;
    }
  }
</style>
