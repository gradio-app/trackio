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
    projectLocked = false,
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
        {#if projectLocked}
          <div class="section-label">Project</div>
          <div class="locked-project">{selectedProject ?? "—"}</div>
        {:else}
          <Dropdown
            label="Project"
            choices={projects}
            bind:value={selectedProject}
            filterable={true}
          />
        {/if}
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
            <a class="hf-login-btn" href={loginHref}>
              <svg class="hf-logo" xmlns="http://www.w3.org/2000/svg" width="95" height="88" fill="none" viewBox="0 0 95 88">
                <path fill="#FFD21E" d="M47.21 76.5a34.75 34.75 0 1 0 0-69.5 34.75 34.75 0 0 0 0 69.5Z"/>
                <path fill="#FF9D0B" d="M81.96 41.75a34.75 34.75 0 1 0-69.5 0 34.75 34.75 0 0 0 69.5 0Zm-73.5 0a38.75 38.75 0 1 1 77.5 0 38.75 38.75 0 0 1-77.5 0Z"/>
                <path fill="#3A3B45" d="M58.5 32.3c1.28.44 1.78 3.06 3.07 2.38a5 5 0 1 0-6.76-2.07c.61 1.15 2.55-.72 3.7-.32ZM34.95 32.3c-1.28.44-1.79 3.06-3.07 2.38a5 5 0 1 1 6.76-2.07c-.61 1.15-2.56-.72-3.7-.32Z"/>
                <path fill="#FF323D" d="M46.96 56.29c9.83 0 13-8.76 13-13.26 0-2.34-1.57-1.6-4.09-.36-2.33 1.15-5.46 2.74-8.9 2.74-7.19 0-13-6.88-13-2.38s3.16 13.26 13 13.26Z"/>
                <path fill="#3A3B45" fill-rule="evenodd" d="M39.43 54a8.7 8.7 0 0 1 5.3-4.49c.4-.12.81.57 1.24 1.28.4.68.82 1.37 1.24 1.37.45 0 .9-.68 1.33-1.35.45-.7.89-1.38 1.32-1.25a8.61 8.61 0 0 1 5 4.17c3.73-2.94 5.1-7.74 5.1-10.7 0-2.34-1.57-1.6-4.09-.36l-.14.07c-2.31 1.15-5.39 2.67-8.77 2.67s-6.45-1.52-8.77-2.67c-2.6-1.29-4.23-2.1-4.23.29 0 3.05 1.46 8.06 5.47 10.97Z" clip-rule="evenodd"/>
                <path fill="#FF9D0B" d="M70.71 37a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5ZM24.21 37a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5Z"/>
              </svg>
              Sign in with Hugging Face
            </a>
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
    gap: 8px;
    width: 100%;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 600;
    color: white;
    background: rgb(20, 28, 46);
    border-radius: var(--radius-lg, 8px);
    text-decoration: none;
    border: none;
    cursor: pointer;
    box-sizing: border-box;
  }
  .hf-login-btn:hover {
    background: rgb(40, 48, 66);
  }
  .hf-logo {
    width: 20px;
    height: 20px;
    flex-shrink: 0;
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
  .locked-project {
    margin-top: 4px;
    font-size: 13px;
    font-weight: 500;
    color: var(--body-text-color, #1f2937);
    padding: 8px 10px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-secondary, #f9fafb);
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
