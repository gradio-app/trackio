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
  import { getAllProjects, getRunsForProject, getAlerts } from "./lib/api.js";
  import { getPageFromPath, navigateTo, getQueryParam } from "./lib/router.js";
  import { applyTheme, detectSystemTheme } from "./lib/theme.js";
  import { DEFAULT_COLORS, getColorForIndex } from "./lib/stores.js";

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
  let sidebarOpen = $state(true);
  let alerts = $state([]);
  let pollTimer = $state(null);

  function handleNavigate(page) {
    currentPage = page;
    navigateTo(page);
  }

  async function refreshProjects() {
    try {
      const data = await getAllProjects();
      projects = data || [];
      if (projects.length > 0 && !selectedProject) {
        const paramProject = getQueryParam("project") || getQueryParam("selected_project");
        selectedProject = paramProject && projects.includes(paramProject)
          ? paramProject
          : projects[0];
      }
    } catch (e) {
      console.error("Failed to load projects:", e);
    }
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

        const newEntries = newRuns.filter((r) => !prevSelected.has(r) && prevSelected.size === 0);
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
    }, 2000);
  }

  $effect(() => {
    selectedProject;
    refreshRuns();
  });

  onMount(() => {
    const themeName = getQueryParam("theme") || detectSystemTheme();
    applyTheme(themeName);

    const sidebarParam = getQueryParam("sidebar");
    if (sidebarParam === "collapsed" || sidebarParam === "hidden") {
      sidebarOpen = false;
    }

    const smoothingParam = getQueryParam("smoothing");
    if (smoothingParam) smoothing = parseInt(smoothingParam);

    currentPage = getPageFromPath();

    window.addEventListener("popstate", () => {
      currentPage = getPageFromPath();
    });

    refreshProjects().then(() => {
      refreshRuns();
      refreshAlerts();
    });

    startPolling();

    return () => {
      if (pollTimer) clearInterval(pollTimer);
    };
  });

  let showSidebar = $derived(
    currentPage === "metrics" ||
    currentPage === "system"
  );
</script>

<div class="app">
  {#if showSidebar}
    <Sidebar
      bind:open={sidebarOpen}
      {projects}
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
        />
      {:else if currentPage === "system"}
        <SystemMetrics project={selectedProject} {runs} />
      {:else if currentPage === "media"}
        <Media project={selectedProject} {runs} />
      {:else if currentPage === "reports"}
        <Reports project={selectedProject} {runs} />
      {:else if currentPage === "runs"}
        <Runs project={selectedProject} />
      {:else if currentPage === "run-detail"}
        <RunDetail project={selectedProject} />
      {:else if currentPage === "files"}
        <Files project={selectedProject} />
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
    background: var(--bg-primary, #fff);
    color: var(--text-primary, #111);
    -webkit-font-smoothing: antialiased;
  }

  :global(:root) {
    --bg-primary: #ffffff;
    --bg-secondary: #f9fafb;
    --bg-tertiary: #f3f4f6;
    --bg-sidebar: #ffffff;
    --text-primary: #111827;
    --text-secondary: #6b7280;
    --text-muted: #9ca3af;
    --border-color: #e5e7eb;
    --border-light: #f3f4f6;
    --accent-color: #f97316;
    --accent-hover: #ea580c;
    --accent-light: #fff7ed;
    --success-color: #10b981;
    --error-color: #ef4444;
    --warning-color: #f59e0b;
    --info-color: #3b82f6;
    --input-bg: #ffffff;
    --input-border: #d1d5db;
    --input-focus: #f97316;
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
    --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    --radius-sm: 6px;
    --radius-md: 8px;
    --radius-lg: 12px;
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
    background: var(--bg-secondary);
  }
</style>
