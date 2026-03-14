<script>
  let {
    headers = [],
    rows = [],
    selectable = false,
    selectedIndices = $bindable(new Set()),
    onrowclick = null,
    label = "",
    renderCell = null,
  } = $props();

  let sortCol = $state(null);
  let sortDir = $state("asc");

  function toggleSort(col) {
    if (sortCol === col) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortCol = col;
      sortDir = "asc";
    }
  }

  let sortedRows = $derived.by(() => {
    if (sortCol === null) return rows;
    const idx = headers.indexOf(sortCol);
    if (idx === -1) return rows;
    return [...rows].sort((a, b) => {
      const va = a[idx];
      const vb = b[idx];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "number" && typeof vb === "number") {
        return sortDir === "asc" ? va - vb : vb - va;
      }
      const sa = String(va);
      const sb = String(vb);
      return sortDir === "asc" ? sa.localeCompare(sb) : sb.localeCompare(sa);
    });
  });

  function toggleAll() {
    if (selectedIndices.size === rows.length) {
      selectedIndices = new Set();
    } else {
      selectedIndices = new Set(rows.map((_, i) => i));
    }
  }

  function toggleRow(i) {
    const next = new Set(selectedIndices);
    if (next.has(i)) {
      next.delete(i);
    } else {
      next.add(i);
    }
    selectedIndices = next;
  }
</script>

<div class="table-container">
  {#if label}
    <div class="header-row">
      <p class="label">{label}</p>
    </div>
  {/if}
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          {#if selectable}
            <th class="check-col">
              <input
                type="checkbox"
                checked={selectedIndices.size === rows.length && rows.length > 0}
                onchange={toggleAll}
              />
            </th>
          {/if}
          {#each headers as header, hi}
            <th
              class:first={hi === 0 && !selectable}
              class:last={hi === headers.length - 1}
              onclick={() => toggleSort(header)}
            >
              <div class="th-inner">
                <span>{header}</span>
                {#if sortCol === header}
                  <span class="sort-arrow">{sortDir === "asc" ? "↑" : "↓"}</span>
                {/if}
              </div>
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each sortedRows as row, ri}
          <tr
            class:row-odd={ri % 2 === 1}
            class:selected={selectedIndices.has(ri)}
            onclick={() => onrowclick?.(row, ri)}
          >
            {#if selectable}
              <td class="check-col" onclick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={selectedIndices.has(ri)}
                  onchange={() => toggleRow(ri)}
                />
              </td>
            {/if}
            {#each row as cell, ci}
              <td
                class:first={ci === 0 && !selectable}
                class:last={ci === row.length - 1}
              >
                {cell ?? ""}
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>

<style>
  .table-container {
    display: flex;
    flex-direction: column;
    gap: var(--size-2, 8px);
    position: relative;
  }
  .header-row {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    min-height: var(--size-6, 24px);
    width: 100%;
  }
  .header-row .label {
    flex: 1;
    margin: 0;
    color: var(--block-label-text-color, var(--neutral-500, #6b7280));
    font-size: var(--block-label-text-size, 12px);
    line-height: var(--line-sm, 1.4);
  }
  .table-wrap {
    position: relative;
    overflow: auto;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--table-radius, var(--radius-lg, 8px));
  }
  table {
    width: 100%;
    table-layout: auto;
    color: var(--body-text-color, #1f2937);
    font-size: var(--input-text-size, 14px);
    line-height: var(--line-sm, 1.4);
    border-spacing: 0;
    border-collapse: separate;
  }
  thead {
    position: sticky;
    top: 0;
    z-index: 5;
    box-shadow: var(--shadow-drop, rgba(0,0,0,0.05) 0px 1px 2px 0px);
  }
  th {
    padding: 0;
    background: var(--table-even-background-fill, white);
    border-right-width: 0px;
    border-left-width: 1px;
    border-bottom-width: 1px;
    border-style: solid;
    border-color: var(--border-color-primary, #e5e7eb);
    text-align: left;
    cursor: pointer;
    user-select: none;
  }
  th.first {
    border-left-width: 0;
    border-top-left-radius: var(--table-radius, var(--radius-lg, 8px));
  }
  th.last {
    border-top-right-radius: var(--table-radius, var(--radius-lg, 8px));
  }
  .th-inner {
    padding: var(--size-2, 8px);
    display: flex;
    align-items: center;
    gap: 4px;
    font-weight: 600;
    font-size: var(--text-sm, 12px);
    white-space: nowrap;
  }
  .sort-arrow {
    font-size: 10px;
    color: var(--body-text-color-subdued, #9ca3af);
  }
  td {
    padding: var(--size-2, 8px);
    border-right-width: 0px;
    border-left-width: 1px;
    border-bottom-width: 1px;
    border-style: solid;
    border-color: var(--border-color-primary, #e5e7eb);
    font-size: var(--text-sm, 12px);
  }
  td.first {
    border-left-width: 0;
  }
  tr {
    background: var(--table-even-background-fill, white);
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    text-align: left;
  }
  tr.row-odd {
    background: var(--table-odd-background-fill, var(--neutral-50, #f9fafb));
  }
  tr.selected {
    background: var(--color-accent-soft, var(--primary-50, #fff7ed));
  }
  tr:last-child td.first {
    border-bottom-left-radius: var(--table-radius, var(--radius-lg, 8px));
  }
  tr:last-child td.last {
    border-bottom-right-radius: var(--table-radius, var(--radius-lg, 8px));
  }
  .check-col {
    width: 40px;
    text-align: center;
    padding: var(--size-2, 8px);
    border-left-width: 0;
  }
  .check-col input[type="checkbox"] {
    appearance: none;
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    border: 1px solid var(--checkbox-border-color, #d1d5db);
    border-radius: var(--checkbox-border-radius, 4px);
    background-color: var(--checkbox-background-color, white);
    cursor: pointer;
    flex-shrink: 0;
    transition: background-color 0.15s, border-color 0.15s;
  }
  .check-col input[type="checkbox"]:checked {
    background-image: var(--checkbox-check);
    background-color: var(--checkbox-background-color-selected, #2563eb);
    border-color: var(--checkbox-border-color-selected, #2563eb);
  }
</style>
