<script>
  import LinePlot from "../components/LinePlot.svelte";
  import Accordion from "../components/Accordion.svelte";
  import { getSystemMetricsForRun, getSystemLogs } from "../lib/api.js";
  import { groupMetricsByPrefix, downsample } from "../lib/dataProcessing.js";
  import { buildColorMap } from "../lib/stores.js";

  let {
    project = null,
    runs = [],
    selectedRuns = [],
    smoothing = 5,
  } = $props();

  let systemData = $state([]);
  let metricNames = $state([]);
  let xLim = $state(null);
  let loading = $state(false);

  let colorMap = $derived(buildColorMap(selectedRuns));

  let metricGroups = $derived(groupMetricsByPrefix(metricNames));
  let groupNames = $derived(Object.keys(metricGroups));

  async function loadData() {
    if (!project || selectedRuns.length === 0) {
      systemData = [];
      metricNames = [];
      return;
    }

    loading = true;
    try {
      const allRows = [];
      const allMetrics = new Set();

      for (const run of selectedRuns) {
        const logs = await getSystemLogs(project, run);
        if (!logs || logs.length === 0) continue;

        const firstTs = new Date(logs[0].timestamp).getTime();
        logs.forEach((row) => {
          const timeSeconds =
            (new Date(row.timestamp).getTime() - firstTs) / 1000;
          Object.keys(row).forEach((k) => {
            if (
              typeof row[k] === "number" &&
              k !== "step" &&
              k !== "time"
            ) {
              allMetrics.add(k);
            }
          });

          allRows.push({ ...row, time: timeSeconds, run, data_type: "original" });
        });
      }

      metricNames = Array.from(allMetrics).sort();
      systemData = allRows;
    } catch (e) {
      console.error("Failed to load system data:", e);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    project;
    selectedRuns;
    smoothing;
    loadData();
  });

  function getPlotData(metric) {
    return systemData.filter(
      (r) => r[metric] != null && r[metric] !== undefined,
    );
  }
</script>

<div class="system-page">
  {#if loading && systemData.length === 0}
    <div class="loading">Loading system metrics...</div>
  {:else if systemData.length === 0}
    <div class="empty-state">
      <p>No system metrics found. Enable GPU logging:</p>
      <pre><code>trackio.init(project="my-project", auto_log_gpu=True)</code></pre>
    </div>
  {:else}
    {#each groupNames as groupName}
      {@const group = metricGroups[groupName]}
      <Accordion label={groupName} open={true}>
        <div class="plot-grid">
          {#each group.direct as metric}
            {@const plotData = getPlotData(metric)}
            {#if plotData.length > 0}
              <LinePlot
                data={plotData}
                x="time"
                y={metric}
                title={metric}
                {colorMap}
                {xLim}
              />
            {/if}
          {/each}
        </div>
      </Accordion>
    {/each}
  {/if}
</div>

<style>
  .system-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }
  .plot-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
  }
  .loading,
  .empty-state {
    padding: 40px;
    text-align: center;
    color: var(--body-text-color-subdued, #9ca3af);
  }
  .empty-state pre {
    display: inline-block;
    text-align: left;
    background: var(--background-fill-secondary, #f9fafb);
    padding: 12px;
    border-radius: var(--radius-lg, 8px);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    font-size: 13px;
  }
</style>
