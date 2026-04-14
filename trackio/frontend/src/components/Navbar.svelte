<script>
  let { currentPage = "metrics", onNavigate } = $props();

  const links = [
    { id: "metrics", label: "Metrics" },
    { id: "system", label: "System Metrics" },
    { id: "media", label: "Media & Tables" },
    { id: "reports", label: "Alerts & Reports" },
    { id: "runs", label: "Runs" },
    { id: "files", label: "Files" },
  ];

  function handleClick(id) {
    onNavigate?.(id);
  }
</script>

<nav class="navbar">
  <div class="nav-spacer"></div>
  <div class="nav-tabs">
    {#each links as link}
      <button
        class="nav-link"
        class:active={currentPage === link.id}
        onclick={() => handleClick(link.id)}
      >
        {link.label}
      </button>
    {/each}
    <button
      class="nav-link settings-btn"
      class:active={currentPage === "settings"}
      onclick={() => handleClick("settings")}
      title="CLI & Settings"
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
        <circle cx="12" cy="12" r="3"/>
      </svg>
      <span>Settings</span>
    </button>
  </div>
</nav>

<style>
  .navbar {
    display: flex;
    align-items: stretch;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-primary, white);
    padding: 0;
    flex-shrink: 0;
    min-height: 44px;
  }
  .nav-spacer {
    flex: 1 1 0;
    min-width: 0;
  }
  .nav-tabs {
    display: flex;
    gap: 0;
    flex-shrink: 0;
    padding-right: 8px;
  }
  .nav-link {
    padding: 10px 16px;
    border: none;
    background: none;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-md, 14px);
    cursor: pointer;
    white-space: nowrap;
    border-bottom: 2px solid transparent;
    transition: color 0.15s;
    font-weight: 400;
  }
  .nav-link:hover {
    color: var(--body-text-color, #1f2937);
  }
  .nav-link.active {
    color: var(--body-text-color, #1f2937);
    border-bottom-color: var(--body-text-color, #1f2937);
    font-weight: 500;
  }
  .settings-btn {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .settings-btn svg {
    flex-shrink: 0;
  }
</style>
