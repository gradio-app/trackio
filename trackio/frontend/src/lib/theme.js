const THEME_KEY = "trackio_theme_preference";

let _listeners = [];

export function onThemeChange(fn) {
  _listeners.push(fn);
  return () => {
    _listeners = _listeners.filter((f) => f !== fn);
  };
}

function _notify() {
  const dark = isDark();
  _listeners.forEach((fn) => fn(dark));
}

const darkOverrides = {
  "--neutral-50": "#fafafa",
  "--neutral-100": "#f4f4f5",
  "--neutral-200": "#e4e4e7",
  "--neutral-300": "#d4d4d8",
  "--neutral-400": "#bbbbc2",
  "--neutral-500": "#71717a",
  "--neutral-600": "#52525b",
  "--neutral-700": "#3f3f46",
  "--neutral-800": "#27272a",
  "--neutral-900": "#18181b",
  "--neutral-950": "#0f0f11",

  "--background-fill-primary": "#0f0f11",
  "--background-fill-secondary": "#18181b",
  "--body-text-color": "#f4f4f5",
  "--body-text-color-subdued": "#bbbbc2",
  "--border-color-primary": "#3f3f46",
  "--color-accent": "#f97316",
  "--color-accent-soft": "#3f3f46",

  "--input-background-fill": "#27272a",
  "--input-background-fill-focus": "#f97316",
  "--input-border-color": "#3f3f46",
  "--input-border-color-focus": "#3f3f46",
  "--input-placeholder-color": "#71717a",
  "--input-shadow": "none",
  "--input-shadow-focus": "none",

  "--checkbox-background-color": "#27272a",
  "--checkbox-background-color-focus": "#27272a",
  "--checkbox-background-color-hover": "#27272a",
  "--checkbox-background-color-selected": "#f97316",
  "--checkbox-border-color": "#3f3f46",
  "--checkbox-border-color-focus": "#f97316",
  "--checkbox-border-color-hover": "#52525b",
  "--checkbox-border-color-selected": "#f97316",

  "--table-even-background-fill": "#0f0f11",
  "--table-odd-background-fill": "#18181b",

  "--slider-color": "#f97316",

  "--shadow-drop": "rgba(0,0,0,0.15) 0px 1px 2px 0px",
  "--shadow-drop-lg":
    "0 1px 3px 0 rgb(0 0 0 / 0.3), 0 1px 2px -1px rgb(0 0 0 / 0.2)",
  "--shadow-inset": "rgba(0,0,0,0.15) 0px 2px 4px 0px inset",

  "--block-title-text-color": "#bbbbc2",
  "--block-info-text-color": "#71717a",

  "--primary-50": "#3f3f46",
};

export function applyTheme(themeName) {
  const root = document.documentElement;
  if (themeName === "dark") {
    root.dataset.theme = "dark";
    Object.entries(darkOverrides).forEach(([key, value]) => {
      root.style.setProperty(key, value);
    });
  } else {
    delete root.dataset.theme;
    Object.keys(darkOverrides).forEach((key) => {
      root.style.removeProperty(key);
    });
  }
  _notify();
}

export function isDark() {
  return document.documentElement.dataset.theme === "dark";
}

export function detectSystemTheme() {
  if (
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  ) {
    return "dark";
  }
  return "default";
}

export function getThemePreference() {
  return localStorage.getItem(THEME_KEY) || "system";
}

export function setThemePreference(pref) {
  localStorage.setItem(THEME_KEY, pref);
  applyThemeFromPreference(pref);
}

export function applyThemeFromPreference(pref) {
  if (pref === "system") {
    applyTheme(detectSystemTheme());
  } else if (pref === "dark") {
    applyTheme("dark");
  } else {
    applyTheme("default");
  }
}

export function initTheme() {
  const urlTheme = new URLSearchParams(window.location.search).get("__theme");
  if (urlTheme) {
    applyTheme(urlTheme);
    return;
  }
  const pref = getThemePreference();
  applyThemeFromPreference(pref);

  if (pref === "system") {
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", () => {
        if (getThemePreference() === "system") {
          applyTheme(detectSystemTheme());
        }
      });
  }
}
