<script>
  import { onMount } from "svelte";
  import Navbar from "./components/Navbar.svelte";
  import Sidebar from "./components/Sidebar.svelte";
  import AlertPanel from "./components/AlertPanel.svelte";
  import Metrics from "./pages/Metrics.svelte";
  import SystemMetrics from "./pages/SystemMetrics.svelte";
  import Media from "./pages/Media.svelte";
  import Reports from "./pages/Reports.svelte";
  import Runs from "./pages/Runs.svelte";
  import RunDetail from "./pages/RunDetail.svelte";
  import Files from "./pages/Files.svelte";
  import {
    getAllProjects,
    getRunsForProject,
    getAlerts,
    getRunMutationStatus,
    getSettings,
    getReadOnlySource,
    isStaticMode,
    setMediaDir,
  } from "./lib/api.js";
  import { setColorPalette } from "./lib/stores.js";
  import { getPageFromPath, navigateTo, getQueryParam } from "./lib/router.js";
  import Settings from "./pages/Settings.svelte";
  import { initTheme } from "./lib/theme.js";

  initTheme();

  let currentPage = $state("metrics");
  let projects = $state([]);
  let selectedProject = $state(null);
  let runs = $state([]);
  let selectedRuns = $state([]);
  let smoothing = $state(10);
  let xAxis = $state("step");
  let logScaleX = $state(false);
  let logScaleY = $state(false);
  let metricFilter = $state("");
  let realtimeEnabled = $state(true);
  let showHeaders = $state(true);
  let filterText = $state("");
  let metricColumns = $state([]);
  let sidebarOpen = $state(true);
  let sidebarHidden = $state(false);
  let urlTick = $state(0);
  let alerts = $state([]);
  let pollTimer = $state(null);
  let mutationStatus = $state({
    spaces: false,
    allowed: true,
    auth: "local",
  });
  let mutationPollTimer = $state(null);
  let appBootstrapReady = $state(false);
  let logoUrls = $state({ light: "/static/trackio/trackio_logo_type_light_transparent.png", dark: "/static/trackio/trackio_logo_type_dark_transparent.png" });
  let plotOrder = $state([]);
  let tableTruncateLength = $state(250);
  let readOnlySource = $state(null);
  let spaceId = $state(null);

  function handleNavigate(page) {
    currentPage = page;
    navigateTo(page);
  }

  function lockedProjectName() {
    return getQueryParam("project") || getQueryParam("selected_project");
  }

  function applyLockedProject() {
    const locked = lockedProjectName();
    if (locked && projects.includes(locked)) {
      selectedProject = locked;
    }
  }

  async function refreshProjects() {
    try {
      const data = await getAllProjects();
      projects = data || [];
      if (projects.length > 0 && !selectedProject) {
        const paramProject = lockedProjectName();
        selectedProject = paramProject && projects.includes(paramProject)
          ? paramProject
          : projects[0];
      }
      applyLockedProject();
    } catch (e) {
      console.error("Failed to load projects:", e);
    }
  }

  async function refreshRunsAndMutation() {
    await refreshRuns();
    await refreshMutationAccess();
  }

  async function refreshRuns() {
    if (!selectedProject) {
      runs = [];
      selectedRuns = [];
      return;
    }
    try {
      const data = await getRunsForProject(selectedProject);
      const newRuns = data || [];
      const newRunNames = new Set(newRuns);

      if (JSON.stringify(runs) !== JSON.stringify(newRuns)) {
        const prevSelected = new Set(selectedRuns);
        runs = newRuns;

        const kept = selectedRuns.filter((r) => newRunNames.has(r));

        if (kept.length === 0 && selectedRuns.length === 0) {
          selectedRuns = [...newRuns];
        } else {
          selectedRuns = [...kept, ...newRuns.filter((r) => !new Set([...kept, ...Array.from(prevSelected)]).has(r))];
        }
      }
    } catch (e) {
      console.error("Failed to load runs:", e);
    }
  }

  async function refreshAlerts() {
    if (!selectedProject) return;
    try {
      const data = await getAlerts(selectedProject, null, null, null);
      alerts = (data || []).slice(-20);
    } catch {
      // ignore
    }
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (!realtimeEnabled) return;
      await refreshRuns();
      await refreshAlerts();
    }, 1000);
  }

  function applyUrlTokens() {
    const params = new URLSearchParams(window.location.search);
    let changed = false;
    const wt = params.get("write_token");
    if (wt) {
      const maxAge = 60 * 60 * 24 * 7;
      document.cookie = `trackio_write_token=${encodeURIComponent(wt)}; path=/; max-age=${maxAge}; SameSite=Lax`;
      params.delete("write_token");
      changed = true;
    }
    const oauthSession = params.get("oauth_session");
    if (oauthSession) {
      sessionStorage.setItem("trackio_oauth_session", oauthSession);
      params.delete("oauth_session");
      changed = true;
    }
    if (changed) {
      const q = params.toString();
      const path = window.location.pathname + (q ? `?${q}` : "");
      window.history.replaceState({}, "", path);
    }
  }

  async function refreshMutationAccess() {
    try {
      const s = await getRunMutationStatus();
      mutationStatus = {
        spaces: !!s.spaces,
        allowed: !!s.allowed,
        auth: s.auth ?? "none",
      };
    } catch {
      mutationStatus = { spaces: false, allowed: true, auth: "local" };
    }
  }

  function startMutationPolling() {
    if (mutationPollTimer) clearInterval(mutationPollTimer);
    mutationPollTimer = setInterval(() => {
      refreshMutationAccess();
    }, 120000);
  }

  $effect(() => {
    selectedProject;
    refreshRuns();
  });

  onMount(() => {
    const sidebarParam = getQueryParam("sidebar");
    if (sidebarParam === "hidden") {
      sidebarHidden = true;
      sidebarOpen = false;
    } else if (sidebarParam === "collapsed") {
      sidebarHidden = false;
      sidebarOpen = false;
    } else {
      sidebarHidden = false;
    }

    const smoothingParam = getQueryParam("smoothing");
    if (smoothingParam) {
      const s = parseInt(smoothingParam, 10);
      if (!Number.isNaN(s)) smoothing = s;
    }

    const metricsParam = getQueryParam("metrics");
    if (metricsParam) {
      const parts = metricsParam.split(",").map((s) => s.trim()).filter(Boolean);
      if (parts.length) {
        metricFilter = parts
          .map((p) => {
            const esc = p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            return `^${esc}$`;
          })
          .join("|");
      }
    }

    if (getQueryParam("accordion") === "hidden") {
      showHeaders = false;
    }

    currentPage = getPageFromPath();

    window.addEventListener("popstate", () => {
      currentPage = getPageFromPath();
      urlTick++;
      applyLockedProject();
    });

    applyUrlTokens();

    (async () => {
      const staticMode = await isStaticMode();

      if (!staticMode) {
        refreshMutationAccess();
        startMutationPolling();
        window.addEventListener("focus", refreshMutationAccess);
      } else {
        realtimeEnabled = false;
        mutationStatus = { spaces: false, allowed: false, auth: "static" };
        readOnlySource = await getReadOnlySource();
      }

      try {
        try {
          const settings = await getSettings();
          if (settings) {
            if (settings.logo_urls) logoUrls = settings.logo_urls;
            if (settings.color_palette) setColorPalette(settings.color_palette);
            if (settings.plot_order) plotOrder = settings.plot_order;
            if (settings.table_truncate_length) tableTruncateLength = settings.table_truncate_length;
            if (settings.media_dir) setMediaDir(settings.media_dir);
            if (settings.space_id) spaceId = settings.space_id;
          }
        } catch {
          // settings endpoint may not be available
        }
        await refreshProjects();
        await refreshRuns();
        await refreshAlerts();
      } catch (e) {
        console.error("Failed to load projects:", e);
      } finally {
        appBootstrapReady = true;
      }

      if (!staticMode) {
        startPolling();
      }
    })();

    return () => {
      if (pollTimer) clearInterval(pollTimer);
      if (mutationPollTimer) clearInterval(mutationPollTimer);
      window.removeEventListener("focus", refreshMutationAccess);
    };
  });

  let projectLocked = $derived.by(() => {
    urlTick;
    const n = lockedProjectName();
    return !!(n && projects.includes(n));
  });

  $effect(() => {
    projects;
    urlTick;
    if (projectLocked) applyLockedProject();
  });

  let showSidebar = $derived(
    currentPage === "metrics" ||
      currentPage === "system" ||
      currentPage === "media" ||
      currentPage === "reports" ||
      currentPage === "runs" ||
      currentPage === "run-detail" ||
      currentPage === "files" ||
      currentPage === "settings"
  );

  let sidebarVariant = $derived(
    currentPage === "runs" || currentPage === "files" ? "compact" : "full"
  );
</script>

<div class="app">
  {#if showSidebar && !sidebarHidden}
    <Sidebar
      bind:open={sidebarOpen}
      variant={sidebarVariant}
      {currentPage}
      spacesMode={mutationStatus.spaces}
      runMutationAllowed={mutationStatus.allowed}
      mutationAuth={mutationStatus.auth}
      {readOnlySource}
      {projects}
      projectLocked={projectLocked}
      bind:selectedProject
      {runs}
      bind:selectedRuns
      bind:smoothing
      bind:xAxis
      bind:logScaleX
      bind:logScaleY
      bind:metricFilter
      bind:realtimeEnabled
      bind:showHeaders
      bind:filterText
      {metricColumns}
      {logoUrls}
    />
  {/if}

  <div class="main">
    <Navbar {currentPage} onNavigate={handleNavigate} />

    <div class="page-content">
      {#if currentPage === "metrics"}
        <Metrics
          project={selectedProject}
          {selectedRuns}
          allRuns={runs}
          {smoothing}
          {xAxis}
          {logScaleX}
          {logScaleY}
          {metricFilter}
          {showHeaders}
          {appBootstrapReady}
          {plotOrder}
          bind:metricColumns
        />
      {:else if currentPage === "system"}
        <SystemMetrics
          project={selectedProject}
          {selectedRuns}
          {smoothing}
          {appBootstrapReady}
        />
      {:else if currentPage === "media"}
        <Media project={selectedProject} {selectedRuns} {tableTruncateLength} />
      {:else if currentPage === "reports"}
        <Reports project={selectedProject} {selectedRuns} />
      {:else if currentPage === "runs"}
        <Runs
          project={selectedProject}
          {runs}
          onRunsChanged={refreshRunsAndMutation}
          runMutationAllowed={mutationStatus.allowed}
        />
      {:else if currentPage === "run-detail"}
        <RunDetail project={selectedProject} />
      {:else if currentPage === "files"}
        <Files project={selectedProject} />
      {:else if currentPage === "settings"}
        <Settings {spaceId} selectedProject={selectedProject} />
      {/if}
    </div>
  </div>

  <AlertPanel {alerts} />
</div>

<style>
  :global(*) {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }

  :global(body) {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      "Helvetica Neue", Arial, sans-serif;
    background: var(--background-fill-primary, #fff);
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-md, 14px);
    -webkit-font-smoothing: antialiased;
  }

  .app {
    display: flex;
    height: 100vh;
    overflow: hidden;
  }

  .main {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-width: 0;
  }

  .page-content {
    flex: 1;
    overflow: hidden;
    display: flex;
    background: var(--bg-primary);
  }
</style>
