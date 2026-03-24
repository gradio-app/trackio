<script>
  import { onMount } from "svelte";
  import ColoredCheckbox from "./ColoredCheckbox.svelte";
  import ColoredRunRadioGroup from "./ColoredRunRadioGroup.svelte";
  import Dropdown from "./Dropdown.svelte";
  import GradioCheckbox from "./GradioCheckbox.svelte";
  import GradioSlider from "./GradioSlider.svelte";
  import GradioTextbox from "./GradioTextbox.svelte";
  import { buildColorMap, getColorForIndex } from "../lib/stores.js";

  let {
    open = $bindable(true),
    variant = "full",
    currentPage = "metrics",
    projects = [],
    selectedProject = $bindable(null),
    runs = [],
    selectedRuns = $bindable([]),
    mediaSelectedRun = $bindable(null),
    reportsSelectedRun = $bindable(null),
    smoothing = $bindable(10),
    xAxis = $bindable("step"),
    logScaleX = $bindable(false),
    logScaleY = $bindable(false),
    metricFilter = $bindable(""),
    realtimeEnabled = $bindable(true),
    showHeaders = $bindable(true),
    filterText = $bindable(""),
    spacesMode = false,
    runMutationAllowed = true,
    mutationAuth = "local",
  } = $props();

  let navTick = $state(0);

  onMount(() => {
    const bump = () => {
      navTick++;
    };
    window.addEventListener("popstate", bump);
    return () => window.removeEventListener("popstate", bump);
  });

  let loginHref = $derived.by(() => {
    navTick;
    return `${window.location.origin}/oauth/hf/start`;
  });

  let showCompactRunPicker = $derived(
    variant === "compact" &&
      (currentPage === "media" || currentPage === "reports"),
  );

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

  let runColorMap = $derived(buildColorMap(runs));

  let latestOnly = $state(false);

  function toggleLatestOnly() {
    latestOnly = !latestOnly;
    if (latestOnly && filteredRuns.length > 0) {
      selectedRuns = [filteredRuns[filteredRuns.length - 1]];
    } else if (!latestOnly) {
      selectedRuns = [...filteredRuns];
    }
  }
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
      <div class="sidebar-scroll">
      <div class="logo-section">
        <picture>
          <source
            media="(prefers-color-scheme: dark)"
            srcset="/static/trackio/trackio_logo_type_dark_transparent.png"
          />
          <img
            src="/static/trackio/trackio_logo_type_light_transparent.png"
            alt="Trackio"
            class="logo"
          />
        </picture>
      </div>

      <div class="section">
        <Dropdown
          label="Project"
          choices={projects}
          bind:value={selectedProject}
          filterable={true}
        />
      </div>

      {#if variant === "full"}
        <div class="section">
          <div class="runs-header">
            <span class="section-label">Runs ({filteredRuns.length})</span>
            <label class="latest-toggle">
              <span>Latest only</span>
              <input
                type="checkbox"
                checked={latestOnly}
                onchange={toggleLatestOnly}
              />
            </label>
          </div>
          <GradioTextbox
            bind:value={filterText}
            placeholder="Type to filter..."
            showLabel={false}
          />
          <div class="checkbox-list">
            <ColoredCheckbox
              choices={filteredRuns}
              bind:selected={selectedRuns}
              colors={filteredRuns.map(
              (r) => runColorMap[r] ?? getColorForIndex(Math.max(0, runs.indexOf(r))),
            )}
              ontoggle={() => { latestOnly = false; }}
            />
          </div>
        </div>

        <span class="section-label">Display Settings</span>

        <div class="section">
          <GradioCheckbox
            label="Refresh metrics realtime"
            bind:checked={realtimeEnabled}
          />
          <GradioCheckbox
            label="Show section headers"
            bind:checked={showHeaders}
          />
        </div>


        <div class="section">
          <GradioSlider
            label="Smoothing Factor (0 = no smoothing)"
            bind:value={smoothing}
            min={0}
            max={20}
            step={1}
          />
        </div>

        <div class="section">
          <Dropdown
            label="X-axis"
            choices={availableXAxes}
            bind:value={xAxis}
            filterable={false}
          />
          <GradioCheckbox
            label="Log scale X-axis"
            bind:checked={logScaleX}
          />
          <GradioCheckbox
            label="Log scale Y-axis"
            bind:checked={logScaleY}
          />
        </div>


        <div class="section">
          <GradioTextbox
            label="Metric Filter (regex)"
            info="Filter metrics using regex patterns. Leave empty to show all metrics."
            placeholder="e.g., loss|ndcg@10|gpu"
            bind:value={metricFilter}
          />
        </div>
      {:else if showCompactRunPicker}
        <div class="section">
          <span class="section-label">Run</span>
          {#if currentPage === "media"}
            <ColoredRunRadioGroup
              {runs}
              bind:value={mediaSelectedRun}
            />
          {:else if currentPage === "reports"}
            <ColoredRunRadioGroup
              {runs}
              bind:value={reportsSelectedRun}
              includeAllOption={true}
            />
          {/if}
        </div>
      {/if}
      </div>

      {#if spacesMode && !runMutationAllowed}
        <div class="oauth-footer">
          {#if mutationAuth === "oauth_insufficient"}
            <p class="oauth-line oauth-warn">
              Signed in, but this account does not have write access to this Space.
            </p>
          {:else}
            <a class="hf-login-btn" href={loginHref}>Sign in with Hugging Face</a>
            <p class="oauth-hint">
              Required to delete or rename runs (Space owner or collaborator with write access).
            </p>
          {/if}
        </div>
      {/if}
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
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .sidebar-scroll {
    overflow-y: auto;
    flex: 1;
    min-height: 0;
  }
  .oauth-footer {
    flex-shrink: 0;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
  }
  .oauth-line {
    margin: 0;
    font-size: 12px;
    line-height: 1.4;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .oauth-warn {
    color: var(--body-text-color, #92400e);
  }
  .hf-login-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 600;
    color: white;
    background: var(--color-accent, #f97316);
    border-radius: var(--radius-lg, 8px);
    text-decoration: none;
    border: none;
    cursor: pointer;
    box-sizing: border-box;
  }
  .hf-login-btn:hover {
    filter: brightness(1.05);
  }
  .oauth-hint {
    margin: 8px 0 0;
    font-size: 11px;
    line-height: 1.35;
    color: var(--body-text-color-subdued, #9ca3af);
  }
  .logo-section {
    margin-bottom: 20px;
  }
  .logo {
    width: 80%;
    max-width: 200px;
  }
  .section {
    margin-bottom: 18px;
  }
  .section-label {
    font-size: 13px;
    font-weight: 500;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .runs-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
  }
  .latest-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--body-text-color-subdued, #6b7280);
    cursor: pointer;
  }
  .latest-toggle input[type="checkbox"] {
    appearance: none;
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    margin: 0;
    border: 1px solid var(--checkbox-border-color, #d1d5db);
    border-radius: var(--checkbox-border-radius, 4px);
    background-color: var(--checkbox-background-color, white);
    box-shadow: var(--checkbox-shadow);
    cursor: pointer;
    flex-shrink: 0;
    transition: background-color 0.15s, border-color 0.15s;
  }
  .latest-toggle input[type="checkbox"]:checked {
    background-image: var(--checkbox-check);
    background-color: var(--checkbox-background-color-selected, #f97316);
    border-color: var(--checkbox-border-color-selected, #f97316);
  }
  .checkbox-list {
    max-height: 300px;
    overflow-y: auto;
    margin-top: 8px;
  }
</style>
