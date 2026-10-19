<script>
  import { tick } from "svelte";
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import ArtifactVersionDetail from "../components/ArtifactVersionDetail.svelte";
  import { getRunSummary, getRunArtifacts, getConsoleOutput } from "../lib/api.js";
  import { copyTextToClipboard } from "../lib/clipboard.js";
  import { parseConsoleLines } from "../lib/console.js";
  import {
    getQueryParam,
    navigateTo,
    setArtifactSelectionParams,
  } from "../lib/router.js";
  import { formatSize } from "../lib/format.js";

  const CONSOLE_POLL_MS = 10000;

  let { project = null } = $props();

  let runName = $state(null);
  let runId = $state(null);
  let summary = $state(null);
  let loading = $state(false);
  let runArtifacts = $state({ input: [], output: [] });
  let expandedArtifact = $state({});
  let consoleOutput = $state(null);
  let consoleEl = $state(null);
  let commandCopied = $state(false);

  let command = $derived(summary?.config?._Command ?? null);
  let displayConfig = $derived(
    summary?.config
      ? Object.fromEntries(Object.entries(summary.config).filter(([key]) => key !== "_Command"))
      : null,
  );
  let consoleEnabled = $derived(consoleOutput?.enabled === true);
  let consoleLines = $derived(parseConsoleLines(consoleOutput?.text ?? ""));

  function currentRunRef() {
    return runId ? { id: runId, name: runName } : runName;
  }

  async function copyCommand() {
    if (!(await copyTextToClipboard(command))) return;
    commandCopied = true;
    setTimeout(() => (commandCopied = false), 1500);
  }

  async function loadConsole() {
    const seq = loadSeq;
    if (!project || (!runName && !runId)) {
      consoleOutput = null;
      return;
    }
    try {
      const output = await getConsoleOutput(project, currentRunRef());
      if (seq !== loadSeq) return;
      const el = consoleEl;
      const atBottom = !el || el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      consoleOutput = output;
      if (atBottom) {
        await tick();
        if (consoleEl) consoleEl.scrollTop = consoleEl.scrollHeight;
      }
    } catch (e) {
      if (seq === loadSeq) console.error("Failed to load console output:", e);
    }
  }

  async function downloadConsole() {
    const output = await getConsoleOutput(project, currentRunRef(), null);
    if (!output?.text) return;
    const blob = new Blob([output.text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(summary?.run || "run").replace(/\//g, "_")}-console.log`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function toggleArtifact(key) {
    expandedArtifact[key] = !expandedArtifact[key];
  }

  function openInArtifacts(name, version) {
    setArtifactSelectionParams(name, version);
    navigateTo("artifacts");
  }

  let loadSeq = 0;

  function syncParamsFromUrl() {
    runId = getQueryParam("selected_run_id");
    runName = getQueryParam("selected_run");
  }

  $effect(() => {
    syncParamsFromUrl();
    window.addEventListener("popstate", syncParamsFromUrl);
    return () => window.removeEventListener("popstate", syncParamsFromUrl);
  });

  async function loadDetail() {
    const seq = ++loadSeq;
    expandedArtifact = {};
    consoleOutput = null;
    if (!project || (!runName && !runId)) {
      summary = null;
      runArtifacts = { input: [], output: [] };
      loading = false;
      return;
    }

    loading = true;
    const runRef = currentRunRef();
    const artifactsPromise = getRunArtifacts(project, runRef).catch(() => ({
      input: [],
      output: [],
    }));
    try {
      const loadedSummary = await getRunSummary(project, runRef);
      if (seq !== loadSeq) return;
      summary = loadedSummary;
      if (loadedSummary?.run) {
        runName = loadedSummary.run;
      }
    } catch (e) {
      if (seq === loadSeq) console.error("Failed to load run detail:", e);
    } finally {
      if (seq === loadSeq) loading = false;
    }
    if (seq === loadSeq) loadConsole();
    const artifacts = await artifactsPromise;
    if (seq !== loadSeq) return;
    runArtifacts = artifacts;
  }

  $effect(() => {
    project;
    runName;
    runId;
    loadDetail();
  });

  $effect(() => {
    if (!consoleEnabled) return;
    const timer = setInterval(() => {
      if (!document.hidden) loadConsole();
    }, CONSOLE_POLL_MS);
    return () => clearInterval(timer);
  });
</script>

{#snippet artifactEntry(art, dir)}
  {@const key = `${dir}:${art.name}@v${art.version}`}
  <div class="artifact-entry">
    <div class="artifact-row">
      <button class="row-toggle" onclick={() => toggleArtifact(key)}>
        <span class="chevron" class:open={expandedArtifact[key]}>▾</span>
        <span class="art-name"
          >{art.name}<span class="art-ver">:v{art.version}</span></span
        >
        <span class="art-type">{art.type}</span>
        <span class="art-size">{formatSize(art.size_bytes)}</span>
      </button>
      <button
        class="open-btn"
        onclick={() => openInArtifacts(art.name, art.version)}
        title="Open in Artifacts"
        aria-label="Open {art.name} v{art.version} in the Artifacts tab"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
          <polyline points="15 3 21 3 21 9" />
          <line x1="10" y1="14" x2="21" y2="3" />
        </svg>
      </button>
    </div>
    {#if expandedArtifact[key]}
      <ArtifactVersionDetail {project} name={art.name} version={art.version} />
    {/if}
  </div>
{/snippet}

<div class="run-detail-page">
  <button class="back-link" onclick={() => navigateTo("runs")}>
    <span aria-hidden="true">←</span>
    All runs
  </button>
  {#if loading}
    <LoadingTrackio />
  {:else if !summary}
    <div class="empty-state">
      <h2>Open a run</h2>
      <p>
        Choose a run from the <strong>Runs</strong> page or follow a run name from the sidebar. This view shows the
        project name, log count, last step, metric keys, and any logged config.
      </p>
      <pre><code>{'import trackio\ntrackio.init(project="my-project", config={"lr": 1e-3})\ntrackio.log({"loss": 0.5})\ntrackio.finish()'}</code></pre>
      <p>Config passed to <code>trackio.init()</code> appears under Configuration when present.</p>
    </div>
  {:else}
    <div class="detail-card">
      <h2>{summary.run}</h2>
      <div class="detail-grid">
        <div class="detail-item">
          <span class="detail-label">Project</span>
          <span class="detail-value">{summary.project}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Total Logs</span>
          <span class="detail-value">{summary.num_logs}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Last Step</span>
          <span class="detail-value">{summary.last_step ?? "N/A"}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Metrics</span>
          <span class="detail-value"
            >{summary.metrics && summary.metrics.length
              ? summary.metrics.join(", ")
              : "N/A"}</span
          >
        </div>
      </div>

      {#if command}
        <h3>Command</h3>
        <div class="command-block">
          <code>{command}</code>
          <button
            class="icon-btn"
            class:copied={commandCopied}
            onclick={copyCommand}
            title="Copy command"
            aria-label="Copy command"
          >
            {#if commandCopied}
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3.5 8.5l3 3 6-7" />
              </svg>
            {:else}
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <rect x="5" y="5" width="8" height="8" rx="1.5" />
                <path d="M11 5V3.5A1.5 1.5 0 009.5 2h-6A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5" />
              </svg>
            {/if}
          </button>
        </div>
      {/if}

      {#if consoleOutput}
        <div class="section-header">
          <h3>Console output</h3>
          {#if consoleEnabled && consoleLines.length > 0}
            <button class="text-btn" onclick={downloadConsole}>Download</button>
          {/if}
        </div>
        {#if !consoleEnabled}
          <div class="console-placeholder">
            <p>
              Console output was not captured for this run. To save everything the script writes to
              stdout and stderr, pass <code>capture_console=True</code> to <code>trackio.init()</code>:
            </p>
            <pre><code>{`trackio.init(project="${summary.project}", capture_console=True)`}</code></pre>
            <p>
              or set <code>TRACKIO_CAPTURE_CONSOLE=1</code> in the environment before launching the
              script.
            </p>
          </div>
        {:else if consoleLines.length === 0}
          <div class="console-placeholder">
            <p>No console output has been captured yet.</p>
          </div>
        {:else}
          {#if consoleOutput.truncated}
            <p class="console-note">Showing the most recent output. Download to see all of it.</p>
          {/if}
          <div class="console-block" bind:this={consoleEl}>
            {#each consoleLines as line}
              <div class="console-line">
                <span class="console-time">{line.time}</span>
                <span class="console-text">{line.text}</span>
              </div>
            {/each}
          </div>
        {/if}
      {/if}

      {#if displayConfig}
        <h3>Configuration</h3>
        <pre class="config-block">{JSON.stringify(displayConfig, null, 2)}</pre>
      {/if}

      {#if runArtifacts.output.length > 0}
        <h3>Output artifacts</h3>
        <div class="artifact-links">
          {#each runArtifacts.output as art}
            {@render artifactEntry(art, "out")}
          {/each}
        </div>
      {/if}

      {#if runArtifacts.input.length > 0}
        <h3>Input artifacts</h3>
        <div class="artifact-links">
          {#each runArtifacts.input as art}
            {@render artifactEntry(art, "in")}
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .run-detail-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }
  .back-link {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin: 0 0 12px;
    padding: 0;
    border: 0;
    background: none;
    color: var(--body-text-color-subdued, #6b7280);
    font: inherit;
    font-size: var(--text-sm, 12px);
    font-weight: 500;
    cursor: pointer;
  }
  .back-link:hover {
    color: var(--body-text-color, #1f2937);
    text-decoration: underline;
  }
  .detail-card {
    background: var(--background-fill-primary, white);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    padding: 24px;
    max-width: 800px;
  }
  .detail-card h2 {
    color: var(--body-text-color, #1f2937);
    margin: 0 0 16px;
    font-size: var(--text-xl, 22px);
  }
  .detail-card h3 {
    color: var(--body-text-color, #1f2937);
    margin: 20px 0 8px;
    font-size: var(--text-lg, 16px);
  }
  .detail-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
  }
  .detail-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .detail-label {
    font-size: var(--text-xs, 10px);
    font-weight: 600;
    color: var(--body-text-color-subdued, #9ca3af);
    text-transform: uppercase;
  }
  .detail-value {
    font-size: var(--text-md, 14px);
    color: var(--body-text-color, #1f2937);
  }
  .config-block {
    background: var(--background-fill-secondary, #f9fafb);
    padding: 12px;
    border-radius: var(--radius-lg, 8px);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    overflow-x: auto;
  }
  .command-block {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    background: var(--background-fill-secondary, #f9fafb);
    padding: 8px 8px 8px 12px;
    border-radius: var(--radius-lg, 8px);
    border: 1px solid var(--border-color-primary, #e5e7eb);
  }
  .command-block code {
    flex: 1;
    min-width: 0;
    padding-top: 4px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .icon-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    border: none;
    background: none;
    border-radius: var(--radius-md, 4px);
    color: var(--body-text-color-subdued, #6b7280);
    cursor: pointer;
    transition:
      background-color 0.15s,
      color 0.15s;
  }
  .icon-btn:hover {
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
  }
  .icon-btn.copied {
    color: var(--color-accent, #f97316);
  }
  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin: 20px 0 8px;
  }
  .detail-card .section-header h3 {
    margin: 0;
  }
  .text-btn {
    padding: 4px 10px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
    font: inherit;
    font-size: var(--text-sm, 12px);
    cursor: pointer;
  }
  .text-btn:hover {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .console-block {
    max-height: 360px;
    overflow: auto;
    background: var(--background-fill-secondary, #f9fafb);
    padding: 8px 12px;
    border-radius: var(--radius-lg, 8px);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: var(--text-sm, 12px);
    line-height: 1.5;
    color: var(--body-text-color, #1f2937);
  }
  .console-line {
    display: flex;
    gap: 12px;
  }
  .console-time {
    flex-shrink: 0;
    color: var(--body-text-color-subdued, #9ca3af);
    user-select: none;
  }
  .console-text {
    white-space: pre-wrap;
    word-break: break-word;
  }
  .console-note {
    margin: 0 0 6px;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .console-placeholder {
    padding: 12px 14px;
    border: 1px dashed var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .console-placeholder p {
    margin: 0;
  }
  .console-placeholder pre {
    margin: 8px 0;
    padding: 8px 12px;
    background: var(--background-fill-secondary, #f9fafb);
    border-radius: var(--radius-md, 6px);
    overflow-x: auto;
  }
  .console-placeholder code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: var(--body-text-color, #1f2937);
  }
  .artifact-links {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .artifact-entry {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    overflow: hidden;
  }
  .artifact-row {
    display: flex;
    align-items: center;
  }
  .row-toggle {
    display: flex;
    align-items: center;
    gap: 12px;
    flex: 1;
    min-width: 0;
    text-align: left;
    background: none;
    border: none;
    padding: 8px 12px;
    cursor: pointer;
  }
  .row-toggle:hover {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .open-btn {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    margin-right: 6px;
    border: none;
    background: none;
    color: var(--body-text-color-subdued, #9ca3af);
    border-radius: var(--radius-sm, 4px);
    cursor: pointer;
    transition:
      color 0.15s,
      background-color 0.15s;
  }
  .open-btn:hover {
    color: var(--color-accent, #f97316);
    background: var(--background-fill-secondary, #f9fafb);
  }
  .chevron {
    flex-shrink: 0;
    display: inline-block;
    color: var(--body-text-color, #1f2937);
    font-size: 14px;
    transition: transform 0.15s;
    transform: rotate(-90deg);
  }
  .chevron.open {
    transform: none;
  }
  .art-name {
    font-weight: 600;
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-md, 14px);
  }
  .art-ver {
    font-weight: 400;
    color: var(--body-text-color-subdued, #6b7280);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .art-type {
    font-size: var(--text-xs, 11px);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--body-text-color-subdued, #6b7280);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: 9px;
    padding: 1px 8px;
  }
  .art-size {
    margin-left: auto;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
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
  .empty-state pre {
    background: var(--background-fill-secondary, #f9fafb);
    padding: 16px;
    border-radius: var(--radius-lg, 8px);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    font-size: 13px;
    overflow-x: auto;
  }
  .empty-state code {
    background: var(--background-fill-secondary, #f0f0f0);
    padding: 1px 5px;
    border-radius: var(--radius-sm, 4px);
    font-size: 13px;
  }
  .empty-state pre code {
    background: none;
    padding: 0;
  }
</style>
