<script>
  import { getRunsForProject, getProjectSummary, getLogs } from "../lib/api.js";
  import { navigateTo, setQueryParam } from "../lib/router.js";

  let { project = null } = $props();

  let runsData = $state([]);
  let loading = $state(false);
  let selectedIndices = $state(new Set());

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

  function toggleSelect(i) {
    const next = new Set(selectedIndices);
    if (next.has(i)) {
      next.delete(i);
    } else {
      next.add(i);
    }
    selectedIndices = next;
  }

  function toggleAll() {
    if (selectedIndices.size === runsData.length) {
      selectedIndices = new Set();
    } else {
      selectedIndices = new Set(runsData.map((_, i) => i));
    }
  }

  function viewRunDetail(runName) {
    setQueryParam("selected_run", runName);
    navigateTo("run-detail");
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
          <th class="check-col">
            <input
              type="checkbox"
              checked={selectedIndices.size === runsData.length}
              onchange={toggleAll}
            />
          </th>
          <th>Run Name</th>
          <th>Steps</th>
          <th>Last Step</th>
        </tr>
      </thead>
      <tbody>
        {#each runsData as run, i}
          <tr class:selected={selectedIndices.has(i)}>
            <td class="check-col">
              <input
                type="checkbox"
                checked={selectedIndices.has(i)}
                onchange={() => toggleSelect(i)}
              />
            </td>
            <td>
              <button
                class="run-link"
                onclick={() => viewRunDetail(run.name)}
              >
                {run.name}
              </button>
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
    padding: 16px;
    overflow-y: auto;
    flex: 1;
  }
  .runs-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .runs-table th,
  .runs-table td {
    padding: 8px 12px;
    border: 1px solid var(--border-color);
    text-align: left;
  }
  .runs-table th {
    background: var(--bg-secondary);
    font-weight: 600;
    color: var(--text-primary);
    position: sticky;
    top: 0;
  }
  .runs-table td {
    color: var(--text-secondary);
  }
  .runs-table tr.selected {
    background: var(--accent-light);
  }
  .check-col {
    width: 40px;
    text-align: center;
  }
  .run-link {
    border: none;
    background: none;
    color: var(--accent-color);
    cursor: pointer;
    font-size: 13px;
    padding: 0;
  }
  .run-link:hover {
    text-decoration: underline;
  }
  .loading,
  .empty-state {
    padding: 40px;
    text-align: center;
    color: var(--text-secondary);
  }
</style>
