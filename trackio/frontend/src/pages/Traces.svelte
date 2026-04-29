<script>
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getTraceStepCounts, getTraces } from "../lib/api.js";

  let {
    project = null,
    selectedRuns = [],
  } = $props();

  const DEFAULT_PAGE_SIZE = 16;
  const DEFAULT_VISIBLE_COLUMNS = [
    "index",
    "key",
    "step",
    "timestamp",
    "messages",
    "metadata",
  ];
  const COLUMN_DEFS = [
    { key: "id", label: "id" },
    { key: "key", label: "key" },
    { key: "index", label: "index" },
    { key: "run", label: "run" },
    { key: "run_id", label: "run_id" },
    { key: "step", label: "step", sortable: true },
    { key: "timestamp", label: "timestamp", sortable: true },
    { key: "messages", label: "messages" },
    { key: "metadata", label: "metadata" },
  ];

  let loading = $state(false);
  let search = $state(getQueryParam("q") || "");
  let sortBy = $state(getQueryParam("sort") || "request_time_desc");
  let page = $state(Math.max(0, parseInt(getQueryParam("page") || "0", 10) || 0));
  let activeRunId = $state(getQueryParam("run_id") || "");
  let expandedTraceId = $state(getQueryParam("row") || "");
  let selectedCellKey = $state(getQueryParam("cell") || "messages");
  let selectedStep = $state(getQueryParam("step") || "");
  let stepCounts = $state([]);
  let stepsLoading = $state(false);
  let visibleColumnKeys = $state(loadVisibleColumns());
  let showColumnPanel = $state(false);
  let traces = $state([]);
  let loadRequestId = 0;
  let stepsRequestId = 0;

  let visibleColumns = $derived.by(() =>
    COLUMN_DEFS.filter((column) => visibleColumnKeys.includes(column.key)),
  );

  let stepOptions = $derived(stepCounts.map((row) => row.step));

  function getQueryParam(key) {
    return new URLSearchParams(window.location.search).get(key);
  }

  function loadVisibleColumns() {
    const raw = getQueryParam("cols");
    if (!raw) return [...DEFAULT_VISIBLE_COLUMNS];
    const known = new Set(COLUMN_DEFS.map((column) => column.key));
    const columns = raw.split(",").filter((column) => known.has(column));
    return columns.length ? columns : [...DEFAULT_VISIBLE_COLUMNS];
  }

  function setQueryParams(values) {
    const params = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(values)) {
      if (value != null && value !== "") {
        params.set(key, value);
      } else {
        params.delete(key);
      }
    }
    const searchParams = params.toString();
    const url = searchParams ? `${window.location.pathname}?${searchParams}` : window.location.pathname;
    window.history.replaceState({}, "", url);
  }

  function runKey(run) {
    return run?.id ?? run?.name ?? "";
  }

  let activeRun = $derived.by(() => {
    if (!selectedRuns.length) return null;
    return selectedRuns.find((run) => runKey(run) === activeRunId) || selectedRuns[0];
  });

  function syncUrlState() {
    const defaultColumns = DEFAULT_VISIBLE_COLUMNS.join(",");
    const currentColumns = visibleColumnKeys.join(",");
    setQueryParams({
      run_id: activeRun ? runKey(activeRun) : "",
      q: search.trim(),
      sort: sortBy,
      page: page > 0 ? String(page) : "",
      row: expandedTraceId,
      cell: expandedTraceId && selectedCellKey ? selectedCellKey : "",
      step: selectedStep || "",
      cols: currentColumns === defaultColumns ? "" : currentColumns,
    });
  }

  function preview(value, limit = 220) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (text.length <= limit) return text || " ";
    return `${text.slice(0, limit - 3)}...`;
  }

  function jsonText(value) {
    if (value == null) return "";
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }

  function valueType(value) {
    if (value == null) return "null";
    if (Array.isArray(value)) return "list";
    return typeof value;
  }

  function cellText(value) {
    if (typeof value === "string") return value;
    if (value == null) return "";
    return jsonText(value);
  }

  function messageRole(message) {
    return String(message?.role || "message").toLowerCase();
  }

  function messageContent(message) {
    const content = message?.content;
    if (typeof content === "string") return content;
    if (content == null) return "";
    return jsonText(content);
  }

  function isMessagesColumn(column, value) {
    return column.key === "messages" && Array.isArray(value);
  }

  function columnValue(trace, key) {
    return trace?.[key];
  }

  function previewValue(value) {
    return preview(cellText(value));
  }

  function columnByKey(key) {
    return COLUMN_DEFS.find((column) => column.key === key);
  }

  function columnType(column) {
    for (const trace of traces) {
      const value = columnValue(trace, column.key);
      if (value != null) return valueType(value);
    }
    return "empty";
  }

  function selectedStepNumber() {
    if (selectedStep === "") return null;
    const step = Number(selectedStep);
    return Number.isFinite(step) ? step : null;
  }

  function selectedStepInfo() {
    const step = selectedStepNumber();
    if (step == null) return null;

    let offset = 0;
    for (const row of stepCounts) {
      if (row.step === step) {
        return { step, offset, count: row.count };
      }
      offset += row.count;
    }
    return null;
  }

  function minStep() {
    return stepOptions.length ? Math.min(...stepOptions) : 0;
  }

  function maxStep() {
    return stepOptions.length ? Math.max(...stepOptions) : 0;
  }

  function nearestStep(value) {
    if (!stepOptions.length) return "";
    const target = Number(value);
    if (!Number.isFinite(target)) return String(stepOptions[0]);
    return String(
      stepOptions.reduce((best, step) =>
        Math.abs(step - target) < Math.abs(best - target) ? step : best,
      ),
    );
  }

  function sliderStep() {
    return selectedStep || nearestStep(page + 1);
  }

  function selectedStepCount() {
    return selectedStepInfo()?.count ?? 0;
  }

  function formatRowNumber(index) {
    const info = selectedStepInfo();
    if (info) return info.offset + index + 1;
    return page * DEFAULT_PAGE_SIZE + index + 1;
  }

  function sortLabel() {
    switch (sortBy) {
      case "request_time_desc":
        return "timestamp desc";
      case "request_time_asc":
        return "timestamp asc";
      case "step_desc":
        return "step desc";
      case "step_asc":
        return "step asc";
      default:
        return sortBy;
    }
  }

  function headerSortState(column) {
    if (column.key === "step" && sortBy.startsWith("step_")) {
      return sortBy.endsWith("_asc") ? "asc" : "desc";
    }
    if (column.key === "timestamp" && sortBy.startsWith("request_time_")) {
      return sortBy.endsWith("_asc") ? "asc" : "desc";
    }
    return "";
  }

  function changeSortForColumn(column) {
    if (!column.sortable) return;
    if (column.key === "step") {
      sortBy = sortBy === "step_asc" ? "step_desc" : "step_asc";
    } else if (column.key === "timestamp") {
      sortBy = sortBy === "request_time_asc" ? "request_time_desc" : "request_time_asc";
    }
    page = 0;
    expandedTraceId = "";
    selectedStep = "";
    syncUrlState();
  }

  function countLabel() {
    const info = selectedStepInfo();
    const start = traces.length ? (info ? info.offset + 1 : page * DEFAULT_PAGE_SIZE + 1) : 0;
    const end = info ? info.offset + traces.length : page * DEFAULT_PAGE_SIZE + traces.length;
    const suffix = search.trim() ? ` matching "${search.trim()}"` : "";
    const stepSuffix = info ? ` in step ${info.step}` : "";
    return `Rows ${start}-${end}${stepSuffix}${suffix}`;
  }

  function normalizeTrace(trace, runLabel) {
    return {
      ...trace,
      run: trace.run || runLabel,
    };
  }

  async function loadStepCounts() {
    const requestId = ++stepsRequestId;
    if (!project || !activeRun) {
      stepCounts = [];
      selectedStep = "";
      return;
    }

    stepsLoading = true;
    try {
      const counts = await getTraceStepCounts(project, activeRun);
      if (requestId !== stepsRequestId) return;
      stepCounts = counts;
      const available = new Set(counts.map((row) => row.step));
      if (selectedStep && !available.has(Number(selectedStep))) {
        selectedStep = "";
      }
      syncUrlState();
    } catch (error) {
      if (requestId !== stepsRequestId) return;
      console.error("Failed to load trace steps:", error);
      stepCounts = [];
    } finally {
      if (requestId === stepsRequestId) {
        stepsLoading = false;
      }
    }
  }

  async function loadTraces(searchQuery, sort) {
    const requestId = ++loadRequestId;
    if (!project || !activeRun) {
      traces = [];
      expandedTraceId = "";
      return;
    }

    const stepInfo = selectedStepInfo();
    if (selectedStep && !stepInfo) {
      traces = [];
      return;
    }

    loading = true;
    try {
      const runTraces = await getTraces(project, activeRun, {
        search: searchQuery,
        sort: stepInfo ? "step_asc" : sort,
        limit: stepInfo ? stepInfo.count : DEFAULT_PAGE_SIZE,
        offset: stepInfo ? stepInfo.offset : page * DEFAULT_PAGE_SIZE,
      });
      if (requestId !== loadRequestId) return;
      traces = (Array.isArray(runTraces) ? runTraces : []).map((trace) =>
        normalizeTrace(trace, activeRun.name),
      );
      if (!traces.find((trace) => trace.id === expandedTraceId)) {
        expandedTraceId = "";
      }
      syncUrlState();
    } catch (error) {
      if (requestId !== loadRequestId) return;
      console.error("Failed to load traces:", error);
      traces = [];
    } finally {
      if (requestId === loadRequestId) {
        loading = false;
      }
    }
  }

  $effect(() => {
    if (!selectedRuns.find((run) => runKey(run) === activeRunId)) {
      activeRunId = selectedRuns.length ? runKey(selectedRuns[0]) : "";
      page = 0;
      expandedTraceId = "";
      selectedStep = "";
    }
  });

  $effect(() => {
    project;
    activeRunId;

    const timeout = setTimeout(() => {
      loadStepCounts();
    }, 0);

    return () => clearTimeout(timeout);
  });

  $effect(() => {
    project;
    selectedRuns;
    activeRunId;
    search;
    sortBy;
    page;
    selectedStep;
    stepCounts;

    const timeout = setTimeout(() => {
      loadTraces(search.trim(), sortBy);
    }, 150);

    return () => clearTimeout(timeout);
  });

  function changeRun(event) {
    activeRunId = event.target.value;
    page = 0;
    expandedTraceId = "";
    selectedStep = "";
    syncUrlState();
  }

  function resetAndSearch() {
    page = 0;
    expandedTraceId = "";
    selectedStep = "";
    syncUrlState();
  }

  function clearSearch() {
    search = "";
    resetAndSearch();
  }

  function changeSort(event) {
    sortBy = event.target.value;
    page = 0;
    expandedTraceId = "";
    selectedStep = "";
    syncUrlState();
  }

  function previousPage() {
    page = Math.max(0, page - 1);
    expandedTraceId = "";
    selectedStep = "";
    syncUrlState();
  }

  function nextPage() {
    page += 1;
    expandedTraceId = "";
    selectedStep = "";
    syncUrlState();
  }

  function jumpToPage(event) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const next = Math.max(1, parseInt(data.get("page") || "1", 10) || 1);
    page = next - 1;
    expandedTraceId = "";
    selectedStep = "";
    syncUrlState();
  }

  function changeStep(event) {
    selectedStep = nearestStep(event.target.value);
    page = 0;
    search = "";
    sortBy = "step_asc";
    expandedTraceId = "";
    selectedCellKey = "messages";
    syncUrlState();
  }

  function clearStep() {
    selectedStep = "";
    expandedTraceId = "";
    selectedCellKey = "messages";
    syncUrlState();
  }

  function toggleTrace(trace) {
    if (expandedTraceId === trace.id) {
      expandedTraceId = "";
      selectedCellKey = "";
    } else {
      expandedTraceId = trace.id;
      const column = columnByKey(selectedCellKey) || columnByKey("messages");
      selectedCellKey = column.key;
    }
    syncUrlState();
  }

  function handleRowKeydown(event, trace) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggleTrace(trace);
    }
  }

  function selectCell(event, trace, column) {
    event.stopPropagation();
    if (expandedTraceId === trace.id && selectedCellKey === column.key) {
      expandedTraceId = "";
      selectedCellKey = "";
      syncUrlState();
      return;
    }
    expandedTraceId = trace.id;
    selectedCellKey = column.key;
    syncUrlState();
  }

  function toggleColumn(key) {
    if (visibleColumnKeys.includes(key)) {
      if (visibleColumnKeys.length === 1) return;
      visibleColumnKeys = visibleColumnKeys.filter((column) => column !== key);
    } else {
      visibleColumnKeys = COLUMN_DEFS
        .map((column) => column.key)
        .filter((column) => column === key || visibleColumnKeys.includes(column));
    }
    syncUrlState();
  }

  function resetColumns() {
    visibleColumnKeys = [...DEFAULT_VISIBLE_COLUMNS];
    syncUrlState();
  }

  function showAllColumns() {
    visibleColumnKeys = COLUMN_DEFS.map((column) => column.key);
    syncUrlState();
  }

</script>

<div class="dataset-page">
  {#if !project}
    <div class="empty-state">
      <h2>Select a project</h2>
      <p>Pick a project to browse trace logs.</p>
    </div>
  {:else if selectedRuns.length === 0}
    <div class="empty-state">
      <h2>No runs selected</h2>
      <p>Select one or more runs in the sidebar to browse traces.</p>
    </div>
  {:else}
    <div class="viewer-header">
      <div>
        <div class="eyebrow">Trackio traces</div>
        <h2>{project}</h2>
      </div>
      <div class="header-stats">
        <span>{countLabel()}</span>
        <span>{visibleColumns.length} columns</span>
        <span>{DEFAULT_PAGE_SIZE} rows/page</span>
      </div>
    </div>

    <div class="control-panel">
      <label class="control">
        <span>Run</span>
        <select value={activeRun ? runKey(activeRun) : ""} onchange={changeRun}>
          {#each selectedRuns as run}
            <option value={runKey(run)}>{run.name || runKey(run)}</option>
          {/each}
        </select>
      </label>

      <form class="search-wrap" onsubmit={(event) => { event.preventDefault(); resetAndSearch(); }}>
        <label class="control">
          <span>Search</span>
          <input type="search" bind:value={search} placeholder="Search traces" />
        </label>
        <button type="submit">Search</button>
        <button type="button" onclick={clearSearch} disabled={!search.trim()}>Clear</button>
      </form>

      <label class="control">
        <span>Sort</span>
        <select value={sortBy} onchange={changeSort}>
          <option value="request_time_desc">timestamp desc</option>
          <option value="request_time_asc">timestamp asc</option>
          <option value="step_desc">step desc</option>
          <option value="step_asc">step asc</option>
        </select>
      </label>

      <div class="columns-control">
        <button type="button" onclick={() => showColumnPanel = !showColumnPanel}>
          Columns
        </button>
        {#if showColumnPanel}
          <div class="columns-popover">
            <div class="columns-actions">
              <button type="button" onclick={showAllColumns}>All</button>
              <button type="button" onclick={resetColumns}>Default</button>
            </div>
            {#each COLUMN_DEFS as column}
              <label>
                <input
                  type="checkbox"
                  checked={visibleColumnKeys.includes(column.key)}
                  onchange={() => toggleColumn(column.key)}
                />
                <span>{column.label}</span>
                <em>{columnType(column)}</em>
              </label>
            {/each}
          </div>
        {/if}
      </div>
    </div>

    {#if stepOptions.length}
      <div class="step-panel">
        <label class="step-control">
          <span>Step</span>
          <input
            type="range"
            min={minStep()}
            max={maxStep()}
            step="1"
            value={sliderStep()}
            disabled={stepsLoading}
            oninput={changeStep}
          />
        </label>
        <output>
          {#if selectedStep}
            step {selectedStep} · {selectedStepCount()} traces
          {:else}
            all steps
          {/if}
        </output>
        <button type="button" onclick={clearStep} disabled={!selectedStep}>All steps</button>
      </div>
    {/if}

    <div class="table-meta">
      <div>
        {loading ? "Loading traces." : countLabel()}
        <span class="muted">Sorted by {sortLabel()}</span>
      </div>
      <div class="pager">
        <button type="button" onclick={previousPage} disabled={loading || page === 0}>Previous</button>
        <form class="jump-form" onsubmit={jumpToPage}>
          <span>Page</span>
          <input name="page" type="number" min="1" value={page + 1} />
          <button type="submit">Go</button>
        </form>
        <button type="button" onclick={nextPage} disabled={loading || traces.length < DEFAULT_PAGE_SIZE}>Next</button>
      </div>
    </div>

    {#if loading}
      <LoadingTrackio />
    {:else if traces.length === 0}
      <div class="empty-state">
        <h2>No traces match the current filters</h2>
        <p>Try a different search query, run, or sort order.</p>
      </div>
    {:else}
      <div class="dataset-table-wrap">
        <table class="dataset-table">
          <thead>
            <tr>
              <th class="row-number-col">#</th>
              {#each visibleColumns as column}
                <th class:sortable={column.sortable}>
                  <button
                    type="button"
                    class="header-button"
                    disabled={!column.sortable}
                    onclick={() => changeSortForColumn(column)}
                  >
                    <span>{column.label}</span>
                    <small>{columnType(column)}</small>
                    {#if headerSortState(column)}
                      <b>{headerSortState(column)}</b>
                    {/if}
                  </button>
                </th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each traces as trace, index}
              <tr
                class:selected={expandedTraceId === trace.id}
                role="button"
                tabindex="0"
                aria-expanded={expandedTraceId === trace.id}
                onclick={() => toggleTrace(trace)}
                onkeydown={(event) => handleRowKeydown(event, trace)}
              >
                <td class="row-number-col">
                  <button
                    type="button"
                    class="row-button"
                    onclick={(event) => {
                      event.stopPropagation();
                      toggleTrace(trace);
                    }}
                  >
                    {formatRowNumber(index)}
                  </button>
                </td>
                {#each visibleColumns as column}
                  {@const value = columnValue(trace, column.key)}
                  {@const cellExpanded = expandedTraceId === trace.id && selectedCellKey === column.key}
                  <td data-type={valueType(value)}>
                    <button
                      type="button"
                      class="cell-button"
                      class:expanded={cellExpanded}
                      aria-expanded={cellExpanded}
                      onclick={(event) => selectCell(event, trace, column)}
                    >
                      {#if cellExpanded}
                        {#if isMessagesColumn(column, value)}
                          <span class="conversation-view">
                            {#each value as message}
                              <span class="chat-message" data-role={messageRole(message)}>
                                <span class="chat-role">{messageRole(message)}</span>
                                <span class="chat-content">{messageContent(message)}</span>
                              </span>
                            {/each}
                          </span>
                        {:else}
                          <span class="cell-expanded-text">{jsonText(value)}</span>
                        {/if}
                      {:else}
                        {previewValue(value)}
                      {/if}
                    </button>
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/if}
</div>

<style>
  .dataset-page {
    padding: 18px 20px;
    overflow-y: auto;
    flex: 1;
    background: var(--background-fill-primary, white);
  }
  .viewer-header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 14px;
  }
  .eyebrow {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
  }
  .viewer-header h2 {
    margin: 3px 0 0;
    color: var(--body-text-color, #1f2937);
    font-size: 18px;
    line-height: 1.2;
  }
  .header-stats {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
  }
  .header-stats span,
  .muted {
    color: var(--body-text-color-subdued, #6b7280);
  }
  .header-stats span {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-sm, 4px);
    padding: 4px 8px;
    font-size: 12px;
  }
  .control-panel {
    display: grid;
    grid-template-columns: minmax(220px, 320px) minmax(360px, 1fr) minmax(160px, 220px) auto;
    align-items: end;
    gap: 10px;
    margin-bottom: 12px;
  }
  .control {
    display: grid;
    gap: 5px;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 12px;
    font-weight: 600;
  }
  .control span {
    text-transform: uppercase;
  }
  .control input,
  .control select,
  .jump-form input {
    width: 100%;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-sm, 4px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
    font: inherit;
    font-size: 13px;
    padding: 8px 10px;
  }
  .search-wrap {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    align-items: end;
    gap: 8px;
  }
  .step-panel {
    display: grid;
    grid-template-columns: minmax(260px, 1fr) auto auto;
    align-items: center;
    gap: 12px;
    margin: -2px 0 12px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    padding: 10px 12px;
  }
  .step-control {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: 12px;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
  }
  .step-control input {
    width: 100%;
    accent-color: var(--color-accent, #ff7c00);
  }
  .step-panel output {
    min-width: 150px;
    color: var(--body-text-color, #1f2937);
    font-size: 13px;
    text-align: right;
  }
  button {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-sm, 4px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
    font: inherit;
    font-size: 13px;
    padding: 8px 10px;
    cursor: pointer;
  }
  button:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }
  .columns-control {
    position: relative;
  }
  .columns-popover {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    z-index: 10;
    width: 260px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, white);
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.12);
    padding: 8px;
  }
  .columns-popover label,
  .columns-actions {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 8px;
  }
  .columns-actions {
    grid-template-columns: 1fr 1fr;
    margin-bottom: 8px;
  }
  .columns-popover label {
    padding: 6px 4px;
    color: var(--body-text-color, #1f2937);
    font-size: 13px;
  }
  .columns-popover em {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 12px;
    font-style: normal;
  }
  .table-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 10px;
    color: var(--body-text-color, #1f2937);
    font-size: 13px;
  }
  .table-meta .muted {
    margin-left: 8px;
  }
  .pager,
  .jump-form {
    display: flex;
    align-items: center;
    gap: 8px;
    white-space: nowrap;
  }
  .jump-form input {
    width: 76px;
    padding: 7px 8px;
  }
  .dataset-table-wrap {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    overflow: auto;
    max-height: calc(100vh - 250px);
  }
  .dataset-table {
    width: 100%;
    min-width: 1120px;
    border-collapse: separate;
    border-spacing: 0;
    table-layout: fixed;
    font-size: 12px;
  }
  .dataset-table th,
  .dataset-table td {
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    border-right: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color, #1f2937);
    vertical-align: top;
  }
  .dataset-table th {
    position: sticky;
    top: 0;
    z-index: 2;
    background: var(--background-fill-primary, white);
    padding: 0;
  }
  .row-number-col {
    position: sticky;
    left: 0;
    z-index: 3;
    width: 64px;
    background: var(--background-fill-primary, white);
    text-align: right;
  }
  th.row-number-col {
    padding: 12px 10px;
    color: var(--body-text-color-subdued, #6b7280);
    font-weight: 600;
  }
  .dataset-table tr.selected td {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .dataset-table tbody tr[role="button"] {
    cursor: pointer;
  }
  .dataset-table tbody tr[role="button"]:hover td {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .header-button {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 2px 8px;
    width: 100%;
    border: 0;
    border-radius: 0;
    padding: 9px 10px;
    text-align: left;
  }
  .header-button span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 700;
  }
  .header-button small,
  .header-button b {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 11px;
    font-weight: 500;
  }
  .header-button b {
    justify-self: end;
  }
  .cell-button,
  .row-button {
    width: 100%;
    min-height: 42px;
    border: 0;
    border-radius: 0;
    background: transparent;
    padding: 8px 10px;
    text-align: left;
  }
  .row-button {
    text-align: right;
    color: var(--body-text-color-subdued, #6b7280);
    font-variant-numeric: tabular-nums;
  }
  .cell-button {
    display: block;
    overflow: hidden;
    color: inherit;
    line-height: 1.45;
    text-overflow: ellipsis;
  }
  .cell-button.expanded {
    max-height: 420px;
    overflow: auto;
    background: var(--background-fill-secondary, #f9fafb);
  }
  .cell-expanded-text {
    display: block;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace);
  }
  .conversation-view {
    display: flex;
    flex-direction: column;
    gap: 10px;
    font-family: inherit;
  }
  .chat-message {
    display: grid;
    gap: 5px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, white);
    padding: 10px;
  }
  .chat-message[data-role="user"] {
    border-left: 3px solid #2563eb;
  }
  .chat-message[data-role="assistant"] {
    border-left: 3px solid #16a34a;
  }
  .chat-message[data-role="system"] {
    border-left: 3px solid #9333ea;
  }
  .chat-role {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
  }
  .chat-content {
    display: block;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--body-text-color, #1f2937);
    font-family: inherit;
    line-height: 1.5;
  }
  .cell-button:hover,
  .row-button:hover,
  .header-button:hover:not(:disabled) {
    background: var(--background-fill-secondary, #f9fafb);
  }
  td[data-type="number"] .cell-button {
    font-variant-numeric: tabular-nums;
  }
  td[data-type="object"] .cell-button,
  td[data-type="list"] .cell-button {
    font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace);
    color: var(--body-text-color-subdued, #4b5563);
  }
  .empty-state {
    max-width: 640px;
    padding: 40px 24px;
    color: var(--body-text-color, #1f2937);
  }
  .empty-state h2 {
    margin: 0 0 8px;
    font-size: 20px;
    font-weight: 700;
  }
  .empty-state p {
    margin: 12px 0 8px;
    color: var(--body-text-color-subdued, #6b7280);
  }
  @media (max-width: 1200px) {
    .viewer-header,
    .table-meta {
      align-items: flex-start;
      flex-direction: column;
    }
    .control-panel {
      grid-template-columns: 1fr;
    }
    .step-panel {
      grid-template-columns: 1fr;
    }
    .step-panel output {
      text-align: left;
    }
    .search-wrap {
      grid-template-columns: 1fr auto auto;
    }
  }
</style>
