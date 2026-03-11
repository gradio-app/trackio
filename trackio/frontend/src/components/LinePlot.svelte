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

  function buildSpec() {
    const hasColor =
      colorField && data.length > 0 && data[0].hasOwnProperty(colorField);
    const runs = hasColor
      ? [...new Set(data.map((d) => d[colorField]))]
      : [];
    const colorDomain = runs;
    const colorRange = runs.map(
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
        legend: {
          labelColor: "var(--text-secondary, #666)",
          titleColor: "var(--text-primary, #333)",
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
  <div class="plot" bind:this={container}></div>
</div>

<style>
  .plot-container {
    min-width: 350px;
    flex: 1;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 8px;
    overflow: hidden;
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
</style>
