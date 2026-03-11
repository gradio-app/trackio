<script>
  import LinePlot from "../components/LinePlot.svelte";
  import Accordion from "../components/Accordion.svelte";
  import { getLogs } from "../lib/api.js";
  import {
    processRunData,
    getMetricColumns,
    groupMetricsByPrefix,
    filterMetricsByRegex,
    downsample,
  } from "../lib/dataProcessing.js";
  import { buildColorMap } from "../lib/stores.js";

  let {
    project = null,
    selectedRuns = [],
    allRuns = [],
    smoothing = 10,
    xAxis = "step",
    logScaleX = false,
    logScaleY = false,
    metricFilter = "",
    showHeaders = true,
  } = $props();

  let masterData = $state([]);
  let xColumn = $state("step");
  let metrics = $state([]);
  let xLim = $state(null);
  let loading = $state(false);

  let colorMap = $derived(buildColorMap(allRuns, smoothing));

  let metricGroups = $derived.by(() => {
    let filtered = metricFilter
      ? filterMetricsByRegex(metrics, metricFilter)
      : metrics;
    return groupMetricsByPrefix(filtered);
  });

  let groupNames = $derived(Object.keys(metricGroups));

  async function loadData() {
    if (!project || selectedRuns.length === 0) {
      masterData = [];
      metrics = [];
      return;
    }

    loading = true;
    try {
      const allRows = [];
      for (const run of selectedRuns) {
        const logs = await getLogs(project, run);
        const result = processRunData(
          logs,
          run,
          smoothing,
          xAxis,
          logScaleX,
          logScaleY,
        );
        if (result) {
          allRows.push(...result.rows);
          xColumn = result.xColumn;
        }
      }
      masterData = allRows;

      const originals = allRows.filter(
        (r) => r.data_type === "original" || !r.data_type,
      );
      const cols = getMetricColumns(originals).filter(
        (c) => c !== xColumn && c !== "run" && c !== "data_type" && c !== "x_axis",
      );
      metrics = cols;
    } catch (e) {
      console.error("Failed to load metrics data:", e);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    project;
    selectedRuns;
    smoothing;
    xAxis;
    logScaleX;
    logScaleY;
    loadData();
  });

  function handlePlotSelect(range) {
    if (range && range.length === 2) {
      xLim = range;
    }
  }

  function handleDoubleClick() {
    xLim = null;
  }

  function getPlotData(metric) {
    const relevant = masterData.filter(
      (r) => r[metric] != null && r[metric] !== undefined,
    );
    const result = downsample(relevant, xColumn, metric, "run", xLim);
    return result.data;
  }
</script>

<div class="metrics-page">
  {#if loading && masterData.length === 0}
    <div class="loading">Loading metrics...</div>
  {:else if masterData.length === 0}
    <div class="empty-state">
      <h2>Start logging with Trackio</h2>
      <pre><code>{'import trackio\ntrackio.init(project="my-project")\nfor i in range(10):\n    trackio.log({"loss": 1/(i+1)})\ntrackio.finish()'}</code></pre>
    </div>
  {:else}
    {#each groupNames as groupName}
      {@const group = metricGroups[groupName]}
      {@const directCount = group.direct.length}
      {@const subCount = Object.values(group.subgroups).reduce((a, b) => a + b.length, 0)}
      {@const totalCount = directCount + subCount}

      <Accordion
        label="{groupName} ({totalCount})"
        open={true}
        hidden={!showHeaders}
      >
        {#if group.direct.length > 0}
          <div class="plot-grid">
            {#each group.direct as metric}
              {@const plotData = getPlotData(metric)}
              {#if plotData.length > 0}
                <LinePlot
                  data={plotData}
                  x={xColumn}
                  y={metric}
                  title={metric}
                  {colorMap}
                  {xLim}
                  onSelect={handlePlotSelect}
                  onDoubleClick={handleDoubleClick}
                />
              {/if}
            {/each}
          </div>
        {/if}

        {#each Object.entries(group.subgroups) as [subName, subMetrics]}
          <Accordion
            label="{subName} ({subMetrics.length})"
            open={true}
            hidden={!showHeaders}
          >
            <div class="plot-grid">
              {#each subMetrics as metric}
                {@const plotData = getPlotData(metric)}
                {#if plotData.length > 0}
                  <LinePlot
                    data={plotData}
                    x={xColumn}
                    y={metric}
                    title={metric}
                    {colorMap}
                    {xLim}
                    onSelect={handlePlotSelect}
                    onDoubleClick={handleDoubleClick}
                  />
                {/if}
              {/each}
            </div>
          </Accordion>
        {/each}
      </Accordion>
    {/each}
  {/if}
</div>

<style>
  .metrics-page {
    padding: 16px;
    overflow-y: auto;
    flex: 1;
  }
  .plot-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
  }
  .loading {
    padding: 40px;
    text-align: center;
    color: var(--text-secondary);
    font-size: 14px;
  }
  .empty-state {
    padding: 40px;
    text-align: center;
    color: var(--text-secondary);
  }
  .empty-state h2 {
    color: var(--text-primary);
    margin-bottom: 16px;
  }
  .empty-state pre {
    display: inline-block;
    text-align: left;
    background: var(--bg-secondary);
    padding: 16px;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-color);
    font-size: 13px;
  }
</style>
