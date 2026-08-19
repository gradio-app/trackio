<script>
  import { onMount, tick } from "svelte";
  import embed from "vega-embed";
  import {
    buildOptimizationHistoryData,
    buildOptimizationHistorySpec,
  } from "../lib/optimizationHistory.js";
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
    buildOptimizationHistoryData(trials, metricGoal, bestRunId),
  );

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
    if (plotData.points.length === 0) return;

    const spec = buildOptimizationHistorySpec(plotData, {
      metricName,
      gridColor: cssVar("--border-color-primary", "#e5e7eb"),
      labelColor: cssVar("--body-text-color-subdued", "#6b7280"),
      titleColor: cssVar("--body-text-color", "#374151"),
      pointColor: darkMode ? "#60a5fa" : "#2563eb",
      bestColor: darkMode ? "#fbbf24" : "#d97706",
      lineColor: darkMode ? "#6b7280" : "#9ca3af",
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

{#if plotData.points.length > 0}
  <div class="plot-container optimization-history-plot">
    <div class="plot-title">Optimization history</div>
    <div class="plot" bind:this={container}></div>
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
    display: flex;
    flex-direction: column;
    height: 100%;
    box-sizing: border-box;
  }
  .plot-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--body-text-color, #374151);
    margin-bottom: 4px;
  }
  .plot {
    width: 100%;
    flex: 1 1 auto;
    min-height: 200px;
  }
  .plot :global(.vega-embed) {
    width: 100% !important;
    height: 100% !important;
  }
  .plot :global(.vega-embed summary) {
    display: none;
  }
</style>
