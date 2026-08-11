<script>
  import Logo from "./Logo.svelte";
  import ProjectSelector from "./ProjectSelector.svelte";

  let {
    open = $bindable(true),
    projects = [],
    selectedProject = $bindable(null),
    projectLocked = false,
    logoUrls = undefined,
    darkMode = false,
    header = undefined,
    footer = undefined,
    children = undefined,
  } = $props();
</script>

<aside class="sidebar-shell" class:collapsed={!open}>
  <button
    class="toggle-btn"
    title={open ? "Collapse sidebar" : "Expand sidebar"}
    onclick={() => (open = !open)}
  >
    {#if open}
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path
          d="M10 12L6 8L10 4"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    {:else}
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path
          d="M6 4L10 8L6 12"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    {/if}
  </button>

  {#if open}
    <div class="shell-header">
      <Logo {logoUrls} {darkMode} />
      <ProjectSelector {projects} bind:selectedProject {projectLocked} />
      {#if header}{@render header()}{/if}
    </div>
    <div class="shell-body">
      {@render children?.()}
    </div>
    {#if footer}{@render footer()}{/if}
  {/if}
</aside>

<style>
  .sidebar-shell {
    width: 290px;
    min-width: 290px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    position: relative;
    border-right: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-primary, #fff);
    overflow: hidden;
    transition:
      width 0.2s,
      min-width 0.2s;
  }
  .sidebar-shell.collapsed {
    width: 40px;
    min-width: 40px;
  }
  .toggle-btn {
    position: absolute;
    top: 12px;
    right: 8px;
    z-index: 10;
    border: none;
    background: none;
    color: var(--body-text-color-subdued, #9ca3af);
    cursor: pointer;
    padding: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-sm, 4px);
    transition:
      color 0.15s,
      background-color 0.15s;
  }
  .toggle-btn:hover {
    color: var(--body-text-color, #1f2937);
    background-color: var(--background-fill-secondary, #f9fafb);
  }
  .shell-header {
    padding: 16px 16px 10px;
    flex-shrink: 0;
  }
  .shell-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }
</style>
