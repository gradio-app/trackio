<script>
  import { onMount, tick } from "svelte";
  import embed from "vega-embed";
  import {
    buildParallelCoordsData,
    buildParallelCoordsSpec,
    METRIC_COLOR_STOPS,
  } from "../lib/parallelCoords.js";
  import { isDark, onThemeChange } from "../lib/theme.js";

  let {
    trials = [],
    metricName = "",
    metricGoal = "minimize",
    bestRunId = null,
  } = $props();

  let container = $state(null);
  let view = $state(null);
  let darkMode = $state(isDark());
  let renderSeq = 0;

  let plotData = $derived(
    buildParallelCoordsData(trials, metricName, bestRunId),
  );

  let metricAxis = $derived(
    plotData.axes.length > 0 ? plotData.axes[plotData.axes.length - 1] : null,
  );
  let legendGradient = $derived.by(() => {
    const stops =
      metricGoal === "minimize"
        ? [...METRIC_COLOR_STOPS].reverse()
        : METRIC_COLOR_STOPS;
    return `linear-gradient(to right, ${stops.join(", ")})`;
  });

  function cssVar(name, fallback) {
    return (
      getComputedStyle(document.documentElement)
        .getPropertyValue(name)
        .trim() || fallback
    );
  }

  async function render() {
    const seq = ++renderSeq;
    await tick();
    if (seq !== renderSeq) return;
    if (!container) return;
    if (plotData.rows.length === 0) return;

    const spec = buildParallelCoordsSpec(plotData, {
      metricName,
      metricGoal,
      gridColor: cssVar("--border-color-primary", "#e5e7eb"),
      labelColor: cssVar("--body-text-color-subdued", "#6b7280"),
      titleColor: cssVar("--body-text-color", "#374151"),
      metricColorRange: METRIC_COLOR_STOPS,
    });

    try {
      const result = await embed(container, spec, {
        actions: false,
        renderer: "canvas",
      });
      if (seq !== renderSeq) {
        result.view.finalize();
        return;
      }
      if (view) view.finalize();
      view = result.view;
      requestAnimationFrame(() => {
        result.view.resize();
      });
    } catch (e) {
      console.error("Vega render error:", e);
    }
  }

  $effect(() => {
    plotData;
    metricGoal;
    darkMode;
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
    const unsubscribe = onThemeChange((dark) => {
      darkMode = dark;
    });
    return () => {
      unsubscribe();
      if (view) view.finalize();
    };
  });
</script>

{#if plotData.rows.length > 0}
  <div class="plot-container parallel-coords-plot">
    <div class="plot" bind:this={container}></div>
    {#if metricAxis}
      <div class="gradient-legend">
        <span class="legend-title">{metricName || "metric"}</span>
        <span class="legend-tick">{metricAxis.ticks[0].label}</span>
        <span class="gradient-bar" style="background: {legendGradient}"></span>
        <span class="legend-tick"
          >{metricAxis.ticks[metricAxis.ticks.length - 1].label}</span
        >
      </div>
    {/if}
  </div>
{/if}

<style>
  .plot-container {
    background: var(--background-fill-primary, white);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    padding: 12px;
    overflow: hidden;
    position: relative;
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
  .gradient-legend {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 8px 0 2px;
  }
  .legend-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--body-text-color, #374151);
    margin-right: 4px;
  }
  .legend-tick {
    font-size: 11px;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .gradient-bar {
    width: 160px;
    height: 8px;
    border-radius: 4px;
  }
</style>
