<script>
  import { getMediaUrl } from "../lib/api.js";

  let { item, onclose = () => {} } = $props();
  let canvas = $state(null);
  let viewer = $state(null);
  let status = $state({ state: "loading" });
  let retry = $state(0);
  let gridVisible = $state(true);
  let axesVisible = $state(true);
  let modal = $state(null);

  $effect(() => {
    const target = canvas;
    const model = item;
    retry;
    if (!target || !model) return;
    let active = true;
    let instance = null;
    const abortController = new AbortController();
    status = { state: "loading" };
    import("../lib/object3dViewer.js")
      .then(({ createObject3DViewer }) =>
        createObject3DViewer(
          target,
          model,
          getMediaUrl(model.file_path),
          (next) => {
            if (active) status = next;
          },
          abortController.signal,
        ),
      )
      .then((created) => {
        if (!active) return created.dispose();
        instance = created;
        viewer = created;
        created.setGridVisible(gridVisible);
        created.setAxesVisible(axesVisible);
      })
      .catch((error) => {
        if (active) {
          status = {
            state: "error",
            message: error instanceof Error ? error.message : String(error),
          };
        }
      });
    return () => {
      active = false;
      abortController.abort();
      instance?.dispose();
      if (viewer === instance) viewer = null;
    };
  });

  function handleKeydown(event) {
    if (event.key === "Escape") onclose();
  }

  function toggleGrid() {
    gridVisible = !gridVisible;
    viewer?.setGridVisible(gridVisible);
  }

  function toggleAxes() {
    axesVisible = !axesVisible;
    viewer?.setAxesVisible(axesVisible);
  }

  async function toggleFullscreen() {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await modal?.requestFullscreen();
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="viewer-backdrop" role="presentation" onclick={onclose}>
  <div
    class="viewer-modal"
    bind:this={modal}
    role="dialog"
    aria-modal="true"
    aria-label={`3D viewer for ${item.caption || item.key || "object"}`}
    tabindex="-1"
    onclick={(event) => event.stopPropagation()}
    onkeydown={(event) => event.stopPropagation()}
  >
    <header>
      <div>
        <h2>{item.caption || item.key || "3D object"}</h2>
        <p>{item.format?.toUpperCase()} · {item.kind?.replaceAll("_", " ")}</p>
      </div>
      <div class="controls">
        <button type="button" onclick={() => viewer?.resetCamera()} disabled={!viewer}>Reset camera</button>
        <button type="button" class:active={gridVisible} onclick={toggleGrid}>Grid</button>
        <button type="button" class:active={axesVisible} onclick={toggleAxes}>Axes</button>
        <button type="button" onclick={toggleFullscreen}>Fullscreen</button>
        <button class="close" type="button" onclick={onclose} aria-label="Close 3D viewer">×</button>
      </div>
    </header>
    <div class="viewport">
      <canvas bind:this={canvas} aria-label="Interactive 3D scene"></canvas>
      {#if status.state === "loading"}
        <div class="status">Loading {item.format?.toUpperCase()}…</div>
      {:else if status.state === "error"}
        <div class="status error" role="alert">
          <strong>3D viewer failed</strong>
          <span>{status.message}</span>
          <button type="button" onclick={() => (retry += 1)}>Retry</button>
        </div>
      {/if}
      <div class="hint">Orbit: drag · Pan: right-drag · Zoom: wheel</div>
    </div>
    <footer>
      <span>{item._run ? `Run: ${item._run} · Step: ${item.step}` : item.key || ""}</span>
      {#if Number.isFinite(status.renderedPointCount)}
        <span>{status.renderedPointCount.toLocaleString()} of {status.originalPointCount.toLocaleString()} points rendered</span>
      {:else if Number.isFinite(item.rendered_point_count)}
        <span>{item.rendered_point_count.toLocaleString()} of {item.original_point_count.toLocaleString()} points</span>
      {/if}
    </footer>
  </div>
</div>

<style>
  .viewer-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1100;
    display: grid;
    padding: 28px;
    place-items: center;
    background: rgb(0 0 0 / 76%);
  }
  .viewer-modal {
    display: grid;
    width: min(1200px, 94vw);
    height: min(820px, 92vh);
    grid-template-rows: auto minmax(0, 1fr) auto;
    overflow: hidden;
    border: 1px solid var(--border-color-primary, #303642);
    border-radius: var(--radius-lg, 8px);
    background: var(--background-fill-primary, #fff);
    box-shadow: 0 24px 80px rgb(0 0 0 / 45%);
  }
  .viewer-modal:fullscreen { width: 100vw; height: 100vh; border: 0; border-radius: 0; }
  header,
  footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 10px 12px;
    color: var(--body-text-color, #1f2937);
  }
  header { border-bottom: 1px solid var(--border-color-primary, #e5e7eb); }
  footer {
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 11px;
  }
  h2 { margin: 0; font-size: 14px; }
  p { margin: 2px 0 0; color: var(--body-text-color-subdued, #6b7280); font-size: 11px; text-transform: capitalize; }
  .controls { display: flex; align-items: center; gap: 5px; }
  button {
    border: 1px solid var(--border-color-primary, #d1d5db);
    border-radius: var(--radius-sm, 4px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
    cursor: pointer;
    font: inherit;
    font-size: 11px;
    padding: 5px 8px;
  }
  button.active { border-color: var(--primary-500, #f97316); color: var(--primary-600, #ea580c); }
  button:disabled { cursor: default; opacity: 0.5; }
  button.close { border: 0; font-size: 23px; line-height: 18px; }
  .viewport { position: relative; min-height: 0; overflow: hidden; background: #0b0d11; }
  canvas { display: block; width: 100%; height: 100%; outline: none; touch-action: none; }
  .status {
    position: absolute;
    inset: 0;
    display: grid;
    place-content: center;
    gap: 10px;
    padding: 30px;
    background: rgb(11 13 17 / 78%);
    color: #d9e1ea;
    text-align: center;
  }
  .status.error span { max-width: 640px; color: #ffb4ab; font-size: 12px; }
  .status button { justify-self: center; }
  .hint {
    position: absolute;
    right: 10px;
    bottom: 8px;
    padding: 4px 7px;
    border-radius: 4px;
    background: rgb(0 0 0 / 52%);
    color: #bcc5d0;
    font-size: 10px;
    pointer-events: none;
  }
  @media (max-width: 760px) {
    .viewer-backdrop { padding: 0; }
    .viewer-modal { width: 100vw; height: 100vh; border-radius: 0; }
    header { align-items: flex-start; }
    .controls { flex-wrap: wrap; justify-content: flex-end; }
    footer { flex-wrap: wrap; }
  }
</style>
