<script>
  import { onMount } from "svelte";
  import LinePlot from "../components/LinePlot.svelte";
  import Accordion from "../components/Accordion.svelte";
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getSystemLogsBatch } from "../lib/api.js";
  import {
    getMetricsPollIntervalMs,
    isRateLimitCooldownActive,
    isTabHidden,
  } from "../lib/hostPolling.js";
  import {
    groupMetricsByPrefix,
    computeMetricPlotData,
    downsample,
  } from "../lib/dataProcessing.js";
  import { buildColorMap } from "../lib/stores.js";

  let {
    project = null,
    selectedRuns = [],
    smoothing = 5,
    appBootstrapReady = false,
    realtimeEnabled = true,
    availableDevices = $bindable([]),
    selectedDevices = $bindable([]),
  } = $props();

  let systemData = $state([]);
  let metricNames = $state([]);
  let xLim = $state(null);
  let hasLoaded = $state(false);
  let metricOrder = $state({});
  let dragState = $state({ group: null, index: -1 });

  let rawDataCache = new Map();
  let refreshTimer = null;

  let runColorMap = $derived(buildColorMap(selectedRuns));

  let metricGroups = $derived(groupMetricsByPrefix(metricNames));
  let groupNames = $derived(Object.keys(metricGroups));

  let plotDataByMetric = $derived.by(() => {
    const map = new Map();
    const lim = xLim;
    for (const g of Object.values(metricGroups)) {
      for (const m of g.direct) {
        if (!map.has(m)) map.set(m, computeMetricPlotData(systemData, "time", m, lim));
      }
      for (const sub of Object.values(g.subgroups)) {
        for (const m of sub) {
          if (!map.has(m)) map.set(m, computeMetricPlotData(systemData, "time", m, lim));
        }
      }
    }
    return map;
  });

  let availableIndexedDevices = $derived.by(() => {
    const devices = [];
    for (const [groupName, group] of Object.entries(metricGroups)) {
      for (const subName of sortSubgroupNames(Object.keys(group.subgroups))) {
        devices.push(formatIndexedSourceLabel(groupName, subName));
      }
    }
    return [...new Set(devices)];
  });

  let comparisonMetricsByGroup = $derived.by(() => {
    const map = new Map();
    for (const [groupName, group] of Object.entries(metricGroups)) {
      map.set(groupName, buildIndexedMetricGroups(groupName, group.subgroups));
    }
    return map;
  });

  let comparisonPlotsByKey = $derived.by(() => {
    const map = new Map();
    const lim = xLim;
    for (const [groupName, comparisonMetrics] of comparisonMetricsByGroup.entries()) {
      for (const [metricName, metrics] of Object.entries(comparisonMetrics)) {
        const key = `sys:${groupName}:compare:${metricName}`;
        map.set(key, computeComparisonPlotData(systemData, "time", metrics, lim));
      }
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

  function sortSubgroupNames(items) {
    return [...items].sort((a, b) => {
      const aNum = Number(a);
      const bNum = Number(b);
      if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) return aNum - bNum;
      return a.localeCompare(b);
    });
  }

  function sameItems(a, b) {
    if (a.length !== b.length) return false;
    return a.every((item, i) => item === b[i]);
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
      const runKey = run.id ?? run.name;
      const logs = rawDataCache.get(runKey);
      if (!logs || logs.length === 0) continue;

      const firstTs = new Date(logs[0].timestamp).getTime();
      logs.forEach((row) => {
        const timeSeconds = (new Date(row.timestamp).getTime() - firstTs) / 1000;
        Object.keys(row).forEach((k) => {
          if (typeof row[k] === "number" && k !== "step" && k !== "time") {
            allMetrics.add(k);
          }
        });
        allRows.push({
          ...row,
          time: timeSeconds,
          run: run.name,
          run_id: runKey,
          series_key: runKey,
          data_type: "original",
        });
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

    const needFetch = selectedRuns.filter((run) => {
      const runKey = run.id ?? run.name;
      return !rawDataCache.has(runKey);
    });
    let fetched = false;
    if (needFetch.length > 0) {
      const batch = await getSystemLogsBatch(project, needFetch);
      for (const entry of batch) {
        const runKey = entry.run_id ?? entry.run;
        rawDataCache.set(runKey, entry.logs);
        fetched = true;
      }
    }

    if (fetched || !hasLoaded) {
      processFromCache();
    }
    hasLoaded = true;
  }

  async function refreshCachedRuns() {
    if (!realtimeEnabled) return;
    if (!project || selectedRuns.length === 0) return;
    if (isTabHidden()) return;
    if (isRateLimitCooldownActive()) return;

    const batch = await getSystemLogsBatch(project, selectedRuns);
    let changed = false;
    for (const entry of batch) {
      const runKey = entry.run_id ?? entry.run;
      const logs = entry.logs;
      const prev = rawDataCache.get(runKey);
      if (!prev || logs.length !== prev.length) {
        rawDataCache.set(runKey, logs);
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

  $effect(() => {
    const previousAvailable = availableDevices;
    const nextAvailable = availableIndexedDevices;
    const filtered = selectedDevices.filter((device) =>
      nextAvailable.includes(device),
    );

    if (!sameItems(availableDevices, nextAvailable)) {
      availableDevices = nextAvailable;
    }

    if (nextAvailable.length === 0) {
      if (selectedDevices.length > 0) selectedDevices = [];
      return;
    }

    if (previousAvailable.length === 0 && selectedDevices.length === 0) {
      if (!sameItems(selectedDevices, nextAvailable)) {
        selectedDevices = [...nextAvailable];
      }
      return;
    }

    if (selectedDevices.length > 0 && filtered.length !== selectedDevices.length) {
      const nextSelected = filtered.length > 0 ? filtered : [...nextAvailable];
      if (!sameItems(selectedDevices, nextSelected)) {
        selectedDevices = nextSelected;
      }
    }
  });

  onMount(() => {
    refreshTimer = setInterval(
      refreshCachedRuns,
      getMetricsPollIntervalMs(),
    );
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

  const metricUnits = {
    utilization: "%",
    mean_utilization: "%",
    allocated_memory: "GiB",
    total_allocated_memory: "GiB",
    power: "W",
    total_power: "W",
    temp: "°C",
    max_temp: "°C",
  };

  function metricTitleFromName(name) {
    const suffix = name.split("/").pop();
    const unit = metricUnits[suffix];
    return unit ? `${name} (${unit})` : name;
  }

  function metricTitle(metric, sliceFrom = 1) {
    const name = metric.split("/").slice(sliceFrom).join("/") || metric;
    return metricTitleFromName(name);
  }

  function formatIndexedSourceLabel(groupName, subName) {
    if (groupName === "gpu") return `GPU ${subName}`;
    return `${groupName.toUpperCase()} ${subName}`;
  }

  function deviceLabel(groupName, subName) {
    return formatIndexedSourceLabel(groupName, subName);
  }

  function buildIndexedMetricGroups(groupName, subgroups) {
    const grouped = {};
    const visibleSubgroups = sortSubgroupNames(Object.keys(subgroups)).filter(
      (subName) => {
        const label = deviceLabel(groupName, subName);
        return selectedDevices.length === 0 || selectedDevices.includes(label);
      },
    );

    for (const subName of visibleSubgroups) {
      for (const metric of subgroups[subName] ?? []) {
        const suffix = metric.split("/").slice(2).join("/");
        if (!suffix) continue;
        if (!grouped[suffix]) grouped[suffix] = [];
        grouped[suffix].push(metric);
      }
    }

    const ordered = {};
    Object.keys(grouped)
      .sort()
      .forEach((suffix) => {
        ordered[suffix] = grouped[suffix];
      });
    return ordered;
  }

  function computeComparisonPlotData(rows, xColumn, metrics, xLim) {
    if (!metrics || metrics.length === 0) {
      return { data: [], yExtent: undefined };
    }

    let relevant = [];

    for (const metric of metrics) {
      const [groupName, subName] = metric.split("/");
      for (const row of rows) {
        const value = row[metric];
        if (value == null) continue;
        relevant.push({
          [xColumn]: row[xColumn],
          value,
          seriesKey: `${row.series_key}\0${groupName}\0${subName}`,
          run: row.run,
          series_key: row.series_key,
          device: deviceLabel(groupName, subName),
          data_type: row.data_type,
        });
      }
    }

    if (xLim) {
      const groups = new Map();
      for (const row of relevant) {
        const key = `${row.seriesKey}\0${row.data_type || "original"}`;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(row);
      }

      const filtered = [];
      for (const rowsForSeries of groups.values()) {
        rowsForSeries.sort((a, b) => a[xColumn] - b[xColumn]);
        let lo = 0;
        let hi = rowsForSeries.length - 1;
        while (lo < rowsForSeries.length && rowsForSeries[lo][xColumn] < xLim[0]) lo++;
        while (hi >= 0 && rowsForSeries[hi][xColumn] > xLim[1]) hi--;
        lo = Math.max(0, lo - 1);
        hi = Math.min(rowsForSeries.length - 1, hi + 1);
        filtered.push(...rowsForSeries.slice(lo, hi + 1));
      }
      relevant = filtered;
    }

    const originals = relevant.filter(
      (row) => row.data_type === "original" || !row.data_type,
    );
    let yExtent = undefined;
    if (originals.length > 0) {
      let yMin = Infinity;
      let yMax = -Infinity;
      for (const row of originals) {
        if (row.value < yMin) yMin = row.value;
        if (row.value > yMax) yMax = row.value;
      }
      if (yMin !== Infinity) yExtent = [yMin, yMax];
    }

    return {
      data: downsample(
        relevant,
        xColumn,
        "value",
        "seriesKey",
        xLim,
        ["seriesKey", "run", "series_key", "device"],
      ).data,
      yExtent,
    };
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
      {@const compareKey = `sys:${groupName}:compare`}
      {@const orderedDirect = getOrderedMetrics(directKey, group.direct)}
      {@const comparisonMetrics = comparisonMetricsByGroup.get(groupName) ?? {}}
      {@const orderedComparisons = getOrderedMetrics(compareKey, Object.keys(comparisonMetrics))}
      <Accordion label={groupName} open={true}>
        {#if orderedDirect.length > 0}
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
                  title={metricTitle(metric, 1)}
                  colorMap={runColorMap}
                  colorField="series_key"
                  colorDisplayField="run"
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
        {/if}

        {#if orderedComparisons.length > 0}
          <div class="subgroup-list">
            <div class="plot-grid">
              {#each orderedComparisons as metricName, i}
                {@const plotKey = `sys:${groupName}:compare:${metricName}`}
                {@const plotResult = comparisonPlotsByKey.get(plotKey) ?? { data: [], yExtent: undefined }}
                {@const plotData = plotResult.data}
                {@const yExtent = plotResult.yExtent}
                {#if plotData.length > 0}
                  <LinePlot
                    data={plotData}
                    x="time"
                    y="value"
                    yLabel={metricTitleFromName(metricName)}
                    title={metricTitleFromName(metricName)}
                    colorField="series_key"
                    colorDisplayField="run"
                    colorLabel="Run"
                    colorMap={runColorMap}
                    dashField="device"
                    dashLabel="Device"
                    {xLim}
                    {yExtent}
                    onSelect={handlePlotSelect}
                    onResetZoom={handleResetZoom}
                    draggable={true}
                    ondragstart={(e) => handleDragStart(compareKey, i, e)}
                    ondragover={(e) => handleDragOver(compareKey, i, e)}
                    ondrop={(e) => handleDrop(compareKey, i, orderedComparisons, e)}
                  />
                {/if}
              {/each}
            </div>
          </div>
        {/if}
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
  .subgroup-list {
    margin-top: 16px;
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
