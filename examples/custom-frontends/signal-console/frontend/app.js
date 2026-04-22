import { mountTheme } from "./shared-theme.js";

mountTheme({
  title: document.querySelector("#title"),
  projectSelect: document.querySelector("#project-select"),
  runSelect: document.querySelector("#run-select"),
  metricsEl: document.querySelector("#metrics"),
  metricsSubtitle: document.querySelector("#metrics-subtitle"),
  statusLine: document.querySelector("#status-line"),
  runsCount: document.querySelector("#runs-count"),
  metricsCount: document.querySelector("#metrics-count"),
  selectedRunName: document.querySelector("#selected-run-name"),
});
