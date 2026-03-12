<script>
  let { currentPage = "metrics", onNavigate } = $props();

  const links = [
    { id: "metrics", label: "Metrics" },
    { id: "system", label: "System Metrics" },
    { id: "media", label: "Media & Tables" },
    { id: "reports", label: "Reports" },
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
    border-bottom: 1px solid var(--border-color);
    background: var(--bg-primary);
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
    color: var(--text-secondary);
    font-size: 14px;
    cursor: pointer;
    white-space: nowrap;
    border-bottom: 2px solid transparent;
    transition: color 0.15s;
    font-weight: 400;
  }
  .nav-link:hover {
    color: var(--text-primary);
  }
  .nav-link.active {
    color: var(--text-primary);
    border-bottom-color: var(--text-primary);
    font-weight: 500;
  }
</style>
