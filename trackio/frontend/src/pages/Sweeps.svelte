<script>
  import { onMount } from "svelte";
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import ParallelCoordinatesPlot from "../components/ParallelCoordinatesPlot.svelte";
  import OptimizationHistoryPlot from "../components/OptimizationHistoryPlot.svelte";
  import {
    getSweeps,
    getSweepTrials,
    setSweepState,
    getRunsForProject,
  } from "../lib/api.js";
  import { openRunDetail, getQueryParam, setQueryParam } from "../lib/router.js";
  import {
    formatCompactNumber,
    formatDate,
    formatRelativeTime,
    formatDuration,
  } from "../lib/format.js";
  import {
    sweepTotalTrials,
    sweepParamSpecs,
    trialParamKeys,
    flattenTrialParams,
  } from "../lib/sweeps.js";
  import { getMetricsPollIntervalMs, isTabHidden } from "../lib/hostPolling.js";

  let { project = null, runMutationAllowed = true } = $props();

  let sweeps = $state([]);
  let loading = $state(false);
  let expandedSweepIds = $state(
    (getQueryParam("selected_sweep") || "").split(",").filter(Boolean),
  );
  let trialsBySweep = $state({});
  let runNamesById = $state({});
  let actionPending = $state(null);
  let actionError = $state(null);
  let confirmKey = $state(null);
  let copiedSweepId = $state(null);
  let trialSorts = $state({});
  let now = $state(Date.now());
  let loadSeq = 0;
  let confirmTimer = null;
  let copiedTimer = null;
  let lastProject = null;

  const TERMINAL_STATES = new Set(["finished", "stopped", "cancelled"]);
  const TRIAL_TERMINAL_STATES = new Set(["finished", "failed", "pruned"]);
  const TRIAL_STATE_ORDER = [
    "running",
    "assigned",
    "finished",
    "failed",
    "pruned",
  ];

  async function loadSweeps(silent = false) {
    const seq = ++loadSeq;
    if (!project) {
      sweeps = [];
      loading = false;
      return;
    }
    if (!silent) loading = true;
    try {
      const [sweepList, runRecords] = await Promise.all([
        getSweeps(project),
        getRunsForProject(project).catch(() => []),
      ]);
      if (seq !== loadSeq) return;
      sweeps = sweepList || [];
      const names = {};
      for (const record of runRecords || []) {
        if (record && record.id != null) names[record.id] = record.name;
      }
      runNamesById = names;
      for (const sweepId of expandedSweepIds) {
        if (
          !trialsBySweep[sweepId] &&
          sweeps.some((s) => s.sweep_id === sweepId)
        ) {
          loadTrials(sweepId);
        }
      }
    } catch (e) {
      if (seq !== loadSeq) return;
      console.error("Failed to load sweeps:", e);
      if (!silent) sweeps = [];
    } finally {
      if (seq === loadSeq && !silent) loading = false;
    }
  }

  async function loadTrials(sweepId) {
    try {
      const trials = ((await getSweepTrials(project, sweepId)) || []).map(
        (trial) => ({ ...trial, params: flattenTrialParams(trial.params) }),
      );
      const previous = trialsBySweep[sweepId];
      if (previous && JSON.stringify(previous) === JSON.stringify(trials)) {
        return;
      }
      trialsBySweep = { ...trialsBySweep, [sweepId]: trials };
    } catch (e) {
      console.error("Failed to load sweep trials:", e);
      trialsBySweep = { ...trialsBySweep, [sweepId]: [] };
    }
  }

  async function toggleTrials(sweepId) {
    if (expandedSweepIds.includes(sweepId)) {
      expandedSweepIds = expandedSweepIds.filter((id) => id !== sweepId);
      setQueryParam("selected_sweep", expandedSweepIds.join(",") || null);
      return;
    }
    expandedSweepIds = [...expandedSweepIds, sweepId];
    const rest = { ...trialSorts };
    delete rest[sweepId];
    trialSorts = rest;
    setQueryParam("selected_sweep", expandedSweepIds.join(","));
    if (!trialsBySweep[sweepId]) {
      await loadTrials(sweepId);
    }
  }

  function handleRowClick(event, sweepId) {
    if (event.target.closest("button, a")) return;
    toggleTrials(sweepId);
  }

  async function applyState(sweepId, state) {
    actionPending = `${sweepId}:${state}`;
    actionError = null;
    try {
      await setSweepState(project, sweepId, state);
    } catch (e) {
      console.error(`Failed to set sweep ${sweepId} to ${state}:`, e);
      actionError = `Could not set sweep ${sweepId} to ${state} — it may have already finished or changed state. The list has been refreshed.`;
    } finally {
      const rest = { ...trialsBySweep };
      delete rest[sweepId];
      trialsBySweep = rest;
      await loadSweeps(true);
      for (const id of expandedSweepIds) {
        if (!trialsBySweep[id]) {
          await loadTrials(id);
        }
      }
      actionPending = null;
    }
  }

  function requestDestructive(sweepId, state) {
    const key = `${sweepId}:${state}`;
    if (confirmKey === key) {
      clearTimeout(confirmTimer);
      confirmKey = null;
      applyState(sweepId, state);
      return;
    }
    confirmKey = key;
    clearTimeout(confirmTimer);
    confirmTimer = setTimeout(() => {
      confirmKey = null;
    }, 4000);
  }

  async function copySweepId(sweepId) {
    try {
      await navigator.clipboard.writeText(sweepId);
      copiedSweepId = sweepId;
      clearTimeout(copiedTimer);
      copiedTimer = setTimeout(() => {
        copiedSweepId = null;
      }, 1500);
    } catch (e) {
      console.error("Failed to copy sweep ID:", e);
    }
  }

  function bestRunName(sweep) {
    if (!sweep.best_run_id) return null;
    return runNamesById[sweep.best_run_id] ?? null;
  }

  function stateChips(sweep) {
    const counts = sweep.trial_counts || {};
    const chips = [];
    for (const state of TRIAL_STATE_ORDER) {
      if (state === "finished") continue;
      if (counts[state]) chips.push({ state, count: counts[state] });
    }
    for (const [state, count] of Object.entries(counts)) {
      if (!TRIAL_STATE_ORDER.includes(state) && count) {
        chips.push({ state, count });
      }
    }
    return chips;
  }

  function terminalTrialCount(sweep) {
    const counts = sweep.trial_counts || {};
    let total = 0;
    for (const state of TRIAL_TERMINAL_STATES) total += counts[state] || 0;
    return total;
  }

  function trialDurationMs(trial, nowMs) {
    if (!trial?.created_at) return null;
    const start = new Date(trial.created_at).getTime();
    if (Number.isNaN(start)) return null;
    if (trial.state === "assigned") return null;
    if (TRIAL_TERMINAL_STATES.has(trial.state)) {
      const end = new Date(trial.updated_at ?? "").getTime();
      if (Number.isNaN(end)) return null;
      return end - start;
    }
    return nowMs - start;
  }

  function formatParamValue(value) {
    if (value == null) return "—";
    if (typeof value === "number") return formatCompactNumber(value);
    if (typeof value === "string") return value;
    return JSON.stringify(value);
  }

  function defaultSort(sweep) {
    if (sweep.metric_name) {
      return {
        key: "metric",
        dir: sweep.metric_goal === "maximize" ? "desc" : "asc",
      };
    }
    return { key: "trial", dir: "asc" };
  }

  function toggleSort(key, sweep) {
    const active = trialSorts[sweep.sweep_id] ?? defaultSort(sweep);
    const next =
      active.key === key
        ? { key, dir: active.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" };
    trialSorts = { ...trialSorts, [sweep.sweep_id]: next };
  }

  function sortIndicator(key, sweep) {
    const active = trialSorts[sweep.sweep_id] ?? defaultSort(sweep);
    if (active.key !== key) return "";
    return active.dir === "asc" ? " ▲" : " ▼";
  }

  function trialSortValue(trial, key, nowMs) {
    if (key === "trial") return trial.trial_id;
    if (key === "state") return trial.state ?? "";
    if (key === "metric") return trial.metric_value;
    if (key === "duration") return trialDurationMs(trial, nowMs);
    if (key.startsWith("param:")) return trial.params?.[key.slice(6)];
    return null;
  }

  function sortedTrials(sweep, nowMs) {
    const trials = trialsBySweep[sweep.sweep_id] || [];
    const { key, dir } = trialSorts[sweep.sweep_id] ?? defaultSort(sweep);
    return [...trials].sort((a, b) => {
      const av = trialSortValue(a, key, nowMs);
      const bv = trialSortValue(b, key, nowMs);
      if (av == null && bv == null) return a.trial_id - b.trial_id;
      if (av == null) return 1;
      if (bv == null) return -1;
      let cmp;
      if (typeof av === "number" && typeof bv === "number") cmp = av - bv;
      else cmp = String(av).localeCompare(String(bv));
      if (dir === "desc") cmp = -cmp;
      if (cmp === 0) cmp = a.trial_id - b.trial_id;
      return cmp;
    });
  }

  function openTrialRun(trial) {
    const name = runNamesById[trial.run_id];
    if (trial.run_id && name) {
      openRunDetail(name, trial.run_id);
    }
  }

  async function pollTick() {
    now = Date.now();
    if (isTabHidden() || !project || actionPending !== null) return;
    await loadSweeps(true);
    for (const sweepId of expandedSweepIds) {
      const sweep = sweeps.find((s) => s.sweep_id === sweepId);
      const trials = trialsBySweep[sweepId] || [];
      const trialsActive = trials.some(
        (t) => !TRIAL_TERMINAL_STATES.has(t.state),
      );
      if ((sweep && !TERMINAL_STATES.has(sweep.state)) || trialsActive) {
        await loadTrials(sweepId);
      }
    }
  }

  $effect(() => {
    if (!project) return;
    const changed = lastProject !== null && lastProject !== project;
    lastProject = project;
    if (changed) {
      expandedSweepIds = [];
      setQueryParam("selected_sweep", null);
      trialsBySweep = {};
      trialSorts = {};
      confirmKey = null;
      sweeps = [];
    }
    loadSweeps();
  });

  onMount(() => {
    const timer = setInterval(pollTick, getMetricsPollIntervalMs());
    return () => {
      clearInterval(timer);
      clearTimeout(confirmTimer);
      clearTimeout(copiedTimer);
    };
  });
</script>

<div class="sweeps-page">
  {#if loading && sweeps.length === 0}
    <LoadingTrackio />
  {:else if sweeps.length === 0}
    <div class="empty-state">
      <h2>No sweeps in this project</h2>
      <p>
        Sweeps run your training function across a hyperparameter search
        space. Example:
      </p>
      <pre><code
          >{'import trackio\n\nsweep_id = trackio.sweep(\n    {\n        "method": "grid",\n        "metric": {"name": "loss", "goal": "minimize"},\n        "parameters": {"lr": {"values": [0.1, 0.01, 0.001]}},\n    },\n    project="my-project",\n)\n\ndef train():\n    run = trackio.init(project="my-project")\n    trackio.log({"loss": run.config["lr"]})\n    trackio.finish()\n\ntrackio.agent(sweep_id, function=train)'}</code
        ></pre>
    </div>
  {:else}
    {#if actionError}
      <div class="action-error">
        <span>{actionError}</span>
        <button
          class="dismiss-btn"
          aria-label="Dismiss error"
          onclick={() => (actionError = null)}>✕</button
        >
      </div>
    {/if}
    <table class="sweeps-table">
      <thead>
        <tr>
          <th>Sweep</th>
          <th>Method</th>
          <th>State</th>
          <th>Trials</th>
          <th>Metric</th>
          <th>Best</th>
          <th>Best Run</th>
          <th>Updated</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {#each sweeps as sweep (sweep.sweep_id)}
          {@const totalTrials = sweepTotalTrials(sweep.config)}
          {@const doneTrials = terminalTrialCount(sweep)}
          {@const finishedTrials = sweep.trial_counts?.finished ?? 0}
          {@const trialDenominator = totalTrials ?? sweep.num_trials}
          <tr
            class="sweep-row"
            class:expanded={expandedSweepIds.includes(sweep.sweep_id)}
            onclick={(event) => handleRowClick(event, sweep.sweep_id)}
          >
            <td class="sweep-id-cell">
              <button
                class="link-btn"
                aria-expanded={expandedSweepIds.includes(sweep.sweep_id)}
                title={sweep.name ? sweep.sweep_id : undefined}
                onclick={() => toggleTrials(sweep.sweep_id)}
              >
                <span class="expand-caret"
                  >{expandedSweepIds.includes(sweep.sweep_id)
                    ? "▾"
                    : "▸"}</span
                >
                {sweep.name || sweep.sweep_id}
              </button>
            </td>
            <td>{sweep.method}</td>
            <td>
              <span
                class="state-badge state-{sweep.state}"
                title={sweep.finish_reason
                  ? `Finished: ${sweep.finish_reason}`
                  : undefined}
                >{sweep.state}{sweep.finish_reason
                  ? ` (${sweep.finish_reason})`
                  : ""}</span
              >
            </td>
            <td class="trials-cell">
              <div class="trials-count">
                {finishedTrials} / {totalTrials ?? sweep.num_trials} finished
              </div>
              {#if trialDenominator > 0}
                <div
                  class="progress-track"
                  title="{doneTrials} of {trialDenominator} trials completed"
                >
                  <div
                    class="progress-fill progress-started"
                    style="width: {Math.min(
                      100,
                      (sweep.num_trials / trialDenominator) * 100,
                    )}%"
                  ></div>
                  <div
                    class="progress-fill progress-done"
                    style="width: {Math.min(
                      100,
                      (doneTrials / trialDenominator) * 100,
                    )}%"
                  ></div>
                </div>
              {/if}
              {#if stateChips(sweep).length > 0}
                <div class="state-chips">
                  {#each stateChips(sweep) as chip (chip.state)}
                    <span class="chip trial-{chip.state}"
                      >{chip.count} {chip.state}</span
                    >
                  {/each}
                </div>
              {/if}
            </td>
            <td>
              {#if sweep.metric_name}
                {sweep.metric_name}
                <span class="metric-goal">({sweep.metric_goal})</span>
              {:else}
                —
              {/if}
            </td>
            <td>{formatCompactNumber(sweep.best_metric_value)}</td>
            <td>
              {#if bestRunName(sweep)}
                <button
                  class="link-btn"
                  onclick={() =>
                    openRunDetail(bestRunName(sweep), sweep.best_run_id)}
                >
                  {bestRunName(sweep)}
                </button>
              {:else}
                —
              {/if}
            </td>
            <td
              class="created-cell"
              title={`Created ${formatDate(sweep.created_at)}\nUpdated ${formatDate(sweep.updated_at)}`}
            >
              {formatRelativeTime(sweep.updated_at, now)}
            </td>
            <td class="actions-cell">
              {#if !TERMINAL_STATES.has(sweep.state)}
                {#if sweep.state === "running"}
                  <button
                    class="action-btn"
                    title="Pause the sweep: agents stop starting new trials until resumed"
                    disabled={!runMutationAllowed || actionPending !== null}
                    onclick={() => applyState(sweep.sweep_id, "paused")}
                    >Pause</button
                  >
                {:else if sweep.state === "paused"}
                  <button
                    class="action-btn"
                    title="Resume the sweep: agents continue starting new trials"
                    disabled={!runMutationAllowed || actionPending !== null}
                    onclick={() => applyState(sweep.sweep_id, "running")}
                    >Resume</button
                  >
                {/if}
                <button
                  class="action-btn"
                  class:confirm-btn={confirmKey === `${sweep.sweep_id}:stopped`}
                  title="Stop the sweep: running trials finish, no new trials are scheduled"
                  disabled={!runMutationAllowed || actionPending !== null}
                  onclick={() => requestDestructive(sweep.sweep_id, "stopped")}
                  >{confirmKey === `${sweep.sweep_id}:stopped`
                    ? "Confirm stop"
                    : "Stop"}</button
                >
                <button
                  class="action-btn delete-btn"
                  class:confirm-btn={confirmKey ===
                    `${sweep.sweep_id}:cancelled`}
                  title="Cancel the sweep: abandon it immediately"
                  disabled={!runMutationAllowed || actionPending !== null}
                  onclick={() =>
                    requestDestructive(sweep.sweep_id, "cancelled")}
                  >{confirmKey === `${sweep.sweep_id}:cancelled`
                    ? "Confirm cancel"
                    : "Cancel"}</button
                >
              {:else}
                <span class="art-none">—</span>
              {/if}
            </td>
          </tr>
          {#if expandedSweepIds.includes(sweep.sweep_id)}
            <tr class="trials-row">
              <td colspan="9">
                <div class="sweep-detail">
                  <div class="sweep-detail-title">
                    {sweep.name || sweep.sweep_id}
                  </div>
                  <div class="sweep-meta">
                    <div class="meta-item">
                      <span class="meta-label">Sweep ID</span>
                      <code class="sweep-id">{sweep.sweep_id}</code>
                      <button
                        class="copy-btn"
                        title="Copy sweep ID"
                        onclick={() => copySweepId(sweep.sweep_id)}
                        >{copiedSweepId === sweep.sweep_id
                          ? "Copied!"
                          : "Copy"}</button
                      >
                    </div>
                    <div class="meta-item">
                      <span class="meta-label">Created</span>
                      {formatDate(sweep.created_at)}
                    </div>
                    <div class="meta-item">
                      <span class="meta-label">Updated</span>
                      {formatRelativeTime(sweep.updated_at, now)}
                    </div>
                    {#if sweep.config?.run_cap}
                      <div class="meta-item">
                        <span class="meta-label">Run cap</span>
                        {sweep.config.run_cap}
                      </div>
                    {/if}
                  </div>
                  {#if sweepParamSpecs(sweep.config).length > 0}
                    <div class="search-space">
                      <span class="meta-label">Search space</span>
                      <div class="search-space-grid">
                        {#each sweepParamSpecs(sweep.config) as param (param.path)}
                          <span class="param-name">{param.path}</span>
                          <span class="param-spec">{param.description}</span>
                        {/each}
                      </div>
                    </div>
                  {/if}
                </div>
                {#if !trialsBySweep[sweep.sweep_id]}
                  <div class="trials-loading">Loading trials…</div>
                {:else if trialsBySweep[sweep.sweep_id].length === 0}
                  <div class="trials-loading">No trials yet.</div>
                {:else}
                  {@const trials = sortedTrials(sweep, now)}
                  {@const paramColumns = trialParamKeys(trials)}
                  <div class="trials-plots">
                    <ParallelCoordinatesPlot
                      trials={trialsBySweep[sweep.sweep_id]}
                      metricName={sweep.metric_name}
                      metricGoal={sweep.metric_goal}
                      bestRunId={sweep.best_run_id}
                    />
                    <OptimizationHistoryPlot
                      trials={trialsBySweep[sweep.sweep_id]}
                      metricName={sweep.metric_name}
                      metricGoal={sweep.metric_goal}
                      bestRunId={sweep.best_run_id}
                    />
                  </div>
                  <div class="trials-table-wrap">
                    <table class="trials-table">
                      <thead>
                        <tr>
                          <th>
                            <button
                              class="sort-btn"
                              onclick={() => toggleSort("trial", sweep)}
                              >#{sortIndicator("trial", sweep)}</button
                            >
                          </th>
                          <th>
                            <button
                              class="sort-btn"
                              onclick={() => toggleSort("state", sweep)}
                              >State{sortIndicator("state", sweep)}</button
                            >
                          </th>
                          <th>
                            <button
                              class="sort-btn"
                              onclick={() => toggleSort("metric", sweep)}
                              >{sweep.metric_name || "Metric"}{sortIndicator(
                                "metric",
                                sweep,
                              )}</button
                            >
                          </th>
                          <th>
                            <button
                              class="sort-btn"
                              onclick={() => toggleSort("duration", sweep)}
                              >Duration{sortIndicator(
                                "duration",
                                sweep,
                              )}</button
                            >
                          </th>
                          <th>Run</th>
                          {#each paramColumns as key (key)}
                            <th>
                              <button
                                class="sort-btn param-header"
                                onclick={() =>
                                  toggleSort(`param:${key}`, sweep)}
                                >{key}{sortIndicator(
                                  `param:${key}`,
                                  sweep,
                                )}</button
                              >
                            </th>
                          {/each}
                        </tr>
                      </thead>
                      <tbody>
                        {#each trials as trial (trial.trial_id)}
                          {@const isBest =
                            sweep.best_run_id != null &&
                            trial.run_id === sweep.best_run_id}
                          {@const hasRun =
                            trial.run_id != null &&
                            runNamesById[trial.run_id] != null}
                          <tr
                            class:best-trial={isBest}
                            class:clickable-row={hasRun}
                            onclick={() => openTrialRun(trial)}
                          >
                            <td>
                              {trial.trial_id}{#if isBest}<span
                                  class="best-badge"
                                  title="Best trial">★ best</span
                                >{/if}
                            </td>
                            <td>
                              <span class="state-badge trial-{trial.state}"
                                >{trial.state}</span
                              >
                            </td>
                            <td>{formatCompactNumber(trial.metric_value)}</td>
                            <td>{formatDuration(trialDurationMs(trial, now))}</td>
                            <td>
                              {#if hasRun}
                                <button
                                  class="link-btn"
                                  onclick={() =>
                                    openRunDetail(
                                      runNamesById[trial.run_id],
                                      trial.run_id,
                                    )}
                                >
                                  {runNamesById[trial.run_id]}
                                </button>
                              {:else}
                                —
                              {/if}
                            </td>
                            {#each paramColumns as key (key)}
                              <td class="params-cell"
                                >{formatParamValue(trial.params?.[key])}</td
                              >
                            {/each}
                          </tr>
                        {/each}
                      </tbody>
                    </table>
                  </div>
                {/if}
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
  {/if}
</div>

<style>
  .sweeps-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
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
  .empty-state pre {
    background: var(--background-fill-secondary, #f3f4f6);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: 6px;
    padding: 12px;
    overflow-x: auto;
    font-size: 13px;
  }
  .sweeps-table,
  .trials-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }
  .sweeps-table th,
  .trials-table th {
    text-align: left;
    padding: 8px 12px;
    border-bottom: 2px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    font-weight: 600;
    white-space: nowrap;
  }
  .sweeps-table td,
  .trials-table td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color, #1f2937);
  }
  .sweep-id-cell {
    white-space: nowrap;
  }
  .sweep-row {
    cursor: pointer;
  }
  .sweep-row:hover td {
    background: rgba(127, 127, 127, 0.12);
  }
  .sweep-row.expanded td {
    background: var(--background-fill-secondary, #f9fafb);
    border-bottom: none;
  }
  .sweep-row.expanded:hover td {
    background: rgba(127, 127, 127, 0.12);
  }
  .expand-caret {
    display: inline-block;
    width: 12px;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .link-btn {
    background: none;
    border: none;
    padding: 0;
    color: var(--link-text-color, #2563eb);
    cursor: pointer;
    font-size: inherit;
    text-align: left;
  }
  .link-btn:hover {
    text-decoration: underline;
  }
  .state-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    background: var(--background-fill-secondary, #f3f4f6);
  }
  .state-running,
  .trial-running {
    color: #15803d;
    background: #dcfce7;
  }
  .state-paused {
    color: #a16207;
    background: #fef9c3;
  }
  .state-finished,
  .trial-finished {
    color: #1d4ed8;
    background: #dbeafe;
  }
  .state-stopped,
  .state-cancelled,
  .trial-failed,
  .trial-pruned {
    color: #b91c1c;
    background: #fee2e2;
  }
  .trial-assigned {
    color: #6b7280;
    background: #f3f4f6;
  }
  .metric-goal {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 12px;
  }
  .trials-cell {
    min-width: 140px;
  }
  .trials-count {
    font-variant-numeric: tabular-nums;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 12px;
  }
  .progress-track {
    position: relative;
    margin-top: 4px;
    height: 5px;
    width: 100%;
    border-radius: 999px;
    background: var(--border-color-primary, #e5e7eb);
    overflow: hidden;
  }
  .progress-fill {
    position: absolute;
    top: 0;
    left: 0;
    height: 100%;
    border-radius: 999px;
  }
  .progress-started {
    background: #93c5fd;
  }
  .progress-done {
    background: #2563eb;
  }
  .state-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 6px;
  }
  .chip {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    background: var(--background-fill-secondary, #f3f4f6);
    color: var(--body-text-color-subdued, #6b7280);
    white-space: nowrap;
  }
  .created-cell {
    white-space: nowrap;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 13px;
  }
  .actions-cell {
    white-space: nowrap;
  }
  .action-btn {
    padding: 4px 10px;
    margin-right: 6px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: 6px;
    background: var(--background-fill-primary, #fff);
    color: var(--body-text-color, #1f2937);
    cursor: pointer;
    font-size: 12px;
  }
  .action-btn:hover:not(:disabled) {
    background: var(--background-fill-secondary, #f3f4f6);
  }
  .action-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .delete-btn:hover:not(:disabled) {
    color: #b91c1c;
    border-color: #fca5a5;
  }
  .confirm-btn,
  .confirm-btn:hover:not(:disabled) {
    color: #b91c1c;
    border-color: #b91c1c;
    background: #fee2e2;
  }
  .trials-row td {
    background: var(--background-fill-secondary, #f9fafb);
    padding: 12px 24px;
  }
  .trials-loading {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 13px;
  }
  .trials-table {
    font-size: 13px;
  }
  .trials-table-wrap {
    overflow-x: auto;
  }
  .sweep-detail {
    margin-bottom: 12px;
  }
  .sweep-detail-title {
    font-size: 15px;
    font-weight: 700;
    color: var(--body-text-color, #1f2937);
    margin-bottom: 6px;
  }
  .sweep-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 24px;
    margin-bottom: 8px;
    font-size: 13px;
  }
  .meta-item {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .meta-label {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .sweep-id {
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 12px;
  }
  .copy-btn {
    padding: 1px 8px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: 6px;
    background: var(--background-fill-primary, #fff);
    color: var(--body-text-color-subdued, #6b7280);
    cursor: pointer;
    font-size: 11px;
  }
  .copy-btn:hover {
    background: var(--background-fill-secondary, #f3f4f6);
  }
  .search-space {
    display: flex;
    align-items: baseline;
    gap: 12px;
    font-size: 13px;
  }
  .search-space-grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 2px 12px;
  }
  .param-name {
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 12px;
    color: var(--body-text-color, #1f2937);
  }
  .param-spec {
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 12px;
    color: var(--body-text-color-subdued, #6b7280);
    word-break: break-word;
  }
  .trials-plots {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
    gap: 12px;
    margin-bottom: 12px;
  }
  .sort-btn {
    background: none;
    border: none;
    padding: 0;
    color: inherit;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
  }
  .sort-btn:hover {
    color: var(--body-text-color, #1f2937);
  }
  .param-header {
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 12px;
  }
  .best-trial td {
    font-weight: 600;
  }
  .best-badge {
    margin-left: 6px;
    color: #d97706;
    font-size: 11px;
    white-space: nowrap;
  }
  .clickable-row {
    cursor: pointer;
  }
  .clickable-row:hover td {
    background: rgba(127, 127, 127, 0.12);
  }
  .params-cell {
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 12px;
    word-break: break-word;
  }
  .art-none {
    color: var(--body-text-color-subdued, #9ca3af);
  }
  .action-error {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
    padding: 8px 12px;
    border: 1px solid #fca5a5;
    border-radius: 6px;
    background: #fee2e2;
    color: #b91c1c;
    font-size: 13px;
  }
  .dismiss-btn {
    background: none;
    border: none;
    padding: 0;
    color: inherit;
    cursor: pointer;
    font-size: 13px;
    line-height: 1.4;
  }
</style>
