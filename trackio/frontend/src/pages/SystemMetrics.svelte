<script>
  import { onMount } from "svelte";
  import LinePlot from "../components/LinePlot.svelte";
  import Accordion from "../components/Accordion.svelte";
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getSystemLogs } from "../lib/api.js";
  import { groupMetricsByPrefix, computeMetricPlotData } from "../lib/dataProcessing.js";
  import { buildColorMap } from "../lib/stores.js";

  let {
    project = null,
    selectedRuns = [],
    smoothing = 5,
    appBootstrapReady = false,
  } = $props();

  let systemData = $state([]);
  let metricNames = $state([]);
  let xLim = $state(null);
  let hasLoaded = $state(false);
  let metricOrder = $state({});
  let dragState = $state({ group: null, index: -1 });

  let rawDataCache = new Map();
  let refreshTimer = null;

  let colorMap = $derived(buildColorMap(selectedRuns));

  let metricGroups = $derived(groupMetricsByPrefix(metricNames));
  let groupNames = $derived(Object.keys(metricGroups));

  let plotDataByMetric = $derived.by(() => {
    const map = new Map();
    const lim = xLim;
    for (const m of metricNames) {
      map.set(m, computeMetricPlotData(systemData, "time", m, lim));
    }
    return map;
  });

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
      systemData = [];
      metricNames = [];
      return;
    }

    const allRows = [];
    const allMetrics = new Set();

    for (const run of selectedRuns) {
      const logs = rawDataCache.get(run);
      if (!logs || logs.length === 0) continue;

      const firstTs = new Date(logs[0].timestamp).getTime();
      logs.forEach((row) => {
        const timeSeconds = (new Date(row.timestamp).getTime() - firstTs) / 1000;
        Object.keys(row).forEach((k) => {
          if (typeof row[k] === "number" && k !== "step" && k !== "time") {
            allMetrics.add(k);
          }
        });
        allRows.push({ ...row, time: timeSeconds, run, data_type: "original" });
      });
    }

    metricNames = Array.from(allMetrics).sort();
    systemData = allRows;
  }

  async function fetchNewRuns() {
    if (!appBootstrapReady) {
      hasLoaded = false;
      return;
    }
    if (!project || selectedRuns.length === 0) {
      systemData = [];
      metricNames = [];
      hasLoaded = true;
      return;
    }

    let fetched = false;
    for (const run of selectedRuns) {
      if (!rawDataCache.has(run)) {
        const logs = await getSystemLogs(project, run);
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
      const logs = await getSystemLogs(project, run);
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
    if (hasLoaded) {
      processFromCache();
    }
  });

  onMount(() => {
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

</script>

<div class="system-page">
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
  {:else if systemData.length === 0}
    <div class="empty-state">
      <h2>No System Metrics Available</h2>
      <p>System metrics will appear here once logged. To enable automatic logging:</p>
      <pre><code>{'import trackio\n\n# Auto-enabled when hardware is detected (NVIDIA GPU or Apple Silicon)\nrun = trackio.init(project="my-project")\n\n# Or explicitly enable it:\nrun = trackio.init(project="my-project", auto_log_gpu=True)\n\n# You can also manually log system metrics:\ntrackio.log_gpu()'}</code></pre>
      <p><strong>Setup:</strong></p>
      <ul>
        <li><strong>NVIDIA GPU:</strong> <code>pip install trackio[gpu]</code> (requires <code>nvidia-ml-py</code>)</li>
        <li><strong>Apple Silicon:</strong> <code>pip install trackio[apple-gpu]</code> (requires <code>psutil</code>)</li>
      </ul>
    </div>
  {:else}
    {#each groupNames as groupName}
      {@const group = metricGroups[groupName]}
      {@const directKey = `sys:${groupName}`}
      {@const orderedDirect = getOrderedMetrics(directKey, group.direct)}
      <Accordion label={groupName} open={true}>
        <div class="plot-grid">
          {#each orderedDirect as metric, i}
            {@const plotResult = plotDataByMetric.get(metric) ?? { data: [], yExtent: undefined }}
            {@const plotData = plotResult.data}
            {@const yExtent = plotResult.yExtent}
            {#if plotData.length > 0}
              <LinePlot
                data={plotData}
                x="time"
                y={metric}
                title={metric}
                {colorMap}
                {xLim}
                {yExtent}
                onSelect={handlePlotSelect}
                onResetZoom={handleResetZoom}
                draggable={true}
                ondragstart={(e) => handleDragStart(directKey, i, e)}
                ondragover={(e) => handleDragOver(directKey, i, e)}
                ondrop={(e) => handleDrop(directKey, i, orderedDirect, e)}
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
    min-height: 0;
  }
  .plot-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
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
  .empty-state ul {
    list-style: disc;
    padding-left: 20px;
    margin: 4px 0 0;
  }
  .empty-state li {
    margin: 4px 0;
    color: var(--body-text-color, #1f2937);
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
