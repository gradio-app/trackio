<script>
  import { tick } from "svelte";
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getProjectSummary, getRunSummary, deleteRun, renameRun } from "../lib/api.js";
  import { navigateTo, setQueryParam } from "../lib/router.js";
  import { buildColorMap } from "../lib/stores.js";

  let {
    project = null,
    runs = [],
    onRunsChanged = null,
    runMutationAllowed = true,
  } = $props();

  let canMutateRuns = $derived(runMutationAllowed);

  let runColorMap = $derived(buildColorMap(runs));

  let runsData = $state([]);
  let loading = $state(false);
  let renamingIndex = $state(-1);
  let renameValue = $state("");
  let renameInput = $state(null);
  let filterText = $state("");

  let filteredRuns = $derived(
    filterText
      ? runsData.filter((r) => r.name.toLowerCase().includes(filterText.toLowerCase()))
      : runsData,
  );

  async function loadRuns() {
    if (!project) {
      runsData = [];
      return;
    }

    loading = true;
    try {
      const summary = await getProjectSummary(project);
      const runRecords = summary.runs || [];
      const summaries = await Promise.all(
        runRecords.map((run) => getRunSummary(project, run)),
      );
      const data = summaries.map((s, i) => ({
        id: runRecords[i].id ?? runRecords[i].name,
        name: runRecords[i].name,
        numSteps: s.num_logs || 0,
        lastStep: s.last_step || 0,
      }));

      runsData = data;
    } catch (e) {
      console.error("Failed to load runs:", e);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    project;
    loadRuns();
  });

  async function handleDelete(run) {
    if (!canMutateRuns) return;
    if (!confirm(`Delete run "${run.name}"? This cannot be undone.`)) return;
    try {
      await deleteRun(project, run);
      await loadRuns();
      if (onRunsChanged) onRunsChanged();
    } catch (e) {
      console.error("Failed to delete run:", e);
    }
  }

  async function startRename(index, currentName) {
    if (!canMutateRuns) return;
    renamingIndex = index;
    renameValue = currentName;
    await tick();
    renameInput?.focus();
    renameInput?.select();
  }

  async function submitRename(run) {
    if (!canMutateRuns) return;
    const newName = renameValue.trim();
    if (!newName || newName === run.name) {
      renamingIndex = -1;
      return;
    }
    try {
      await renameRun(project, run, newName);
      renamingIndex = -1;
      await loadRuns();
      if (onRunsChanged) onRunsChanged();
    } catch (e) {
      console.error("Failed to rename run:", e);
    }
  }

  function handleRenameKeydown(e, run) {
    if (e.key === "Enter") submitRename(run);
    if (e.key === "Escape") renamingIndex = -1;
  }
</script>

<div class="runs-page">
  {#if loading}
    <LoadingTrackio />
  {:else if runsData.length === 0}
    <div class="empty-state">
      <h2>No runs in this project</h2>
      <p>Runs are created when you call <code>trackio.init()</code> and log at least one step. Example:</p>
      <pre><code>{'import trackio\ntrackio.init(project="my-project")\nfor i in range(10):\n    trackio.log({"loss": 1 / (i + 1)})\ntrackio.finish()'}</code></pre>
      <p>Refresh this page or wait for the dashboard to poll; new runs appear in the table with step counts.</p>
    </div>
  {:else}
    <div class="filter-section">
      <input
        type="text"
        class="filter-input"
        aria-label="Filter runs"
        placeholder="Filter runs..."
        bind:value={filterText}
      />
      {#if filterText}
        <span class="filter-count">{filteredRuns.length} of {runsData.length} runs</span>
      {/if}
    </div>
    <table class="runs-table">
      <thead>
        <tr>
          <th>Actions</th>
          <th>Run Name</th>
          <th>Steps</th>
          <th>Last Step</th>
        </tr>
      </thead>
      <tbody>
        {#each filteredRuns as run, i}
          <tr>
            <td class="actions-cell">
              <div class="actions-wrap">
              <button
                class="action-btn"
                title={canMutateRuns ? "Rename" : "Sign in with Hugging Face (write access) to rename runs"}
                disabled={!canMutateRuns}
                onclick={() => startRename(i, run.name)}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M17 3a2.83 2.83 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
                </svg>
              </button>
              <button
                class="action-btn delete-btn"
                title={canMutateRuns ? "Delete" : "Sign in with Hugging Face (write access) to delete runs"}
                disabled={!canMutateRuns}
                onclick={() => handleDelete(run)}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/>
                  <path d="M10 11v6"/>
                  <path d="M14 11v6"/>
                  <path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/>
                </svg>
              </button>
              </div>
            </td>
            <td class="run-name-cell">
              {#if renamingIndex === i}
                <input
                  class="rename-input"
                  type="text"
                  bind:value={renameValue}
                  bind:this={renameInput}
                  onkeydown={(e) => handleRenameKeydown(e, run)}
                  onblur={() => submitRename(run)}
                />
              {:else}
                <div class="run-name-with-dot">
                  <span
                    class="run-dot"
                    style:background={runColorMap[run.id] ?? "#9ca3af"}
                  ></span>
                  <button class="link-btn" onclick={() => { setQueryParam("selected_run_id", run.id); setQueryParam("selected_run", run.name); navigateTo("run-detail"); }}>
                    {run.name}
                  </button>
                </div>
              {/if}
            </td>
            <td>{run.numSteps}</td>
            <td>{run.lastStep}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>

<style>
  .runs-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
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
  .filter-section {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }
  .filter-input {
    flex: 1;
    max-width: 400px;
    padding: 8px 12px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-sm, 4px);
    font-size: var(--text-md, 14px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
  }
  .filter-input:focus {
    outline: none;
    border-color: var(--color-accent, #f97316);
  }
  .filter-count {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .runs-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-md, 14px);
  }
  .runs-table th {
    text-align: left;
    padding: 8px 12px;
    border-bottom: 2px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    font-weight: 600;
    font-size: var(--text-sm, 12px);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .runs-table td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color, #1f2937);
  }
  .runs-table tbody tr:nth-child(odd) {
    background: var(--table-odd-background-fill, var(--background-fill-primary, white));
  }
  .runs-table tbody tr:nth-child(even) {
    background: var(--table-even-background-fill, var(--background-fill-secondary, #f9fafb));
  }
  .runs-table tr:hover {
    background: var(--background-fill-secondary, #f3f4f6);
  }
  .run-name-cell {
    font-weight: 500;
  }
  .run-name-with-dot {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    max-width: 100%;
  }
  .run-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .link-btn {
    background: none;
    border: none;
    color: var(--color-accent, #f97316);
    cursor: pointer;
    font: inherit;
    font-weight: 500;
    padding: 0;
    text-align: left;
  }
  .link-btn:hover {
    text-decoration: underline;
  }
  .rename-input {
    font: inherit;
    padding: 2px 6px;
    border: 1px solid var(--color-accent, #f97316);
    border-radius: var(--radius-sm, 4px);
    outline: none;
    width: 100%;
  }
  .actions-wrap {
    display: flex;
    gap: 4px;
    align-items: center;
  }
  .action-btn {
    background: none;
    border: 1px solid transparent;
    color: var(--body-text-color-subdued, #6b7280);
    cursor: pointer;
    padding: 4px;
    border-radius: var(--radius-sm, 4px);
    display: flex;
    align-items: center;
  }
  .action-btn:hover {
    background: var(--background-fill-secondary, #f9fafb);
    border-color: var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color, #1f2937);
  }
  .delete-btn:hover {
    color: #dc2626;
    border-color: #fecaca;
    background: #fef2f2;
  }
  .action-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
    pointer-events: none;
  }
</style>
