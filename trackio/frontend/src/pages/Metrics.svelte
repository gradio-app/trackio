<script>
  import { onMount } from "svelte";
  import { getQueryParam } from "../lib/router.js";
  import LinePlot from "../components/LinePlot.svelte";
  import BarPlot from "../components/BarPlot.svelte";
  import Accordion from "../components/Accordion.svelte";
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
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
    appBootstrapReady = false,
    plotOrder = [],
  } = $props();

  let masterData = $state([]);
  let xColumn = $state("step");
  let metrics = $state([]);
  let singlePointMetrics = $state(new Set());
  let xLim = $state(null);
  let hasLoaded = $state(false);
  let metricOrder = $state({});
  let dragState = $state({ group: null, index: -1 });

  let rawDataCache = new Map();
  let refreshTimer = null;

  let colorMap = $derived(buildColorMap(allRuns));

  let metricGroups = $derived.by(() => {
    let filtered = metricFilter
      ? filterMetricsByRegex(metrics, metricFilter)
      : metrics;
    return groupMetricsByPrefix(filtered, plotOrder);
  });

  let groupNames = $derived(Object.keys(metricGroups));

  function getOrderedMetrics(key, items) {
    const order = metricOrder[key];
    if (!order) return items;
    const ordered = [];
    for (const m of order) {
      if (items.includes(m)) ordered.push(m);
    }
    for (const m of items) {
      if (!ordered.includes(m)) ordered.push(m);
    }
    return ordered;
  }

  function handleDragStart(groupKey, index, e) {
    dragState = { group: groupKey, index };
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", "");
  }

  function handleDragOver(groupKey, index, e) {
    if (dragState.group !== groupKey) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }

  function handleDrop(groupKey, index, metrics, e) {
    e.preventDefault();
    if (dragState.group !== groupKey || dragState.index === index) {
      dragState = { group: null, index: -1 };
      return;
    }
    const ordered = [...metrics];
    const [moved] = ordered.splice(dragState.index, 1);
    ordered.splice(index, 0, moved);
    metricOrder = { ...metricOrder, [groupKey]: ordered };
    dragState = { group: null, index: -1 };
  }

  function processFromCache() {
    if (!project || selectedRuns.length === 0) {
      masterData = [];
      metrics = [];
      return;
    }

    const allRows = [];
    for (const run of selectedRuns) {
      const logs = rawDataCache.get(run);
      if (!logs) continue;
      const result = processRunData(logs, run, smoothing, xAxis, logScaleX, logScaleY);
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

    const countPerRunMetric = new Map();
    for (const r of originals) {
      const run = r.run;
      for (const col of cols) {
        if (r[col] == null) continue;
        const key = `${col}\0${run}`;
        countPerRunMetric.set(key, (countPerRunMetric.get(key) || 0) + 1);
      }
    }
    const sp = new Set(cols);
    for (const [key, count] of countPerRunMetric) {
      if (count > 1) {
        sp.delete(key.split("\0")[0]);
      }
    }
    singlePointMetrics = sp;
  }

  async function fetchNewRuns() {
    if (!appBootstrapReady) {
      hasLoaded = false;
      return;
    }
    if (!project || selectedRuns.length === 0) {
      masterData = [];
      metrics = [];
      hasLoaded = true;
      return;
    }

    let fetched = false;
    for (const run of selectedRuns) {
      if (!rawDataCache.has(run)) {
        const logs = await getLogs(project, run);
        rawDataCache.set(run, logs);
        fetched = true;
      }
    }

    if (fetched || !hasLoaded) {
      processFromCache();
    }
    hasLoaded = true;
  }

  async function refreshCachedRuns() {
    if (!project || selectedRuns.length === 0) return;

    let changed = false;
    for (const run of selectedRuns) {
      const logs = await getLogs(project, run);
      const prev = rawDataCache.get(run);
      if (!prev || logs.length !== prev.length) {
        rawDataCache.set(run, logs);
        changed = true;
      }
    }
    if (changed) {
      processFromCache();
    }
  }

  $effect(() => {
    project;
    selectedRuns;
    appBootstrapReady;
    rawDataCache = project ? rawDataCache : new Map();
    fetchNewRuns();
  });

  $effect(() => {
    smoothing;
    xAxis;
    logScaleX;
    logScaleY;
    if (hasLoaded) {
      processFromCache();
    }
  });

  onMount(() => {
    const xMin = getQueryParam("xmin");
    const xMax = getQueryParam("xmax");
    if (xMin != null && xMin !== "" && xMax != null && xMax !== "") {
      const lo = parseFloat(xMin);
      const hi = parseFloat(xMax);
      if (!Number.isNaN(lo) && !Number.isNaN(hi) && lo < hi) {
        xLim = [lo, hi];
      }
    }
    refreshTimer = setInterval(refreshCachedRuns, 1000);
    return () => {
      if (refreshTimer) clearInterval(refreshTimer);
    };
  });

  function handlePlotSelect(range) {
    if (range && range.length === 2) {
      xLim = range;
    }
  }

  function handleResetZoom() {
    xLim = null;
  }

  function getPlotData(metric) {
    let relevant = masterData.filter(
      (r) => r[metric] != null && r[metric] !== undefined,
    );
    if (xLim) {
      const sorted = relevant.sort((a, b) => a[xColumn] - b[xColumn]);
      let lo = 0;
      let hi = sorted.length - 1;
      while (lo < sorted.length && sorted[lo][xColumn] < xLim[0]) lo++;
      while (hi >= 0 && sorted[hi][xColumn] > xLim[1]) hi--;
      lo = Math.max(0, lo - 1);
      hi = Math.min(sorted.length - 1, hi + 1);
      relevant = sorted.slice(lo, hi + 1);
    }
    const result = downsample(relevant, xColumn, metric, "run", xLim);
    return result.data;
  }

</script>

<div class="metrics-page">
  {#if !appBootstrapReady || !hasLoaded}
    <LoadingTrackio />
  {:else if !project}
    <div class="empty-state">
      <h2>No projects</h2>
      <p>
        Create a project by calling <code>trackio.init(project="…")</code> in your training script.
      </p>
    </div>
  {:else if selectedRuns.length === 0}
    <div class="empty-state">
      <h2>No run selected</h2>
      <p>Select one or more runs in the sidebar.</p>
    </div>
  {:else if masterData.length === 0}
    <div class="empty-state">
      <h2>Start logging with Trackio</h2>
      <p>You can create a new project by calling <code>trackio.init()</code>:</p>
      <pre><code>{'import trackio\ntrackio.init(project="my-project")'}</code></pre>
      <p>Then call <code>trackio.log()</code> to log metrics:</p>
      <pre><code>{'for i in range(10):\n    trackio.log({"loss": 1/(i+1)})'}</code></pre>
      <p>Finally, call <code>trackio.finish()</code> to finish the run:</p>
      <pre><code>{'trackio.finish()'}</code></pre>
    </div>
  {:else}
    {#each groupNames as groupName}
      {@const group = metricGroups[groupName]}
      {@const directKey = `${groupName}:direct`}
      {@const orderedDirect = getOrderedMetrics(directKey, group.direct)}
      {@const directCount = group.direct.length}
      {@const subCount = Object.values(group.subgroups).reduce((a, b) => a + b.length, 0)}
      {@const totalCount = directCount + subCount}

      <Accordion
        label="{groupName} ({totalCount})"
        open={true}
        hidden={!showHeaders}
      >
        {#if orderedDirect.length > 0}
          <div class="plot-grid">
            {#each orderedDirect as metric, i}
              {@const plotData = getPlotData(metric)}
              {@const useBar = singlePointMetrics.has(metric)}
              {#if plotData.length > 0}
                {#if useBar}
                  <BarPlot
                    data={plotData}
                    y={metric}
                    title={metric}
                    {colorMap}
                    draggable={true}
                    ondragstart={(e) => handleDragStart(directKey, i, e)}
                    ondragover={(e) => handleDragOver(directKey, i, e)}
                    ondrop={(e) => handleDrop(directKey, i, orderedDirect, e)}
                  />
                {:else}
                  <LinePlot
                    data={plotData}
                    x={xColumn}
                    y={metric}
                    title={metric}
                    {colorMap}
                    {xLim}
                    onSelect={handlePlotSelect}
                    onResetZoom={handleResetZoom}
                    draggable={true}
                    ondragstart={(e) => handleDragStart(directKey, i, e)}
                    ondragover={(e) => handleDragOver(directKey, i, e)}
                    ondrop={(e) => handleDrop(directKey, i, orderedDirect, e)}
                  />
                {/if}
              {/if}
            {/each}
          </div>
        {/if}

        {#each Object.entries(group.subgroups) as [subName, subMetrics]}
          {@const subKey = `${groupName}:${subName}`}
          {@const orderedSub = getOrderedMetrics(subKey, subMetrics)}
          <Accordion
            label="{subName} ({subMetrics.length})"
            open={true}
            hidden={!showHeaders}
          >
            <div class="plot-grid">
              {#each orderedSub as metric, i}
                {@const plotData = getPlotData(metric)}
                {@const useBar = singlePointMetrics.has(metric)}
                {#if plotData.length > 0}
                  {#if useBar}
                    <BarPlot
                      data={plotData}
                      y={metric}
                      title={metric}
                      {colorMap}
                      draggable={true}
                      ondragstart={(e) => handleDragStart(subKey, i, e)}
                      ondragover={(e) => handleDragOver(subKey, i, e)}
                      ondrop={(e) => handleDrop(subKey, i, orderedSub, e)}
                    />
                  {:else}
                    <LinePlot
                      data={plotData}
                      x={xColumn}
                      y={metric}
                      title={metric}
                      {colorMap}
                      {xLim}
                      onSelect={handlePlotSelect}
                      onResetZoom={handleResetZoom}
                      draggable={true}
                      ondragstart={(e) => handleDragStart(subKey, i, e)}
                      ondragover={(e) => handleDragOver(subKey, i, e)}
                      ondrop={(e) => handleDrop(subKey, i, orderedSub, e)}
                    />
                  {/if}
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
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
    min-height: 0;
  }
  .plot-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
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
