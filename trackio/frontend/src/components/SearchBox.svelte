<script>
  let { value = $bindable(""), placeholder = "Search…" } = $props();
</script>

<div class="search-box">
  <svg class="search-icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
    <circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.5" />
    <path
      d="M11 11l3 3"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="round"
    />
  </svg>
  <input type="text" {placeholder} bind:value />
  {#if value}
    <button class="clear-search" onclick={() => (value = "")} title="Clear search"
      >×</button
    >
  {/if}
</div>

<style>
  .search-box {
    position: relative;
    display: flex;
    align-items: center;
  }
  .search-icon {
    position: absolute;
    left: 10px;
    color: var(--body-text-color-subdued, #9ca3af);
    pointer-events: none;
  }
  .search-box input {
    width: 100%;
    padding: 6px 26px 6px 30px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-secondary, #f9fafb);
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-sm, 13px);
    outline: none;
  }
  .search-box input:focus {
    border-color: var(--color-accent, #f97316);
  }
  .clear-search {
    position: absolute;
    right: 8px;
    border: none;
    background: none;
    color: var(--body-text-color-subdued, #9ca3af);
    font-size: 18px;
    line-height: 1;
    cursor: pointer;
    padding: 0 2px;
  }
  .clear-search:hover {
    color: var(--body-text-color, #1f2937);
  }
</style>
