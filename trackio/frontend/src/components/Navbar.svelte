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
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M6.86 1.58a.98.98 0 0 1 1.9 0l.16.88a.73.73 0 0 0 1 .5l.8-.4a.98.98 0 0 1 1.34 1.34l-.4.8a.73.73 0 0 0 .5 1l.88.16a.98.98 0 0 1 0 1.9l-.88.16a.73.73 0 0 0-.5 1l.4.8a.98.98 0 0 1-1.34 1.34l-.8-.4a.73.73 0 0 0-1 .5l-.16.88a.98.98 0 0 1-1.9 0l-.16-.88a.73.73 0 0 0-1-.5l-.8.4a.98.98 0 0 1-1.34-1.34l.4-.8a.73.73 0 0 0-.5-1l-.88-.16a.98.98 0 0 1 0-1.9l.88-.16a.73.73 0 0 0 .5-1l-.4-.8A.98.98 0 0 1 4.9 2.56l.8.4a.73.73 0 0 0 1-.5l.16-.88Z" />
        <circle cx="7.81" cy="7.81" r="2.2" />
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
