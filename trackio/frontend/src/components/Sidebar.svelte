<script>
  import { onMount } from "svelte";
  import ColoredCheckbox from "./ColoredCheckbox.svelte";
  import Dropdown from "./Dropdown.svelte";
  import GradioCheckbox from "./GradioCheckbox.svelte";
  import GradioSlider from "./GradioSlider.svelte";
  import GradioTextbox from "./GradioTextbox.svelte";
  import { buildColorMap, getColorForIndex } from "../lib/stores.js";
  import { latestOnlySelection } from "../lib/selection.js";

  let {
    open = $bindable(true),
    variant = "full",
    currentPage = "metrics",
    projects = [],
    selectedProject = $bindable(null),
    runs = [],
    selectedRuns = $bindable([]),
    availableSystemDevices = [],
    selectedSystemDevices = $bindable([]),
    traceModel = $bindable("All models"),
    traceModelChoices = [],
    smoothing = $bindable(10),
    xAxis = $bindable("step"),
    logScaleX = $bindable(false),
    logScaleY = $bindable(false),
    metricFilter = $bindable(""),
    realtimeEnabled = $bindable(true),
    showHeaders = $bindable(true),
    filterText = $bindable(""),
    metricColumns = [],
    spacesMode = false,
    runMutationAllowed = true,
    mutationAuth = "local",
    readOnlySource = null,
    projectLocked = false,
    spaceId = null,
    logoUrls = { light: "/static/trackio/trackio_logo_type_light_transparent.png", dark: "/static/trackio/trackio_logo_type_dark_transparent.png" },
    darkMode = false,
  } = $props();

  let navTick = $state(0);
  let copyFeedbackTimer = null;

  onMount(() => {
    const bump = () => {
      navTick++;
    };
    window.addEventListener("popstate", bump);
    return () => {
      window.removeEventListener("popstate", bump);
      if (copyFeedbackTimer) {
        clearTimeout(copyFeedbackTimer);
        copyFeedbackTimer = null;
      }
    };
  });

  let loginHref = $derived.by(() => {
    navTick;
    return `${window.location.origin}/oauth/hf/start`;
  });


  let availableXAxes = $derived.by(() => {
    let axes = ["step", "time", ...metricColumns];
    return axes;
  });

  function toggleSidebar() {
    open = !open;
  }

  function setIndeterminate(node, value) {
    node.indeterminate = value;
    return {
      update(newValue) {
        node.indeterminate = newValue;
      },
    };
  }

  let filteredRuns = $derived(
    filterText
      ? runs.filter((r) => r.name.toLowerCase().includes(filterText.toLowerCase()))
      : runs,
  );

  let runColorMap = $derived(buildColorMap(runs));
  let filteredRunIds = $derived(filteredRuns.map((r) => r.id ?? r.name));

  let latestOnly = $state(false);
  let shareTab = $state("share");
  let copyFeedback = $state(null);

  function toggleLatestOnly() {
    latestOnly = !latestOnly;
    if (latestOnly && filteredRuns.length > 0) {
      selectedRuns = latestOnlySelection(filteredRunIds);
    } else if (!latestOnly) {
      selectedRuns = [...filteredRunIds];
    }
  }

  $effect(() => {
    if (!latestOnly || filteredRunIds.length === 0) return;
    const desired = latestOnlySelection(filteredRunIds);
    if (
      selectedRuns.length !== desired.length ||
      selectedRuns[0] !== desired[0]
    ) {
      selectedRuns = desired;
    }
  });

  function toggleDevice(device) {
    if (selectedSystemDevices.includes(device)) {
      selectedSystemDevices = selectedSystemDevices.filter((d) => d !== device);
    } else {
      selectedSystemDevices = [...selectedSystemDevices, device];
    }
  }

  function buildSpaceHost(spaceIdValue) {
    if (!spaceIdValue || !spaceIdValue.includes("/")) return "";
    const [namespace, name] = spaceIdValue.split("/", 2);
    if (!namespace || !name) return "";
    return `${namespace}-${name}.hf.space`;
  }

  function shareBaseHref() {
    const hfHost = buildSpaceHost(spaceId);
    if (hfHost) {
      return `https://${hfHost}`;
    }
    const base = window.__trackio_base || "/";
    const u = new URL(base, window.location.origin);
    let href = u.href;
    if (href.endsWith("/")) {
      href = href.slice(0, -1);
    }
    return href || u.origin;
  }

  function selectedRunIdsForShare(selectedIds, allRuns) {
    const valid = new Set(allRuns.map((run) => run.id ?? run.name));
    return selectedIds.filter((id) => valid.has(id));
  }

  let shareUrl = $derived.by(() => {
    navTick;
    if (currentPage !== "metrics" || !spacesMode) return "";
    if (!selectedProject) return "";
    const params = new URLSearchParams();
    params.set("project", selectedProject);
    if (metricFilter?.trim()) {
      params.set("metric_filter", metricFilter.trim());
    }
    const runIds = selectedRunIdsForShare(selectedRuns, runs);
    if (runIds.length) {
      params.set("run_ids", runIds.join(","));
    }
    if (!showHeaders) {
      params.set("accordion", "hidden");
    }
    params.set("sidebar", "hidden");
    params.set("navbar", "hidden");
    const base = shareBaseHref();
    const q = params.toString();
    return q ? `${base}/?${q}` : `${base}/`;
  });

  let embedCode = $derived.by(() => {
    if (!shareUrl) return "";
    return `<iframe src="${shareUrl}" style="width:1600px; height:500px; border:0;"></iframe>`;
  });

  async function copyText(value, feedbackKey) {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = value;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
    copyFeedback = feedbackKey;
    if (copyFeedbackTimer) {
      clearTimeout(copyFeedbackTimer);
    }
    copyFeedbackTimer = setTimeout(() => {
      copyFeedback = null;
      copyFeedbackTimer = null;
    }, 2000);
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
        <img
          src={darkMode ? logoUrls.dark : logoUrls.light}
          alt="Trackio"
          class="logo"
        />
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
        {#if currentPage === "metrics" && spacesMode}
          <div class="section">
            <div class="share-tabs">
              <button
                class="share-tab-btn"
                class:active={shareTab === "share"}
                onclick={() => { shareTab = "share"; }}
              >
                Share
              </button>
              <button
                class="share-tab-btn"
                class:active={shareTab === "embed"}
                onclick={() => { shareTab = "embed"; }}
              >
                Embed
              </button>
            </div>
            {#if shareTab === "share"}
              <div class="share-field">
                <span class="section-label">Share this view</span>
                {#if shareUrl}
                  <div class="share-input-row">
                    <input type="text" value={shareUrl} readonly />
                    <button
                      type="button"
                      class="copy-btn"
                      aria-label={copyFeedback === "share" ? "Copied" : "Copy share link"}
                      onclick={() => copyText(shareUrl, "share")}
                    >
                      {#if copyFeedback === "share"}
                        <svg
                          class="copy-btn-check"
                          width="14"
                          height="14"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2.5"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          aria-hidden="true"
                        >
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      {:else}
                        Copy
                      {/if}
                    </button>
                  </div>
                {:else}
                  <p class="share-hint">Select a project to generate a share link.</p>
                {/if}
              </div>
            {:else}
              <div class="share-field">
                <span class="section-label">Embed this view</span>
                {#if embedCode}
                  <div class="share-input-row">
                    <textarea readonly rows="2" value={embedCode}></textarea>
                    <button
                      type="button"
                      class="copy-btn"
                      aria-label={copyFeedback === "embed" ? "Copied" : "Copy embed code"}
                      onclick={() => copyText(embedCode, "embed")}
                    >
                      {#if copyFeedback === "embed"}
                        <svg
                          class="copy-btn-check"
                          width="14"
                          height="14"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2.5"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          aria-hidden="true"
                        >
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      {:else}
                        Copy
                      {/if}
                    </button>
                  </div>
                {:else}
                  <p class="share-hint">Select a project to generate embed HTML.</p>
                {/if}
              </div>
            {/if}
          </div>
        {/if}

        <div class="section">
          <div class="runs-header">
            <label class="select-all-label">
              <input
                type="checkbox"
                class="select-all-cb"
                checked={selectedRuns.length === filteredRunIds.length && filteredRunIds.length > 0}
                use:setIndeterminate={selectedRuns.length > 0 && selectedRuns.length < filteredRunIds.length}
                onchange={() => {
                  if (selectedRuns.length === filteredRunIds.length) {
                    selectedRuns = [];
                  } else {
                    selectedRuns = [...filteredRunIds];
                  }
                  latestOnly = false;
                }}
              />
              <span class="section-label">Runs ({filteredRunIds.length})</span>
            </label>
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
              getKey={(run) => run.id ?? run.name}
              getLabel={(run) => run.name}
              colors={filteredRuns.map(
              (r) => runColorMap[r.id ?? r.name] ?? getColorForIndex(Math.max(0, runs.indexOf(r))),
            )}
              ontoggle={() => { latestOnly = false; }}
            />
          </div>
          {#if currentPage === "system" && availableSystemDevices.length > 0}
            <div class="device-group">
              <label class="select-all-label">
                <input
                  type="checkbox"
                  class="select-all-cb"
                  checked={selectedSystemDevices.length === availableSystemDevices.length && availableSystemDevices.length > 0}
                  use:setIndeterminate={selectedSystemDevices.length > 0 && selectedSystemDevices.length < availableSystemDevices.length}
                  onchange={() => {
                    if (selectedSystemDevices.length === availableSystemDevices.length) {
                      selectedSystemDevices = [];
                    } else {
                      selectedSystemDevices = [...availableSystemDevices];
                    }
                  }}
                />
                <span class="section-sublabel">Devices ({availableSystemDevices.length})</span>
              </label>
              <div class="checkbox-group">
                {#each availableSystemDevices as device}
                  <label class="checkbox-item">
                    <input
                      type="checkbox"
                      checked={selectedSystemDevices.includes(device)}
                      onchange={() => toggleDevice(device)}
                    />
                    <span class="run-name" title={device}>{device}</span>
                  </label>
                {/each}
              </div>
            </div>
          {/if}
        </div>

        {#if currentPage === "traces"}
          <span class="section-label">Trace Filters</span>

          <div class="section">
            <Dropdown
              label="Model Version"
              choices={traceModelChoices}
              bind:value={traceModel}
              filterable={false}
            />
          </div>
        {/if}

        {#if currentPage === "metrics" || currentPage === "system"}
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
              label="Metric Filter"
              info="Filter metrics using regex patterns. Leave empty to show all metrics."
              placeholder="e.g., loss|ndcg@10|gpu"
              bind:value={metricFilter}
            />
          </div>
        {/if}
      {/if}
      </div>

      {#if readOnlySource}
        <div class="readonly-footer">
          <span class="readonly-badge">READ ONLY</span>
          <a class="readonly-link" href={readOnlySource.url} target="_blank" rel="noopener noreferrer">
            {readOnlySource.url}
          </a>
        </div>
      {:else if spacesMode && !runMutationAllowed}
        <div class="oauth-footer">
          {#if mutationAuth === "oauth_insufficient"}
            <p class="oauth-line oauth-warn">
              Signed in, but this account does not have write access to this Space.
            </p>
          {:else}
            <a class="hf-login-btn" href={loginHref}>
              <svg class="hf-logo" xmlns="http://www.w3.org/2000/svg" width="95" height="88" fill="none" viewBox="0 0 95 88"><path fill="#FFD21E" d="M47.21 76.5a34.75 34.75 0 1 0 0-69.5 34.75 34.75 0 0 0 0 69.5Z"/><path fill="#FF9D0B" d="M81.96 41.75a34.75 34.75 0 1 0-69.5 0 34.75 34.75 0 0 0 69.5 0Zm-73.5 0a38.75 38.75 0 1 1 77.5 0 38.75 38.75 0 0 1-77.5 0Z"/><path fill="#3A3B45" d="M58.5 32.3c1.28.44 1.78 3.06 3.07 2.38a5 5 0 1 0-6.76-2.07c.61 1.15 2.55-.72 3.7-.32ZM34.95 32.3c-1.28.44-1.79 3.06-3.07 2.38a5 5 0 1 1 6.76-2.07c-.61 1.15-2.56-.72-3.7-.32Z"/><path fill="#FF323D" d="M46.96 56.29c9.83 0 13-8.76 13-13.26 0-2.34-1.57-1.6-4.09-.36-2.33 1.15-5.46 2.74-8.9 2.74-7.19 0-13-6.88-13-2.38s3.16 13.26 13 13.26Z"/><path fill="#3A3B45" fill-rule="evenodd" d="M39.43 54a8.7 8.7 0 0 1 5.3-4.49c.4-.12.81.57 1.24 1.28.4.68.82 1.37 1.24 1.37.45 0 .9-.68 1.33-1.35.45-.7.89-1.38 1.32-1.25a8.61 8.61 0 0 1 5 4.17c3.73-2.94 5.1-7.74 5.1-10.7 0-2.34-1.57-1.6-4.09-.36l-.14.07c-2.31 1.15-5.39 2.67-8.77 2.67s-6.45-1.52-8.77-2.67c-2.6-1.29-4.23-2.1-4.23.29 0 3.05 1.46 8.06 5.47 10.97Z" clip-rule="evenodd"/><path fill="#FF9D0B" d="M70.71 37a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5ZM24.21 37a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5ZM17.52 48c-1.62 0-3.06.66-4.07 1.87a5.97 5.97 0 0 0-1.33 3.76 7.1 7.1 0 0 0-1.94-.3c-1.55 0-2.95.59-3.94 1.66a5.8 5.8 0 0 0-.8 7 5.3 5.3 0 0 0-1.79 2.82c-.24.9-.48 2.8.8 4.74a5.22 5.22 0 0 0-.37 5.02c1.02 2.32 3.57 4.14 8.52 6.1 3.07 1.22 5.89 2 5.91 2.01a44.33 44.33 0 0 0 10.93 1.6c5.86 0 10.05-1.8 12.46-5.34 3.88-5.69 3.33-10.9-1.7-15.92-2.77-2.78-4.62-6.87-5-7.77-.78-2.66-2.84-5.62-6.25-5.62a5.7 5.7 0 0 0-4.6 2.46c-1-1.26-1.98-2.25-2.86-2.82A7.4 7.4 0 0 0 17.52 48Zm0 4c.51 0 1.14.22 1.82.65 2.14 1.36 6.25 8.43 7.76 11.18.5.92 1.37 1.31 2.14 1.31 1.55 0 2.75-1.53.15-3.48-3.92-2.93-2.55-7.72-.68-8.01.08-.02.17-.02.24-.02 1.7 0 2.45 2.93 2.45 2.93s2.2 5.52 5.98 9.3 3.97 6.8 1.22 10.83c-1.88 2.75-5.47 3.58-9.16 3.58-3.81 0-7.73-.9-9.92-1.46-.11-.03-13.45-3.8-11.76-7 .28-.54.75-.76 1.34-.76 2.38 0 6.7 3.54 8.57 3.54.41 0 .7-.17.83-.6.79-2.85-12.06-4.05-10.98-8.17.2-.73.71-1.02 1.44-1.02 3.14 0 10.2 5.53 11.68 5.53.11 0 .2-.03.24-.1.74-1.2.33-2.04-4.9-5.2-5.21-3.16-8.88-5.06-6.8-7.33.24-.26.58-.38 1-.38 3.17 0 10.66 6.82 10.66 6.82s2.02 2.1 3.25 2.1c.28 0 .52-.1.68-.38.86-1.46-8.06-8.22-8.56-11.01-.34-1.9.24-2.85 1.31-2.85Z"/><path fill="#FFD21E" d="M38.6 76.69c2.75-4.04 2.55-7.07-1.22-10.84-3.78-3.77-5.98-9.3-5.98-9.3s-.82-3.2-2.69-2.9c-1.87.3-3.24 5.08.68 8.01 3.91 2.93-.78 4.92-2.29 2.17-1.5-2.75-5.62-9.82-7.76-11.18-2.13-1.35-3.63-.6-3.13 2.2.5 2.79 9.43 9.55 8.56 11-.87 1.47-3.93-1.71-3.93-1.71s-9.57-8.71-11.66-6.44c-2.08 2.27 1.59 4.17 6.8 7.33 5.23 3.16 5.64 4 4.9 5.2-.75 1.2-12.28-8.53-13.36-4.4-1.08 4.11 11.77 5.3 10.98 8.15-.8 2.85-9.06-5.38-10.74-2.18-1.7 3.21 11.65 6.98 11.76 7.01 4.3 1.12 15.25 3.49 19.08-2.12Z"/><path fill="#FF9D0B" d="M77.4 48c1.62 0 3.07.66 4.07 1.87a5.97 5.97 0 0 1 1.33 3.76 7.1 7.1 0 0 1 1.95-.3c1.55 0 2.95.59 3.94 1.66a5.8 5.8 0 0 1 .8 7 5.3 5.3 0 0 1 1.78 2.82c.24.9.48 2.8-.8 4.74a5.22 5.22 0 0 1 .37 5.02c-1.02 2.32-3.57 4.14-8.51 6.1-3.08 1.22-5.9 2-5.92 2.01a44.33 44.33 0 0 1-10.93 1.6c-5.86 0-10.05-1.8-12.46-5.34-3.88-5.69-3.33-10.9 1.7-15.92 2.78-2.78 4.63-6.87 5.01-7.77.78-2.66 2.83-5.62 6.24-5.62a5.7 5.7 0 0 1 4.6 2.46c1-1.26 1.98-2.25 2.87-2.82A7.4 7.4 0 0 1 77.4 48Zm0 4c-.51 0-1.13.22-1.82.65-2.13 1.36-6.25 8.43-7.76 11.18a2.43 2.43 0 0 1-2.14 1.31c-1.54 0-2.75-1.53-.14-3.48 3.91-2.93 2.54-7.72.67-8.01a1.54 1.54 0 0 0-.24-.02c-1.7 0-2.45 2.93-2.45 2.93s-2.2 5.52-5.97 9.3c-3.78 3.77-3.98 6.8-1.22 10.83 1.87 2.75 5.47 3.58 9.15 3.58 3.82 0 7.73-.9 9.93-1.46.1-.03 13.45-3.8 11.76-7-.29-.54-.75-.76-1.34-.76-2.38 0-6.71 3.54-8.57 3.54-.42 0-.71-.17-.83-.6-.8-2.85 12.05-4.05 10.97-8.17-.19-.73-.7-1.02-1.44-1.02-3.14 0-10.2 5.53-11.68 5.53-.1 0-.19-.03-.23-.1-.74-1.2-.34-2.04 4.88-5.2 5.23-3.16 8.9-5.06 6.8-7.33-.23-.26-.57-.38-.98-.38-3.18 0-10.67 6.82-10.67 6.82s-2.02 2.1-3.24 2.1a.74.74 0 0 1-.68-.38c-.87-1.46 8.05-8.22 8.55-11.01.34-1.9-.24-2.85-1.31-2.85Z"/><path fill="#FFD21E" d="M56.33 76.69c-2.75-4.04-2.56-7.07 1.22-10.84 3.77-3.77 5.97-9.3 5.97-9.3s.82-3.2 2.7-2.9c1.86.3 3.23 5.08-.68 8.01-3.92 2.93.78 4.92 2.28 2.17 1.51-2.75 5.63-9.82 7.76-11.18 2.13-1.35 3.64-.6 3.13 2.2-.5 2.79-9.42 9.55-8.55 11 .86 1.47 3.92-1.71 3.92-1.71s9.58-8.71 11.66-6.44c2.08 2.27-1.58 4.17-6.8 7.33-5.23 3.16-5.63 4-4.9 5.2.75 1.2 12.28-8.53 13.36-4.4 1.08 4.11-11.76 5.3-10.97 8.15.8 2.85 9.05-5.38 10.74-2.18 1.69 3.21-11.65 6.98-11.76 7.01-4.31 1.12-15.26 3.49-19.08-2.12Z"/></svg>
              Sign in with Hugging Face
            </a>
            <p class="oauth-hint">
              Required to delete or rename runs (Space owner or collaborator with write access).
            </p>
          {/if}
        </div>
      {:else if spacesMode && runMutationAllowed && mutationAuth === "oauth"}
        <div class="oauth-footer">
          <p class="oauth-signed-in">Signed in with Hugging Face</p>
          <a class="oauth-logout" href="/oauth/logout" onclick={() => { sessionStorage.removeItem("trackio_oauth_session"); }}>Logout</a>
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
  .readonly-footer {
    flex-shrink: 0;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .readonly-badge {
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: 999px;
    padding: 2px 8px;
    font-size: 10px;
    letter-spacing: 0.06em;
    font-weight: 600;
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-secondary, #f9fafb);
  }
  .readonly-link {
    font-size: 12px;
    color: var(--body-text-color-subdued, #6b7280);
    text-decoration: none;
    max-width: 100%;
    overflow-wrap: anywhere;
  }
  .readonly-link:hover {
    color: var(--body-text-color, #1f2937);
    text-decoration: underline;
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
  .oauth-signed-in {
    margin: 0;
    font-size: 12px;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .oauth-logout {
    font-size: 12px;
    color: var(--body-text-color-subdued, #9ca3af);
    text-decoration: none;
    cursor: pointer;
  }
  .oauth-logout:hover {
    text-decoration: underline;
    color: var(--body-text-color, #1f2937);
  }
  .logo-section {
    margin-bottom: 20px;
  }
  .logo {
    width: 80%;
    max-width: 200px;
  }
  .section {
    margin-top: 2px;
    margin-bottom: 18px;
  }
  .share-tabs {
    display: flex;
    gap: 6px;
    margin-bottom: 8px;
  }
  .share-tab-btn {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    padding: 4px 8px;
    font-size: 12px;
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-primary, white);
    cursor: pointer;
  }
  .share-tab-btn.active {
    color: var(--body-text-color, #1f2937);
    background: var(--background-fill-secondary, #f9fafb);
  }
  .share-field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .share-input-row {
    display: flex;
    gap: 6px;
    align-items: stretch;
  }
  .share-input-row input,
  .share-input-row textarea {
    width: 100%;
    min-width: 0;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    padding: 6px 8px;
    font-size: 12px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    color: var(--body-text-color, #1f2937);
    background: var(--background-fill-secondary, #f9fafb);
    resize: vertical;
  }
  .copy-btn {
    box-sizing: border-box;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    padding: 6px 10px;
    min-width: 3.25rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    line-height: 1;
    color: var(--body-text-color, #1f2937);
    background: var(--background-fill-primary, white);
    cursor: pointer;
    flex-shrink: 0;
  }
  .copy-btn-check {
    display: block;
    color: var(--color-accent, #f97316);
  }
  .share-hint {
    margin: 0;
    font-size: 12px;
    line-height: 1.4;
    color: var(--body-text-color-subdued, #9ca3af);
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
  .select-all-label {
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
  }
  .select-all-cb {
    appearance: none;
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    border: 1px solid var(--checkbox-border-color, #d1d5db);
    border-radius: var(--checkbox-border-radius, 4px);
    background-color: var(--checkbox-background-color, white);
    cursor: pointer;
    flex-shrink: 0;
    position: relative;
    transition: background-color 0.15s, border-color 0.15s;
  }
  .select-all-cb:checked {
    background-color: var(--checkbox-background-color-selected, var(--color-accent, #f97316));
    border-color: var(--checkbox-background-color-selected, var(--color-accent, #f97316));
    background-image: var(--checkbox-check);
  }
  .select-all-cb:indeterminate {
    background-color: var(--checkbox-background-color-selected, var(--color-accent, #f97316));
    border-color: var(--checkbox-background-color-selected, var(--color-accent, #f97316));
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 16 16' fill='white' xmlns='http://www.w3.org/2000/svg'%3E%3Crect x='3' y='7' width='10' height='2' rx='1'/%3E%3C/svg%3E");
    background-size: 12px;
    background-position: center;
    background-repeat: no-repeat;
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
  .device-group {
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
  }
  .section-sublabel {
    font-size: 12px;
    font-weight: 600;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .checkbox-group {
    display: flex;
    flex-direction: column;
    margin-top: 8px;
  }
  .checkbox-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 0;
    cursor: pointer;
    font-size: 13px;
  }
  .checkbox-item input[type="checkbox"] {
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
  .checkbox-item input[type="checkbox"]:checked {
    background-image: var(--checkbox-check);
    background-color: var(--checkbox-background-color-selected, #f97316);
    border-color: var(--checkbox-border-color-selected, #f97316);
  }
  .checkbox-item input[type="checkbox"]:hover {
    border-color: var(--checkbox-border-color-hover, #d1d5db);
  }
  .run-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--body-text-color, #1f2937);
  }
</style>
