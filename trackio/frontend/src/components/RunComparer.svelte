<!--
@component
Run comparer panel: the selected runs as color-coded columns,
their dot-flattened config keys and run metadata as rows, with a "Diff
only" toggle, key search, per-cell copy of the full value, and an accent
on rows that differ. Collapsed by default; shows at most the first
COMPARER_MAX_COLUMNS selected runs.

Props:
- `runs` — run records in sidebar order
- `runConfigs` — nested configs keyed by run id (name as fallback)
- `colorMap` — run key → color, shared with the charts and sidebar
-->
<script>
  import { onDestroy } from "svelte";
  import Accordion from "./Accordion.svelte";
  import GradioCheckbox from "./GradioCheckbox.svelte";
  import GradioTextbox from "./GradioTextbox.svelte";
  import { copyTextToClipboard } from "../lib/clipboard.js";
  import {
    COMPARER_MAX_COLUMNS,
    MISSING_MARKER,
    buildComparerRows,
    filterComparerRows,
    formatCellValue,
    runKeyOf,
  } from "../lib/comparer.js";

  let { runs = [], runConfigs = {}, colorMap = {} } = $props();

  const SECTION_LABELS = {
    config: "Config",
    metadata: "Metadata",
  };
  const SECTION_ORDER = ["config", "metadata"];
  const DISPLAY_LIMIT = 200;
  const TITLE_LIMIT = 1000;

  let open = $state(false);
  let searchText = $state("");
  let diffOnly = $state(false);
  let copiedCell = $state(null);
  let copyTimer = null;

  let displayRuns = $derived(runs.slice(0, COMPARER_MAX_COLUMNS));
  let allRows = $derived(buildComparerRows(displayRuns, runConfigs));
  let rows = $derived(filterComparerRows(allRows, searchText, diffOnly));
  let sections = $derived(
    SECTION_ORDER.map((section) => ({
      section,
      label: SECTION_LABELS[section],
      rows: rows.filter((row) => row.section === section),
    })).filter((group) => group.rows.length > 0),
  );

  function cellId(row, colIndex) {
    return `${row.section}\0${row.key}\0${colIndex}`;
  }

  async function copyCell(row, colIndex, text) {
    const copied = await copyTextToClipboard(text);
    if (!copied) return;
    copiedCell = cellId(row, colIndex);
    if (copyTimer) {
      clearTimeout(copyTimer);
    }
    copyTimer = setTimeout(() => {
      copiedCell = null;
      copyTimer = null;
    }, 1200);
  }

  /**
   * Truncates display text at `limit` UTF-16 code units, dropping a
   * trailing high surrogate so an emoji is never cut in half, and appends
   * an ellipsis. Copying is unaffected — it always uses the full text.
   */
  function truncate(text, limit) {
    if (text.length <= limit) {
      return text;
    }
    let sliced = text.slice(0, limit);
    if (/[\uD800-\uDBFF]$/.test(sliced)) {
      sliced = sliced.slice(0, -1);
    }
    return sliced + "…";
  }

  onDestroy(() => {
    if (copyTimer) {
      clearTimeout(copyTimer);
    }
  });
</script>

<div class="run-comparer">
  <Accordion label="Run comparer" bind:open>
    {#if runs.length === 0}
      <p class="comparer-empty">Select runs to compare.</p>
    {:else if allRows.length === 0}
      <p class="comparer-empty">No config values to compare.</p>
    {:else}
      <div class="comparer-controls">
        <div class="comparer-search">
          <GradioTextbox
            showLabel={false}
            placeholder="Search keys"
            bind:value={searchText}
          />
        </div>
        <GradioCheckbox label="Diff only" bind:checked={diffOnly} />
        {#if runs.length > COMPARER_MAX_COLUMNS}
          <span class="comparer-note">
            Showing first {COMPARER_MAX_COLUMNS} of {runs.length} selected runs
          </span>
        {/if}
      </div>
      {#if rows.length === 0}
        <p class="comparer-empty">No matching keys.</p>
      {:else}
        <div class="comparer-scroll">
          <table class="comparer-table">
            <thead>
              <tr>
                <th class="key-col">Key</th>
                {#each displayRuns as run (runKeyOf(run))}
                  <th class="run-col">
                    <div class="run-header">
                      <span
                        class="color-dot"
                        style="background: {colorMap[runKeyOf(run)] || '#999'}"
                      ></span>
                      <span class="run-name" title={run.name}>{run.name}</span>
                    </div>
                  </th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each sections as group (group.section)}
                <tr class="section-row">
                  <td class="key-col">{group.label}</td>
                  <td colspan={displayRuns.length}></td>
                </tr>
                {#each group.rows as row (`${row.section}\0${row.key}`)}
                  <tr class:differs={row.differs}>
                    <td class="key-col" title={row.label}>{row.label}</td>
                    {#each displayRuns as run, colIndex (runKeyOf(run))}
                      {@const cell = formatCellValue(row.values[colIndex])}
                      <td class="value-cell">
                        {#if cell.missing}
                          <span class="missing">{MISSING_MARKER}</span>
                        {:else}
                          <span
                            class="cell-text"
                            title={truncate(cell.text, TITLE_LIMIT)}
                          >
                            {truncate(cell.text, DISPLAY_LIMIT)}
                          </span>
                          {#if cell.text !== ""}
                            <button
                              class="copy-btn"
                              title="Copy value"
                              aria-label="Copy value"
                              onclick={() => copyCell(row, colIndex, cell.text)}
                            >
                              {#if copiedCell === cellId(row, colIndex)}
                                <svg
                                  width="12"
                                  height="12"
                                  viewBox="0 0 16 16"
                                  fill="none"
                                >
                                  <path
                                    d="M3 8.5L6.5 12L13 4.5"
                                    stroke="currentColor"
                                    stroke-width="1.6"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                  />
                                </svg>
                              {:else}
                                <svg
                                  width="12"
                                  height="12"
                                  viewBox="0 0 16 16"
                                  fill="none"
                                >
                                  <rect
                                    x="5.5"
                                    y="5.5"
                                    width="8"
                                    height="8"
                                    rx="1.5"
                                    stroke="currentColor"
                                    stroke-width="1.4"
                                  />
                                  <path
                                    d="M10.5 5.5V4A1.5 1.5 0 0 0 9 2.5H4A1.5 1.5 0 0 0 2.5 4v5A1.5 1.5 0 0 0 4 10.5h1.5"
                                    stroke="currentColor"
                                    stroke-width="1.4"
                                  />
                                </svg>
                              {/if}
                            </button>
                          {/if}
                        {/if}
                      </td>
                    {/each}
                  </tr>
                {/each}
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    {/if}
  </Accordion>
</div>

<style>
  .comparer-controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
    margin-bottom: 10px;
  }
  .comparer-search {
    width: 240px;
    max-width: 100%;
  }
  .comparer-note {
    font-size: 12px;
    color: var(--body-text-color-subdued, #9ca3af);
  }
  .comparer-empty {
    margin: 4px 0;
    font-size: 13px;
    color: var(--body-text-color-subdued, #9ca3af);
  }
  .comparer-scroll {
    overflow: auto;
    max-height: 420px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
  }
  .comparer-table {
    border-collapse: separate;
    border-spacing: 0;
    min-width: 100%;
    font-size: 13px;
  }
  .comparer-table th,
  .comparer-table td {
    padding: 6px 10px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    text-align: left;
    white-space: nowrap;
    color: var(--body-text-color, #1f2937);
  }
  .comparer-table thead th {
    position: sticky;
    top: 0;
    z-index: 2;
    background: var(--background-fill-primary, white);
    font-weight: 600;
  }
  .key-col {
    position: sticky;
    left: 0;
    z-index: 1;
    background: var(--background-fill-primary, white);
    border-right: 1px solid var(--border-color-primary, #e5e7eb);
    min-width: 140px;
    max-width: 260px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .comparer-table thead th.key-col {
    z-index: 3;
  }
  th.run-col {
    min-width: 130px;
  }
  .run-header {
    display: flex;
    align-items: center;
    gap: 6px;
    max-width: 220px;
  }
  .color-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .run-header .run-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .section-row td {
    background: var(--background-fill-secondary, #f9fafb);
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .value-cell {
    position: relative;
    min-width: 110px;
    max-width: 320px;
    padding-right: 30px;
  }
  .cell-text {
    display: inline-block;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    vertical-align: middle;
  }
  .missing {
    color: var(--body-text-color-subdued, #9ca3af);
  }
  tr.differs td {
    background: var(--color-accent-soft, #fff7ed);
  }
  tr.differs td.key-col {
    background: var(--color-accent-soft, #fff7ed);
    box-shadow: inset 3px 0 0 var(--color-accent, #f97316);
  }
  .copy-btn {
    position: absolute;
    top: 50%;
    right: 4px;
    transform: translateY(-50%);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 3px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: 4px;
    background: var(--background-fill-primary, white);
    color: var(--body-text-color-subdued, #6b7280);
    cursor: pointer;
    opacity: 0;
    transition:
      opacity 0.12s,
      color 0.12s;
  }
  .value-cell:hover .copy-btn,
  .copy-btn:focus-visible {
    opacity: 1;
  }
  .copy-btn:hover {
    color: var(--color-accent, #f97316);
  }
</style>
