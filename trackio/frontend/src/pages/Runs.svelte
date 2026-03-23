<script>
  import GradioTable from "../components/GradioTable.svelte";
  import { getRunsForProject, getProjectSummary, getLogs, deleteRun, renameRun } from "../lib/api.js";
  import { navigateTo, setQueryParam } from "../lib/router.js";

  let { project = null, onRunsChanged = null } = $props();

  let runsData = $state([]);
  let loading = $state(false);
  let selectedIndices = $state(new Set());
  let renamingIndex = $state(-1);
  let renameValue = $state("");

  async function loadRuns() {
    if (!project) {
      runsData = [];
      return;
    }

    loading = true;
    try {
      const summary = await getProjectSummary(project);
      const runNames = summary.runs || [];
      const data = [];

      for (const name of runNames) {
        const logs = await getLogs(project, name);
        const numSteps = logs ? logs.length : 0;
        const lastStep = logs && logs.length > 0 ? logs[logs.length - 1].step : 0;
        data.push({ name, numSteps, lastStep });
      }

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

  function viewRunDetail(row) {
    const runName = row[0];
    setQueryParam("selected_run", runName);
    navigateTo("run-detail");
  }

  async function handleDelete(runName) {
    if (!confirm(`Delete run "${runName}"? This cannot be undone.`)) return;
    try {
      await deleteRun(project, runName);
      await loadRuns();
      if (onRunsChanged) onRunsChanged();
    } catch (e) {
      console.error("Failed to delete run:", e);
    }
  }

  function startRename(index, currentName) {
    renamingIndex = index;
    renameValue = currentName;
  }

  async function submitRename(oldName) {
    const newName = renameValue.trim();
    if (!newName || newName === oldName) {
      renamingIndex = -1;
      return;
    }
    try {
      await renameRun(project, oldName, newName);
      renamingIndex = -1;
      await loadRuns();
      if (onRunsChanged) onRunsChanged();
    } catch (e) {
      console.error("Failed to rename run:", e);
    }
  }

  function handleRenameKeydown(e, oldName) {
    if (e.key === "Enter") submitRename(oldName);
    if (e.key === "Escape") renamingIndex = -1;
  }
</script>

<div class="runs-page">
  {#if loading}
    <div class="loading">Loading runs...</div>
  {:else if runsData.length === 0}
    <div class="empty-state">No runs found for this project.</div>
  {:else}
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
        {#each runsData as run, i}
          <tr>
            <td class="actions-cell">
              <button class="action-btn" title="Rename" onclick={() => startRename(i, run.name)}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M17 3a2.83 2.83 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
                </svg>
              </button>
              <button class="action-btn delete-btn" title="Delete" onclick={() => handleDelete(run.name)}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/>
                  <path d="M10 11v6"/>
                  <path d="M14 11v6"/>
                  <path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/>
                </svg>
              </button>
            </td>
            <td class="run-name-cell">
              {#if renamingIndex === i}
                <input
                  class="rename-input"
                  type="text"
                  bind:value={renameValue}
                  onkeydown={(e) => handleRenameKeydown(e, run.name)}
                  onblur={() => submitRename(run.name)}
                />
              {:else}
                <button class="link-btn" onclick={() => { setQueryParam("selected_run", run.name); navigateTo("run-detail"); }}>
                  {run.name}
                </button>
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
  .loading,
  .empty-state {
    padding: 40px;
    text-align: center;
    color: var(--body-text-color-subdued, #9ca3af);
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
  .runs-table tbody tr:nth-child(even) {
    background: var(--table-even-background, #f9fafb);
  }
  .runs-table tr:hover {
    background: var(--background-fill-secondary, #f3f4f6);
  }
  .run-name-cell {
    font-weight: 500;
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
  .actions-cell {
    display: flex;
    gap: 4px;
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
</style>
