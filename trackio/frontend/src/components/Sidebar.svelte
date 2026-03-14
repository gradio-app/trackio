<script>
  import ColoredCheckbox from "./ColoredCheckbox.svelte";
  import Dropdown from "./Dropdown.svelte";
  import GradioCheckbox from "./GradioCheckbox.svelte";
  import GradioSlider from "./GradioSlider.svelte";
  import GradioTextbox from "./GradioTextbox.svelte";
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
    {#if open}
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path d="M10 12L6 8L10 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    {:else}
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path d="M6 4L10 8L6 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    {/if}
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
        <Dropdown
          label="Project"
          choices={projects}
          bind:value={selectedProject}
          filterable={true}
        />
      </div>

      <div class="control-group">
        <div class="group-box">
          <span class="block-title">Runs ({filteredRuns.length})</span>
          <GradioTextbox
            bind:value={filterText}
            placeholder="Type to filter..."
            showLabel={false}
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
        <GradioCheckbox
          label="Refresh metrics realtime"
          bind:checked={realtimeEnabled}
        />
      </div>

      <div class="control-group">
        <GradioSlider
          label="Smoothing Factor"
          info="0 = no smoothing"
          bind:value={smoothing}
          min={0}
          max={20}
          step={1}
        />
      </div>

      <div class="control-group">
        <Dropdown
          label="X-axis"
          choices={availableXAxes}
          bind:value={xAxis}
          filterable={false}
        />
      </div>

      <div class="control-group">
        <GradioCheckbox
          label="Log scale X-axis"
          bind:checked={logScaleX}
        />
      </div>

      <div class="control-group">
        <GradioCheckbox
          label="Log scale Y-axis"
          bind:checked={logScaleY}
        />
      </div>

      <div class="control-group">
        <GradioCheckbox
          label="Show section headers"
          bind:checked={showHeaders}
        />
      </div>

      <div class="control-group">
        <GradioTextbox
          label="Metric Filter (regex)"
          info="Filter metrics using regex patterns. Leave empty to show all metrics."
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
    background: var(--background-fill-primary, white);
    border-right: 1px solid var(--border-color-primary, #e5e7eb);
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
    color: var(--body-text-color-subdued, #9ca3af);
    cursor: pointer;
    padding: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-sm, 4px);
    transition: color 0.15s, background-color 0.15s;
  }
  .toggle-btn:hover {
    color: var(--body-text-color, #1f2937);
    background-color: var(--background-fill-secondary, #f9fafb);
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
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    padding: 10px;
    margin-bottom: 4px;
  }
  .group-box .block-title {
    display: block;
    font-size: var(--block-title-text-size, 14px);
    font-weight: var(--block-title-text-weight, 400);
    color: var(--block-title-text-color, #6b7280);
    margin-bottom: 6px;
  }
  .checkbox-list {
    max-height: 300px;
    overflow-y: auto;
    margin-top: 4px;
  }
  .divider {
    border: none;
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
    margin: 16px 0;
  }
</style>
