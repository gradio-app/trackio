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
    flex: 1;
  }
  .nav-tabs {
    display: flex;
    gap: 0;
    padding-right: 16px;
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
</style>
