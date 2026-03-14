<script>
  import GradioTable from "../components/GradioTable.svelte";
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

  function viewRunDetail(row) {
    const runName = row[0];
    setQueryParam("selected_run", runName);
    navigateTo("run-detail");
  }

  let tableHeaders = ["Run Name", "Steps", "Last Step"];
  let tableRows = $derived(
    runsData.map(r => [r.name, r.numSteps, r.lastStep])
  );
</script>

<div class="runs-page">
  {#if loading}
    <div class="loading">Loading runs...</div>
  {:else if runsData.length === 0}
    <div class="empty-state">No runs found for this project.</div>
  {:else}
    <GradioTable
      headers={tableHeaders}
      rows={tableRows}
      selectable={true}
      bind:selectedIndices
      onrowclick={viewRunDetail}
    />
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
</style>
