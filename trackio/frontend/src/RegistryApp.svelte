<script>
  import { onMount } from "svelte";
  import { DEFAULT_LOGO_URLS } from "./components/Logo.svelte";
  import { getSettings } from "./lib/api.js";
  import { setColorPalette } from "./lib/stores.js";
  import { initTheme, isDark, onThemeChange } from "./lib/theme.js";
  import { applyUrlTokens } from "./lib/urlTokens.js";
  import Registries from "./pages/Registries.svelte";

  initTheme();
  applyUrlTokens();

  let darkMode = $state(isDark());
  let logoUrls = $state(DEFAULT_LOGO_URLS);
  onThemeChange((dark) => (darkMode = dark));

  onMount(async () => {
    try {
      const settings = await getSettings();
      if (settings?.logo_urls) logoUrls = settings.logo_urls;
      if (settings?.color_palette) setColorPalette(settings.color_palette);
    } catch {}
  });
</script>

<div class="registry-app">
  <header class="app-header">
    <img src={darkMode ? logoUrls.dark : logoUrls.light} alt="Trackio" />
    <span>Registry</span>
  </header>
  <Registries />
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
    background: var(--background-fill-secondary, #f9fafb);
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-md, 14px);
  }
  .registry-app {
    min-height: 100vh;
  }
  .app-header {
    height: 45px;
    padding: 0 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-primary, white);
  }
  .app-header img {
    width: 112px;
    display: block;
  }
  .app-header span {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
</style>
