import { getAllProjects, getRunsForProject, getLogs } from "./api.js";

export function createDashboardState() {
  let projects = $state([]);
  let selectedProject = $state(null);
  let runs = $state([]);
  let selectedRuns = $state([]);
  let runColors = $state({});
  let smoothing = $state(10);
  let xAxis = $state("step");
  let logScaleX = $state(false);
  let logScaleY = $state(false);
  let metricFilter = $state("");
  let realtimeEnabled = $state(true);
  let showHeaders = $state(true);
  let filterText = $state("");
  let sidebarOpen = $state(true);
  let currentPage = $state("metrics");
  let loading = $state(false);
  let theme = $state("default");

  return {
    get projects() {
      return projects;
    },
    set projects(v) {
      projects = v;
    },
    get selectedProject() {
      return selectedProject;
    },
    set selectedProject(v) {
      selectedProject = v;
    },
    get runs() {
      return runs;
    },
    set runs(v) {
      runs = v;
    },
    get selectedRuns() {
      return selectedRuns;
    },
    set selectedRuns(v) {
      selectedRuns = v;
    },
    get runColors() {
      return runColors;
    },
    set runColors(v) {
      runColors = v;
    },
    get smoothing() {
      return smoothing;
    },
    set smoothing(v) {
      smoothing = v;
    },
    get xAxis() {
      return xAxis;
    },
    set xAxis(v) {
      xAxis = v;
    },
    get logScaleX() {
      return logScaleX;
    },
    set logScaleX(v) {
      logScaleX = v;
    },
    get logScaleY() {
      return logScaleY;
    },
    set logScaleY(v) {
      logScaleY = v;
    },
    get metricFilter() {
      return metricFilter;
    },
    set metricFilter(v) {
      metricFilter = v;
    },
    get realtimeEnabled() {
      return realtimeEnabled;
    },
    set realtimeEnabled(v) {
      realtimeEnabled = v;
    },
    get showHeaders() {
      return showHeaders;
    },
    set showHeaders(v) {
      showHeaders = v;
    },
    get filterText() {
      return filterText;
    },
    set filterText(v) {
      filterText = v;
    },
    get sidebarOpen() {
      return sidebarOpen;
    },
    set sidebarOpen(v) {
      sidebarOpen = v;
    },
    get currentPage() {
      return currentPage;
    },
    set currentPage(v) {
      currentPage = v;
    },
    get loading() {
      return loading;
    },
    set loading(v) {
      loading = v;
    },
    get theme() {
      return theme;
    },
    set theme(v) {
      theme = v;
    },
  };
}

export const DEFAULT_COLORS = [
  "#A8769B",
  "#E89957",
  "#3B82F6",
  "#10B981",
  "#EF4444",
  "#8B5CF6",
  "#14B8A6",
  "#F59E0B",
  "#EC4899",
  "#06B6D4",
];

export function getColorForIndex(i) {
  return DEFAULT_COLORS[i % DEFAULT_COLORS.length];
}

export function buildColorMap(runs, smoothing) {
  const map = {};
  runs.forEach((run, i) => {
    const base = getColorForIndex(i);
    if (smoothing > 0) {
      map[run] = base + "4D";
      map[run + "_smoothed"] = base;
    } else {
      map[run] = base;
    }
  });
  return map;
}
