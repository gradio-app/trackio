<script>
  import { onMount } from "svelte";
  import embed from "vega-embed";

  let {
    data = [],
    x = "step",
    y = "",
    colorField = "run",
    colorMap = {},
    title = "",
    xLim = null,
    onSelect = null,
    onDoubleClick = null,
  } = $props();

  let container;
  let view;

  let legendEntries = $derived.by(() => {
    if (!colorField || !data || data.length === 0) return [];
    const seen = new Set();
    const entries = [];
    for (const d of data) {
      const name = d[colorField];
      if (name && !seen.has(name)) {
        seen.add(name);
        entries.push({ name, color: colorMap[name] || "#999" });
      }
    }
    return entries;
  });

  function buildSpec() {
    const hasColor =
      colorField && data.length > 0 && data[0].hasOwnProperty(colorField);
    const allRuns = hasColor
      ? [...new Set(data.map((d) => d[colorField]))]
      : [];
    const uniqueRuns = [...new Set(allRuns)];
    const colorDomain = uniqueRuns;
    const colorRange = uniqueRuns.map(
      (r) => colorMap[r] || "#999",
    );

    const originalData = data.filter(
      (d) => d.data_type === "original" || !d.data_type,
    );
    const smoothedData = data.filter((d) => d.data_type === "smoothed");
    const hasSmoothed = smoothedData.length > 0;

    const layers = [];

    if (hasSmoothed) {
      layers.push({
        data: { values: originalData },
        mark: { type: "line", strokeWidth: 1, opacity: 0.3 },
        encoding: {
          x: {
            field: x,
            type: "quantitative",
            ...(xLim
              ? { scale: { domain: [xLim[0], xLim[1]] } }
              : {}),
          },
          y: { field: y, type: "quantitative" },
          ...(hasColor
            ? {
                color: {
                  field: colorField,
                  type: "nominal",
                  scale: { domain: colorDomain, range: colorRange },
                  legend: null,
                },
              }
            : {}),
        },
      });
      layers.push({
        data: { values: smoothedData },
        mark: { type: "line", strokeWidth: 2 },
        encoding: {
          x: {
            field: x,
            type: "quantitative",
            ...(xLim
              ? { scale: { domain: [xLim[0], xLim[1]] } }
              : {}),
          },
          y: { field: y, type: "quantitative" },
          ...(hasColor
            ? {
                color: {
                  field: colorField,
                  type: "nominal",
                  scale: { domain: colorDomain, range: colorRange },
                  legend: null,
                },
              }
            : {}),
        },
      });
    } else {
      layers.push({
        data: { values: data },
        mark: { type: "line", strokeWidth: 2 },
        encoding: {
          x: {
            field: x,
            type: "quantitative",
            ...(xLim
              ? { scale: { domain: [xLim[0], xLim[1]] } }
              : {}),
          },
          y: { field: y, type: "quantitative" },
          ...(hasColor
            ? {
                color: {
                  field: colorField,
                  type: "nominal",
                  scale: { domain: colorDomain, range: colorRange },
                  legend: null,
                },
              }
            : {}),
        },
      });
    }

    if (onSelect) {
      layers.push({
        mark: "rule",
        params: [
          {
            name: "brush",
            select: { type: "interval", encodings: ["x"] },
          },
        ],
        encoding: {
          opacity: { value: 0 },
        },
      });
    }

    const yTitle = y.includes("/") ? y.split("/").pop() : y;

    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      title: { text: title, fontSize: 13, color: "var(--text-primary, #333)" },
      width: "container",
      height: 250,
      layer: layers,
      config: {
        background: "transparent",
        axis: {
          labelColor: "var(--text-secondary, #666)",
          titleColor: "var(--text-primary, #333)",
          gridColor: "var(--border-light, #eee)",
        },
        view: {
          stroke: "transparent",
        },
      },
      encoding: {
        y: { title: yTitle },
      },
    };
  }

  async function render() {
    if (!container || !data || data.length === 0 || !y) return;

    const spec = buildSpec();

    try {
      if (view) {
        view.finalize();
      }
      const result = await embed(container, spec, {
        actions: { export: true, source: false, compiled: false, editor: false },
        renderer: "svg",
      });
      view = result.view;

      if (onSelect) {
        result.view.addSignalListener("brush", (_, value) => {
          if (value && value[x]) {
            onSelect(value[x]);
          }
        });
      }
    } catch (e) {
      console.error("Vega render error:", e);
    }
  }

  function downloadData() {
    if (!data || data.length === 0) return;
    const jsonStr = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const safeName = (y || "data").replace(/\//g, "_");
    a.download = `${safeName}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  $effect(() => {
    data;
    y;
    x;
    colorMap;
    xLim;
    title;
    render();
  });

  onMount(() => {
    if (onDoubleClick) {
      container?.addEventListener("dblclick", () => {
        onDoubleClick();
      });
    }
    return () => {
      if (view) view.finalize();
    };
  });
</script>

<div class="plot-container">
  <div class="plot-toolbar">
    <button class="toolbar-btn" onclick={downloadData} title="Download data">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
        <polyline points="7 10 12 15 17 10"/>
        <line x1="12" y1="15" x2="12" y2="3"/>
      </svg>
    </button>
  </div>
  <div class="plot" bind:this={container}></div>
  {#if legendEntries.length > 0}
    <div class="custom-legend">
      <span class="legend-title">{colorField}</span>
      {#each legendEntries as entry}
        <span class="legend-item">
          <span class="legend-dot" style="background: {entry.color}"></span>
          <span class="legend-label">{entry.name}</span>
        </span>
      {/each}
    </div>
  {/if}
</div>

<style>
  .plot-container {
    min-width: 350px;
    flex: 1;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 12px;
    overflow: hidden;
    position: relative;
  }
  .plot-toolbar {
    position: absolute;
    top: 8px;
    right: 8px;
    display: flex;
    gap: 4px;
    z-index: 5;
    opacity: 0;
    transition: opacity 0.15s;
  }
  .plot-container:hover .plot-toolbar {
    opacity: 1;
  }
  .toolbar-btn {
    border: 1px solid var(--border-color);
    background: var(--bg-primary);
    color: var(--text-secondary);
    cursor: pointer;
    padding: 4px 6px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .toolbar-btn:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }
  .plot {
    width: 100%;
  }
  .plot :global(.vega-embed) {
    width: 100% !important;
  }
  .plot :global(.vega-embed summary) {
    opacity: 0.3;
  }
  .plot :global(.vega-embed:hover summary) {
    opacity: 1;
  }
  .custom-legend {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 6px 0 0;
    flex-wrap: wrap;
  }
  .legend-title {
    font-size: 11px;
    color: var(--text-secondary);
    font-weight: 600;
  }
  .legend-item {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .legend-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .legend-label {
    font-size: 11px;
    color: var(--text-secondary);
  }
</style>
