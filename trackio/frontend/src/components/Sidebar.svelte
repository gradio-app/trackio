<script>
  import ColoredCheckbox from "./ColoredCheckbox.svelte";
  import { DEFAULT_COLORS, getColorForIndex } from "../lib/stores.js";

  let {
    open = $bindable(true),
    projects = [],
    selectedProject = $bindable(null),
    runs = [],
    selectedRuns = $bindable([]),
    smoothing = $bindable(10),
    xAxis = $bindable("step"),
    logScaleX = $bindable(false),
    logScaleY = $bindable(false),
    metricFilter = $bindable(""),
    realtimeEnabled = $bindable(true),
    showHeaders = $bindable(true),
    filterText = $bindable(""),
  } = $props();

  let availableXAxes = $derived.by(() => {
    let axes = ["step", "time"];
    return axes;
  });

  function toggleSidebar() {
    open = !open;
  }

  let filteredRuns = $derived(
    filterText
      ? runs.filter((r) => r.toLowerCase().includes(filterText.toLowerCase()))
      : runs,
  );
</script>

<div class="sidebar" class:collapsed={!open}>
  <button class="toggle-btn" onclick={toggleSidebar}>
    {open ? "‹" : "›"}
  </button>

  {#if open}
    <div class="sidebar-content">
      <div class="logo-section">
        <picture>
          <source
            media="(prefers-color-scheme: dark)"
            srcset="/trackio/assets/trackio_logo_type_dark_transparent.png"
          />
          <img
            src="/trackio/assets/trackio_logo_type_light_transparent.png"
            alt="Trackio"
            class="logo"
          />
        </picture>
      </div>

      <div class="control-group">
        <span class="label">Project</span>
        <select
          class="select"
          bind:value={selectedProject}
        >
          {#each projects as project}
            <option value={project}>{project}</option>
          {/each}
        </select>
      </div>

      <div class="control-group">
        <div class="group-box">
          <span class="label">Runs ({filteredRuns.length})</span>
          <input
            type="text"
            class="input"
            placeholder="Type to filter..."
            bind:value={filterText}
          />
        </div>
        <div class="checkbox-list">
          <ColoredCheckbox
            choices={filteredRuns}
            bind:selected={selectedRuns}
            colors={filteredRuns.map((_, i) => getColorForIndex(i))}
          />
        </div>
      </div>

      <hr class="divider" />

      <div class="control-group">
        <label class="checkbox-label">
          <input type="checkbox" bind:checked={realtimeEnabled} />
          <span class="checkbox-text">Refresh metrics realtime</span>
        </label>
      </div>

      <div class="control-group">
        <span class="label">Smoothing Factor</span>
        <span class="info-text">0 = no smoothing</span>
        <div class="slider-row">
          <span class="slider-label">0</span>
          <input
            type="range"
            min="0"
            max="20"
            step="1"
            bind:value={smoothing}
            class="slider"
          />
          <span class="slider-label">20</span>
        </div>
      </div>

      <div class="control-group">
        <span class="label">X-axis</span>
        <select class="select" bind:value={xAxis}>
          {#each availableXAxes as axis}
            <option value={axis}>{axis}</option>
          {/each}
        </select>
      </div>

      <div class="control-group">
        <label class="checkbox-label">
          <input type="checkbox" bind:checked={logScaleX} />
          <span class="checkbox-text">Log scale X-axis</span>
        </label>
      </div>

      <div class="control-group">
        <label class="checkbox-label">
          <input type="checkbox" bind:checked={logScaleY} />
          <span class="checkbox-text">Log scale Y-axis</span>
        </label>
      </div>

      <div class="control-group">
        <label class="checkbox-label">
          <input type="checkbox" bind:checked={showHeaders} />
          <span class="checkbox-text">Show section headers</span>
        </label>
      </div>

      <div class="control-group">
        <span class="label">Metric Filter (regex)</span>
        <span class="info-text">Filter metrics using regex patterns. Leave empty to show all metrics.</span>
        <input
          type="text"
          class="input"
          placeholder="e.g., loss|ndcg@10|gpu"
          bind:value={metricFilter}
        />
      </div>
    </div>
  {/if}
</div>

<style>
  .sidebar {
    width: 290px;
    min-width: 290px;
    background: var(--bg-sidebar);
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: hidden;
    transition: width 0.2s, min-width 0.2s;
  }
  .sidebar.collapsed {
    width: 40px;
    min-width: 40px;
  }
  .toggle-btn {
    position: absolute;
    top: 12px;
    right: 8px;
    z-index: 10;
    border: none;
    background: none;
    color: var(--text-secondary);
    cursor: pointer;
    padding: 2px 8px;
    font-size: 20px;
    line-height: 1;
  }
  .toggle-btn:hover {
    color: var(--text-primary);
  }
  .sidebar-content {
    padding: 16px;
    overflow-y: auto;
    flex: 1;
    padding-top: 16px;
  }
  .logo-section {
    margin-bottom: 20px;
  }
  .logo {
    width: 80%;
    max-width: 200px;
  }
  .control-group {
    margin-bottom: 16px;
  }
  .group-box {
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 10px;
    margin-bottom: 4px;
  }
  .group-box .label {
    margin-bottom: 6px;
  }
  .group-box .input {
    margin-top: 4px;
  }
  .label {
    display: block;
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
    margin-bottom: 6px;
  }
  .info-text {
    display: block;
    font-size: 12px;
    color: var(--text-muted);
    margin-bottom: 6px;
  }
  .select {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid var(--input-border);
    border-radius: var(--radius-md);
    background: var(--input-bg);
    color: var(--text-primary);
    font-size: 14px;
    appearance: auto;
  }
  .select:focus {
    outline: none;
    border-color: var(--input-focus);
    box-shadow: 0 0 0 2px rgba(249, 115, 22, 0.1);
  }
  .input {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid var(--input-border);
    border-radius: var(--radius-md);
    background: var(--input-bg);
    color: var(--text-primary);
    font-size: 14px;
    box-sizing: border-box;
  }
  .input:focus {
    outline: none;
    border-color: var(--input-focus);
    box-shadow: 0 0 0 2px rgba(249, 115, 22, 0.1);
  }
  .checkbox-list {
    max-height: 300px;
    overflow-y: auto;
    margin-top: 4px;
  }
  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    color: var(--text-primary);
    cursor: pointer;
    padding: 2px 0;
  }
  .checkbox-label input[type="checkbox"] {
    width: 16px;
    height: 16px;
    accent-color: var(--accent-color);
    cursor: pointer;
  }
  .checkbox-text {
    font-weight: 500;
  }
  .slider-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .slider-label {
    font-size: 12px;
    color: var(--text-muted);
    min-width: 14px;
    text-align: center;
  }
  .slider {
    flex: 1;
    accent-color: var(--accent-color);
  }
  .divider {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 16px 0;
  }
</style>
