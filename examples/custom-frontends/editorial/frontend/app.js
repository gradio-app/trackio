import { mountTheme } from "./shared-theme.js";

mountTheme({
  title: document.querySelector("#title"),
  projectSelect: document.querySelector("#project-select"),
  runSelect: document.querySelector("#run-select"),
  metricsEl: document.querySelector("#metrics"),
  metricsSubtitle: document.querySelector("#metrics-subtitle"),
  projectSummary: document.querySelector("#project-summary"),
  runsCount: document.querySelector("#runs-count"),
  metricsCount: document.querySelector("#metrics-count"),
  selectedRunName: document.querySelector("#selected-run-name"),
  selectedRunMeta: document.querySelector("#selected-run-meta"),
});
