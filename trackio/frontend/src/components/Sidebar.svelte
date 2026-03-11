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
    {open ? "◀" : "▶"}
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
        <label class="label">Project</label>
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
        <label class="label">Runs ({filteredRuns.length})</label>
        <input
          type="text"
          class="input"
          placeholder="Type to filter..."
          bind:value={filterText}
        />
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
          Refresh metrics realtime
        </label>
      </div>

      <div class="control-group">
        <label class="label">Smoothing Factor: {smoothing}</label>
        <input
          type="range"
          min="0"
          max="20"
          step="1"
          bind:value={smoothing}
          class="slider"
        />
        <span class="hint">{smoothing === 0 ? "no smoothing" : ""}</span>
      </div>

      <div class="control-group">
        <label class="label">X-axis</label>
        <select class="select" bind:value={xAxis}>
          {#each availableXAxes as axis}
            <option value={axis}>{axis}</option>
          {/each}
        </select>
      </div>

      <div class="control-group">
        <label class="checkbox-label">
          <input type="checkbox" bind:checked={logScaleX} />
          Log scale X-axis
        </label>
      </div>

      <div class="control-group">
        <label class="checkbox-label">
          <input type="checkbox" bind:checked={logScaleY} />
          Log scale Y-axis
        </label>
      </div>

      <div class="control-group">
        <label class="checkbox-label">
          <input type="checkbox" bind:checked={showHeaders} />
          Show section headers
        </label>
      </div>

      <div class="control-group">
        <label class="label">Metric Filter (regex)</label>
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
    width: 280px;
    min-width: 280px;
    background: var(--bg-sidebar);
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: hidden;
    transition: width 0.2s, min-width 0.2s;
  }
  .sidebar.collapsed {
    width: 32px;
    min-width: 32px;
  }
  .toggle-btn {
    position: absolute;
    top: 8px;
    right: 4px;
    z-index: 10;
    border: none;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    cursor: pointer;
    padding: 4px 6px;
    border-radius: var(--radius-sm);
    font-size: 10px;
  }
  .toggle-btn:hover {
    background: var(--border-color);
  }
  .sidebar-content {
    padding: 12px;
    overflow-y: auto;
    flex: 1;
    padding-top: 32px;
  }
  .logo-section {
    margin-bottom: 16px;
  }
  .logo {
    width: 80%;
    max-width: 200px;
  }
  .control-group {
    margin-bottom: 12px;
  }
  .label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    margin-bottom: 4px;
  }
  .select {
    width: 100%;
    padding: 6px 8px;
    border: 1px solid var(--input-border);
    border-radius: var(--radius-sm);
    background: var(--input-bg);
    color: var(--text-primary);
    font-size: 13px;
  }
  .select:focus {
    outline: none;
    border-color: var(--input-focus);
  }
  .input {
    width: 100%;
    padding: 6px 8px;
    border: 1px solid var(--input-border);
    border-radius: var(--radius-sm);
    background: var(--input-bg);
    color: var(--text-primary);
    font-size: 13px;
    box-sizing: border-box;
  }
  .input:focus {
    outline: none;
    border-color: var(--input-focus);
  }
  .checkbox-list {
    max-height: 300px;
    overflow-y: auto;
    margin-top: 4px;
  }
  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--text-primary);
    cursor: pointer;
  }
  .slider {
    width: 100%;
    accent-color: var(--accent-color);
  }
  .hint {
    font-size: 11px;
    color: var(--text-muted);
  }
  .divider {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 12px 0;
  }
</style>
