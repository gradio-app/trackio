import { mountTheme } from "./shared-theme.js";

mountTheme({
  title: document.querySelector("#title"),
  projectsEl: document.querySelector("#projects"),
  runsEl: document.querySelector("#runs"),
  metricsEl: document.querySelector("#metrics"),
});
