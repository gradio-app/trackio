<script>
  import { onMount, tick } from "svelte";
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
    onResetZoom = null,
    draggable = false,
    ondragstart = null,
    ondragover = null,
    ondrop = null,
  } = $props();

  let container = $state(null);
  let plotContainer = $state(null);
  let fullscreenHost = $state(null);
  let view = $state(null);
  let fullscreen = $state(false);

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

  let colorSpecKey = $derived.by(() => {
    if (!colorField || !data || data.length === 0) return "";
    const seen = new Set();
    const parts = [];
    for (const d of data) {
      const name = d[colorField];
      if (name && !seen.has(name)) {
        seen.add(name);
        parts.push(`${name}:${colorMap[name] ?? "#999"}`);
      }
    }
    parts.sort();
    return parts.join("|");
  });

  function cssVar(name, fallback) {
    return (
      getComputedStyle(document.documentElement)
        .getPropertyValue(name)
        .trim() || fallback
    );
  }

  function buildSpec() {
    const hasColor =
      colorField && data.length > 0 && Object.hasOwn(data[0], colorField);
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

    const xEnc = {
      field: x,
      type: "quantitative",
      scale: { zero: false, ...(xLim ? { domain: [xLim[0], xLim[1]] } : {}) },
    };
    const yEnc = { field: y, type: "quantitative" };
    const colorEnc = hasColor
      ? {
          color: {
            field: colorField,
            type: "nominal",
            scale: { domain: colorDomain, range: colorRange },
            legend: null,
          },
        }
      : {};

    const layers = [];

    const lineMark = (extra = {}) => ({
      type: "line",
      clip: false,
      strokeWidth: 2,
      ...extra,
    });

    if (hasSmoothed) {
      layers.push({
        data: { values: originalData },
        mark: lineMark({ strokeWidth: 1, opacity: 0.3 }),
        encoding: { x: xEnc, y: yEnc, ...colorEnc },
        name: "original",
      });
      layers.push({
        data: { values: smoothedData },
        mark: lineMark(),
        encoding: { x: xEnc, y: yEnc, ...colorEnc },
        name: "plot",
      });
    } else {
      layers.push({
        data: { values: data },
        mark: lineMark(),
        encoding: { x: xEnc, y: yEnc, ...colorEnc },
        name: "plot",
      });
    }

    const yTitle = y.includes("/") ? y.split("/").pop() : y;

    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      title: {
        text: title,
        fontSize: 13,
        color: cssVar("--body-text-color", "#374151"),
      },
      width: "container",
      height: fullscreen ? "container" : 250,
      autosize: { type: "fit", contains: "padding" },
      layer: layers,
      ...(onSelect
        ? {
            params: [
              {
                name: "brush",
                select: {
                  type: "interval",
                  encodings: ["x"],
                  mark: { fill: "gray", fillOpacity: 0.3, stroke: "none" },
                },
                views: ["plot"],
              },
            ],
          }
        : {}),
      config: {
        background: "transparent",
        axis: {
          labelColor: cssVar("--body-text-color-subdued", "#6b7280"),
          titleColor: cssVar("--body-text-color", "#374151"),
          gridColor: cssVar("--border-color-primary", "#f3f4f6"),
        },
        view: {
          stroke: "transparent",
        },
        mark: {
          cursor: onSelect ? "crosshair" : undefined,
        },
      },
      encoding: {
        y: { title: yTitle },
      },
    };
  }

  async function render() {
    await tick();
    if (!container || !data || data.length === 0 || !y) return;

    const spec = buildSpec();

    try {
      if (view) {
        view.finalize();
        view = null;
      }
      const result = await embed(container, spec, {
        actions: false,
        renderer: "canvas",
      });
      view = result.view;
      requestAnimationFrame(() => {
        result.view.resize();
      });

      if (onSelect) {
        let lastSelectTime = 0;
        let debounceTimer = null;
        result.view.addSignalListener("brush", (_, value) => {
          if (Date.now() - lastSelectTime < 1000) return;
          if (!value || Object.keys(value).length === 0) return;
          clearTimeout(debounceTimer);
          const range = value[Object.keys(value)[0]];
          if (!range || range.length !== 2) return;
          debounceTimer = setTimeout(() => {
            lastSelectTime = Date.now();
            onSelect(range);
          }, 250);
        });
      }
    } catch (e) {
      console.error("Vega render error:", e);
    }
  }

  function downloadCSV() {
    if (!data || data.length === 0) return;
    const originals = data.filter((d) => d.data_type === "original" || !d.data_type);
    if (originals.length === 0) return;

    const cols = Object.keys(originals[0]).filter((k) => k !== "data_type");
    const header = cols.map((c) => /[,"]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c).join(",");
    const rows = originals.map((row) =>
      cols.map((c) => {
        const v = row[c];
        if (v == null) return "";
        if (typeof v === "string" && (v.includes(",") || v.includes('"')))
          return `"${v.replace(/"/g, '""')}"`;
        return v;
      }).join(","),
    );
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(y || "data").replace(/\//g, "_")}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function downloadImage() {
    if (!view) return;
    try {
      const url = await view.toImageURL("png", 4);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${(y || "chart").replace(/\//g, "_")}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (e) {
      console.error("Failed to export image:", e);
    }
  }

  function requestFullscreenEl(el) {
    if (!el) return Promise.reject(new Error("no element"));
    const req =
      el.requestFullscreen ||
      el.webkitRequestFullscreen ||
      el.mozRequestFullScreen ||
      el.msRequestFullscreen;
    if (!req) return Promise.reject(new Error("no fullscreen"));
    return req.call(el);
  }

  function exitFullscreenDoc() {
    const exit =
      document.exitFullscreen ||
      document.webkitExitFullscreen ||
      document.mozCancelFullScreen ||
      document.msExitFullscreen;
    if (exit) return exit.call(document);
    return Promise.resolve();
  }

  async function enterFullscreen() {
    fullscreen = true;
    document.body.style.overflow = "hidden";
    await tick();
    await tick();
    try {
      await requestFullscreenEl(fullscreenHost);
      await tick();
      view?.resize();
    } catch {
      document.body.style.overflow = "";
      fullscreen = false;
    }
  }

  async function leaveFullscreen() {
    try {
      await exitFullscreenDoc();
    } catch {
    }
    document.body.style.overflow = "";
    fullscreen = false;
  }

  async function toggleFullscreen() {
    if (fullscreen) {
      await leaveFullscreen();
    } else {
      await enterFullscreen();
    }
  }

  function onFullscreenChange() {
    const active =
      document.fullscreenElement ||
      document.webkitFullscreenElement ||
      document.mozFullScreenElement ||
      document.msFullscreenElement;
    if (!active && fullscreen) {
      document.body.style.overflow = "";
      fullscreen = false;
    }
    if (active && fullscreen) {
      tick().then(() => view?.resize());
    }
  }

  function handleKeydown(e) {
    if (e.key === "Escape" && fullscreen) {
      leaveFullscreen();
    }
  }

  $effect(() => {
    data;
    y;
    x;
    colorSpecKey;
    xLim;
    title;
    fullscreen;
    container;
    render();
  });

  $effect(() => {
    if (!container) return;
    const ro = new ResizeObserver(() => {
      queueMicrotask(() => {
        view?.resize();
      });
    });
    ro.observe(container);
    return () => ro.disconnect();
  });

  onMount(() => {
    document.addEventListener("fullscreenchange", onFullscreenChange);
    document.addEventListener("webkitfullscreenchange", onFullscreenChange);
    document.addEventListener("mozfullscreenchange", onFullscreenChange);
    document.addEventListener("MSFullscreenChange", onFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      document.removeEventListener("webkitfullscreenchange", onFullscreenChange);
      document.removeEventListener("mozfullscreenchange", onFullscreenChange);
      document.removeEventListener("MSFullscreenChange", onFullscreenChange);
      if (view) view.finalize();
      document.body.style.overflow = "";
    };
  });

  function handleDragStart(e) {
    if (ondragstart) ondragstart(e);
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="plot-container"
  class:hidden-plot={fullscreen}
  bind:this={plotContainer}
  draggable={draggable ? "true" : undefined}
  ondragstart={draggable ? handleDragStart : undefined}
  ondragover={draggable ? ondragover : undefined}
  ondrop={draggable ? ondrop : undefined}
>
  <div class="plot-toolbar">
    <button
      type="button"
      class="toolbar-btn"
      onclick={downloadCSV}
      title="Download this plot’s data as a CSV file"
      aria-label="Download this plot’s data as a CSV file"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
      </svg>
    </button>
    <button
      type="button"
      class="toolbar-btn"
      onclick={downloadImage}
      title="Download this chart as a PNG image"
      aria-label="Download this chart as a PNG image"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
        <circle cx="8.5" cy="8.5" r="1.5"/>
        <polyline points="21 15 16 10 5 21"/>
      </svg>
    </button>
    <button
      type="button"
      class="toolbar-btn"
      onclick={toggleFullscreen}
      title="Open this chart in the browser’s fullscreen mode"
      aria-label="Open this chart in the browser’s fullscreen mode"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="15 3 21 3 21 9"/>
        <polyline points="9 21 3 21 3 15"/>
        <line x1="21" y1="3" x2="14" y2="10"/>
        <line x1="3" y1="21" x2="10" y2="14"/>
      </svg>
    </button>
  </div>
  {#if draggable}
    <div
      class="drag-handle"
      title="Drag to reorder this plot in the list"
      aria-label="Drag to reorder this plot in the list"
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
        <circle cx="9" cy="5" r="2"/><circle cx="15" cy="5" r="2"/>
        <circle cx="9" cy="12" r="2"/><circle cx="15" cy="12" r="2"/>
        <circle cx="9" cy="19" r="2"/><circle cx="15" cy="19" r="2"/>
      </svg>
    </div>
  {/if}
  {#if !fullscreen}
    <div class="plot-chart-wrap">
      <div class="plot" bind:this={container}></div>
      {#if xLim && onResetZoom}
        <button
          type="button"
          class="reset-zoom-btn"
          onclick={(e) => {
            e.stopPropagation();
            onResetZoom();
          }}
          title="Reset horizontal zoom: show the full range on the x-axis"
          aria-label="Reset horizontal zoom: show the full range on the x-axis"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 12h16M4 12l3-3M4 12l3 3M20 12l-3-3M20 12l-3 3"/>
          </svg>
        </button>
      {/if}
    </div>
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
  {/if}
</div>

{#if fullscreen}
  <div class="fullscreen-host" bind:this={fullscreenHost}>
    <div class="fullscreen-toolbar">
      <button
        type="button"
        class="toolbar-btn"
        onclick={downloadCSV}
        title="Download this plot’s data as a CSV file"
        aria-label="Download this plot’s data as a CSV file"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/>
        </svg>
      </button>
      <button
        type="button"
        class="toolbar-btn"
        onclick={downloadImage}
        title="Download this chart as a PNG image"
        aria-label="Download this chart as a PNG image"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
          <circle cx="8.5" cy="8.5" r="1.5"/>
          <polyline points="21 15 16 10 5 21"/>
        </svg>
      </button>
      <button
        type="button"
        class="toolbar-btn"
        onclick={() => leaveFullscreen()}
        title="Exit fullscreen and return to the metrics view"
        aria-label="Exit fullscreen and return to the metrics view"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="4 14 10 14 10 20"/>
          <polyline points="20 10 14 10 14 4"/>
          <line x1="14" y1="10" x2="21" y2="3"/>
          <line x1="3" y1="21" x2="10" y2="14"/>
        </svg>
      </button>
    </div>
    <div class="fullscreen-chart-wrap">
      <div class="plot-chart-wrap plot-chart-wrap--fs">
        <div class="plot fullscreen-plot" bind:this={container}></div>
        {#if xLim && onResetZoom}
          <button
            type="button"
            class="reset-zoom-btn"
            onclick={(e) => {
              e.stopPropagation();
              onResetZoom();
            }}
            title="Reset horizontal zoom: show the full range on the x-axis"
            aria-label="Reset horizontal zoom: show the full range on the x-axis"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 12h16M4 12l3-3M4 12l3 3M20 12l-3-3M20 12l-3 3"/>
            </svg>
          </button>
        {/if}
      </div>
    </div>
    {#if legendEntries.length > 0}
      <div class="custom-legend fullscreen-legend">
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
{/if}

<style>
  .plot-container {
    min-width: 350px;
    flex: 1;
    background: var(--background-fill-primary, white);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    padding: 12px;
    overflow: hidden;
    position: relative;
  }
  .plot-container[draggable="true"] {
    cursor: grab;
  }
  .plot-container[draggable="true"]:active {
    cursor: grabbing;
  }
  .hidden-plot {
    visibility: hidden;
    height: 0;
    padding: 0;
    margin: 0;
    border: none;
    overflow: hidden;
    pointer-events: none;
  }
  .drag-handle {
    position: absolute;
    top: 8px;
    left: 8px;
    color: var(--body-text-color-subdued, #9ca3af);
    opacity: 0;
    transition: opacity 0.15s;
    z-index: 5;
  }
  .plot-container:hover .drag-handle {
    opacity: 0.5;
  }
  .drag-handle:hover {
    opacity: 1 !important;
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
    border: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color-subdued, #6b7280);
    cursor: pointer;
    padding: 4px 6px;
    border-radius: var(--radius-sm, 4px);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .toolbar-btn:hover {
    background: var(--neutral-100, #f3f4f6);
    color: var(--body-text-color, #1f2937);
  }
  .plot-chart-wrap {
    position: relative;
    width: 100%;
  }
  .plot-chart-wrap--fs {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .reset-zoom-btn {
    position: absolute;
    bottom: 1px;
    right: 1px;
    z-index: 6;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin: 0;
    min-width: 52px;
    padding: 5px 12px 5px 10px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--body-text-color-subdued, #334155);
    cursor: pointer;
    opacity: 0.92;
    transform: translateY(6px);
    transition: opacity 0.15s ease, color 0.15s ease, background 0.15s ease;
    box-shadow: none;
  }
  .reset-zoom-btn:hover {
    opacity: 1;
    color: var(--body-text-color, #0f172a);
    background: var(--background-fill-secondary, rgba(226, 232, 240, 0.85));
    transform: translateY(6px);
  }
  .reset-zoom-btn svg {
    display: block;
    flex-shrink: 0;
    filter: drop-shadow(0 0 0.5px rgba(255, 255, 255, 0.95));
  }
  .plot {
    width: 100%;
  }
  .plot :global(.vega-embed) {
    width: 100% !important;
  }
  .plot :global(.vega-embed summary) {
    display: none;
  }
  .fullscreen-host {
    position: fixed;
    inset: 0;
    z-index: 10000;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    background: var(--background-fill-primary, white);
    padding: 12px;
    gap: 8px;
    pointer-events: auto;
  }
  .fullscreen-host:fullscreen {
    width: 100%;
    height: 100%;
  }
  .fullscreen-host:-webkit-full-screen {
    width: 100%;
    height: 100%;
  }
  .fullscreen-toolbar {
    flex-shrink: 0;
    display: flex;
    justify-content: flex-end;
    gap: 4px;
    z-index: 5;
  }
  .fullscreen-chart-wrap {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .fullscreen-legend {
    flex-shrink: 0;
  }
  .fullscreen-plot {
    flex: 1;
    min-height: 0;
    width: 100%;
    overflow: hidden;
  }
  .fullscreen-plot :global(.vega-embed) {
    width: 100% !important;
    height: 100% !important;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .fullscreen-plot :global(.vega-embed .vega-view) {
    flex: 1;
    min-height: 0;
  }
  .fullscreen-plot :global(.vega-embed summary) {
    display: none;
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
    color: var(--body-text-color-subdued, #6b7280);
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
    color: var(--body-text-color-subdued, #6b7280);
  }
</style>
