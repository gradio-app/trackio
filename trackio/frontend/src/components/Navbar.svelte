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
  {#each links as link}
    <button
      class="nav-link"
      class:active={currentPage === link.id}
      onclick={() => handleClick(link.id)}
    >
      {link.label}
    </button>
  {/each}
</nav>

<style>
  .navbar {
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--border-color);
    background: var(--bg-primary);
    padding: 0 16px;
    overflow-x: auto;
    flex-shrink: 0;
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
    transition: all 0.15s;
  }
  .nav-link:hover {
    color: var(--text-primary);
    background: var(--bg-tertiary);
  }
  .nav-link.active {
    color: var(--accent-color);
    border-bottom-color: var(--accent-color);
    font-weight: 500;
  }
</style>
