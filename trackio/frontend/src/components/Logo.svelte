<script module>
  export const DEFAULT_LOGO_URLS = {
    light: "/static/trackio/trackio_logo_type_light_transparent.png",
    dark: "/static/trackio/trackio_logo_type_dark_transparent.png",
  };
</script>

<script>
  let { logoUrls = DEFAULT_LOGO_URLS, darkMode = false } = $props();
</script>

<div class="logo-section">
  <img
    src={darkMode ? logoUrls.dark : logoUrls.light}
    alt="Trackio"
    class="logo"
  />
</div>

<style>
  .logo-section {
    margin-bottom: 20px;
  }
  .logo {
    width: 80%;
    max-width: 200px;
  }
</style>
