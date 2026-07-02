<script>
  let {
    panelsPerRow = 4,
    rowsToShow = "all",
    currentPage = 0,
    totalPanels = 0,
    perRowOptions = [1, 2, 3, 4, 5, 6],
    onPanelsPerRowChange = () => {},
    onRowsToShowChange = () => {},
    onPageChange = () => {},
  } = $props();

  let rowsOpen = $state(false);
  let containerEl;

  let availableOptions = $derived(
    perRowOptions.filter((n) => n <= Math.max(totalPanels, 1)),
  );
  let cols = $derived(Math.max(1, Math.min(panelsPerRow, totalPanels || 1)));
  let totalRows = $derived(Math.max(1, Math.ceil(totalPanels / cols)));
  let rowOptions = $derived(Array.from({ length: totalRows }, (_, i) => i + 1));
  let effectiveRowsPerPage = $derived(
    rowsToShow === "all" ? totalRows : Math.max(1, Math.min(rowsToShow, totalRows)),
  );
  let totalPages = $derived(Math.max(1, Math.ceil(totalRows / effectiveRowsPerPage)));
  let page = $derived(Math.min(Math.max(0, currentPage), totalPages - 1));
  let rowStart = $derived(page * effectiveRowsPerPage + 1);
  let rowEnd = $derived(Math.min(totalRows, rowStart + effectiveRowsPerPage - 1));
  let rowsLabel = $derived(
    totalPages <= 1
      ? `All rows (${totalRows})`
      : `Rows ${rowStart}-${rowEnd} of ${totalRows}`,
  );

  function toggleRowsMenu() {
    rowsOpen = !rowsOpen;
  }

  function selectRows(value) {
    onRowsToShowChange(value);
    rowsOpen = false;
  }

  function prevPage() {
    if (page > 0) onPageChange(page - 1);
  }

  function nextPage() {
    if (page < totalPages - 1) onPageChange(page + 1);
  }

  function handleOutsideClick(e) {
    if (containerEl && !containerEl.contains(e.target)) {
      rowsOpen = false;
    }
  }

  $effect(() => {
    if (!rowsOpen) return;
    window.addEventListener("mousedown", handleOutsideClick);
    return () => window.removeEventListener("mousedown", handleOutsideClick);
  });
</script>

<div class="group-panel-controls" bind:this={containerEl}>
  {#if totalPanels > 1}
    <select
      class="per-row-select"
      value={cols}
      onchange={(e) => onPanelsPerRowChange(Number(e.currentTarget.value))}
      aria-label="Panels per row"
      title="Panels per row"
    >
      {#each availableOptions as n}
        <option value={n}>{n}/row</option>
      {/each}
    </select>
  {/if}

  {#if totalRows > 1}
    <div class="rows-select">
      {#if totalPages > 1}
        <button
          type="button"
          class="page-nav"
          onclick={prevPage}
          disabled={page <= 0}
          aria-label="Previous rows"
        >
          ‹
        </button>
      {/if}
      <button type="button" class="rows-button" onclick={toggleRowsMenu}>
        <span>{rowsLabel}</span>
        <span class="chevron" class:open={rowsOpen}>▾</span>
      </button>
      {#if totalPages > 1}
        <button
          type="button"
          class="page-nav"
          onclick={nextPage}
          disabled={page >= totalPages - 1}
          aria-label="Next rows"
        >
          ›
        </button>
      {/if}
      {#if rowsOpen}
        <ul class="rows-menu" role="listbox">
          {#each rowOptions as r}
            <li>
              <button
                type="button"
                class="rows-option"
                class:selected={rowsToShow === r}
                onclick={() => selectRows(r)}
              >
                {r} row{r === 1 ? "" : "s"} per page
              </button>
            </li>
          {/each}
          <li class="rows-menu-divider"></li>
          <li>
            <button
              type="button"
              class="rows-option"
              class:selected={rowsToShow === "all"}
              onclick={() => selectRows("all")}
            >
              Show all rows
            </button>
          </li>
        </ul>
      {/if}
    </div>
  {/if}
</div>

<style>
  .group-panel-controls {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .per-row-select {
    font-size: 12px;
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-secondary, #f9fafb);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-sm, 4px);
    padding: 3px 6px;
    cursor: pointer;
  }
  .rows-select {
    position: relative;
    display: flex;
    align-items: center;
    gap: 2px;
  }
  .page-nav {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 22px;
    font-size: 13px;
    line-height: 1;
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-secondary, #f9fafb);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-sm, 4px);
    cursor: pointer;
    padding: 0;
  }
  .page-nav:hover:not(:disabled) {
    color: var(--body-text-color, #1f2937);
  }
  .page-nav:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .rows-button {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-secondary, #f9fafb);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-sm, 4px);
    padding: 3px 6px;
    cursor: pointer;
    white-space: nowrap;
  }
  .rows-button:hover {
    color: var(--body-text-color, #1f2937);
  }
  .chevron {
    font-size: 10px;
    transition: transform 0.15s;
    display: inline-block;
  }
  .chevron.open {
    transform: rotate(180deg);
  }
  .rows-menu {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    z-index: var(--layer-top, 9999);
    margin: 0;
    padding: 4px 0;
    min-width: 150px;
    list-style: none;
    background: var(--background-fill-primary, white);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  }
  .rows-menu-divider {
    height: 1px;
    margin: 4px 0;
    background: var(--border-color-primary, #e5e7eb);
  }
  .rows-option {
    display: block;
    width: 100%;
    text-align: left;
    padding: 6px 12px;
    font-size: 13px;
    color: var(--body-text-color, #1f2937);
    background: none;
    border: none;
    cursor: pointer;
  }
  .rows-option:hover {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .rows-option.selected {
    font-weight: 600;
  }
</style>
