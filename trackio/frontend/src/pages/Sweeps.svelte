<script>
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import ParallelCoordinatesPlot from "../components/ParallelCoordinatesPlot.svelte";
  import {
    getSweeps,
    getSweepTrials,
    setSweepState,
    getRunsForProject,
  } from "../lib/api.js";
  import { openRunDetail } from "../lib/router.js";

  let { project = null, runMutationAllowed = true } = $props();

  let sweeps = $state([]);
  let loading = $state(false);
  let expandedSweepId = $state(null);
  let trialsBySweep = $state({});
  let runNamesById = $state({});
  let actionPending = $state(null);
  let actionError = $state(null);
  let loadSeq = 0;

  const TERMINAL_STATES = new Set(["finished", "stopped", "cancelled"]);

  async function loadSweeps() {
    const seq = ++loadSeq;
    if (!project) {
      sweeps = [];
      loading = false;
      return;
    }
    loading = true;
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
    } catch (e) {
      if (seq !== loadSeq) return;
      console.error("Failed to load sweeps:", e);
      sweeps = [];
    } finally {
      if (seq === loadSeq) loading = false;
    }
  }

  async function loadTrials(sweepId) {
    try {
      const trials = await getSweepTrials(project, sweepId);
      trialsBySweep = { ...trialsBySweep, [sweepId]: trials || [] };
    } catch (e) {
      console.error("Failed to load sweep trials:", e);
      trialsBySweep = { ...trialsBySweep, [sweepId]: [] };
    }
  }

  async function toggleTrials(sweepId) {
    if (expandedSweepId === sweepId) {
      expandedSweepId = null;
      return;
    }
    expandedSweepId = sweepId;
    if (!trialsBySweep[sweepId]) {
      await loadTrials(sweepId);
    }
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
      trialsBySweep = {};
      await loadSweeps();
      if (expandedSweepId) {
        await loadTrials(expandedSweepId);
      }
      actionPending = null;
    }
  }

  function formatMetric(value) {
    if (value == null) return "—";
    const num = Number(value);
    if (Number.isInteger(num)) return String(num);
    return num.toPrecision(4);
  }

  function formatParams(params) {
    return Object.entries(params || {})
      .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
      .join(", ");
  }

  function bestRunName(sweep) {
    if (!sweep.best_run_id) return null;
    return runNamesById[sweep.best_run_id] ?? null;
  }

  $effect(() => {
    if (project) {
      expandedSweepId = null;
      trialsBySweep = {};
      loadSweeps();
    }
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
      <div class="action-error">{actionError}</div>
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
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {#each sweeps as sweep (sweep.sweep_id)}
          <tr>
            <td class="sweep-id-cell">
              <button
                class="link-btn"
                onclick={() => toggleTrials(sweep.sweep_id)}
              >
                <span class="expand-caret"
                  >{expandedSweepId === sweep.sweep_id ? "▾" : "▸"}</span
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
            <td>{sweep.num_trials}</td>
            <td>
              {#if sweep.metric_name}
                {sweep.metric_name}
                <span class="metric-goal">({sweep.metric_goal})</span>
              {:else}
                —
              {/if}
            </td>
            <td>{formatMetric(sweep.best_metric_value)}</td>
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
            <td class="actions-cell">
              {#if !TERMINAL_STATES.has(sweep.state)}
                {#if sweep.state === "running"}
                  <button
                    class="action-btn"
                    disabled={!runMutationAllowed || actionPending !== null}
                    onclick={() => applyState(sweep.sweep_id, "paused")}
                    >Pause</button
                  >
                {:else if sweep.state === "paused"}
                  <button
                    class="action-btn"
                    disabled={!runMutationAllowed || actionPending !== null}
                    onclick={() => applyState(sweep.sweep_id, "running")}
                    >Resume</button
                  >
                {/if}
                <button
                  class="action-btn"
                  disabled={!runMutationAllowed || actionPending !== null}
                  onclick={() => applyState(sweep.sweep_id, "stopped")}
                  >Stop</button
                >
                <button
                  class="action-btn delete-btn"
                  disabled={!runMutationAllowed || actionPending !== null}
                  onclick={() => applyState(sweep.sweep_id, "cancelled")}
                  >Cancel</button
                >
              {:else}
                <span class="art-none">—</span>
              {/if}
            </td>
          </tr>
          {#if expandedSweepId === sweep.sweep_id}
            <tr class="trials-row">
              <td colspan="8">
                {#if !trialsBySweep[sweep.sweep_id]}
                  <div class="trials-loading">Loading trials…</div>
                {:else if trialsBySweep[sweep.sweep_id].length === 0}
                  <div class="trials-loading">No trials yet.</div>
                {:else}
                  <div class="trials-plot">
                    <ParallelCoordinatesPlot
                      trials={trialsBySweep[sweep.sweep_id]}
                      metricName={sweep.metric_name}
                      metricGoal={sweep.metric_goal}
                      bestRunId={sweep.best_run_id}
                    />
                  </div>
                  <table class="trials-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>State</th>
                        <th>{sweep.metric_name || "Metric"}</th>
                        <th>Run</th>
                        <th>Parameters</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each trialsBySweep[sweep.sweep_id] as trial (trial.trial_id)}
                        <tr
                          class:best-trial={sweep.best_run_id != null &&
                            trial.run_id === sweep.best_run_id}
                        >
                          <td>{trial.trial_id}</td>
                          <td>
                            <span class="state-badge trial-{trial.state}"
                              >{trial.state}</span
                            >
                          </td>
                          <td>{formatMetric(trial.metric_value)}</td>
                          <td>
                            {#if trial.run_id && runNamesById[trial.run_id]}
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
                          <td class="params-cell">{formatParams(trial.params)}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
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
  .trials-plot {
    margin-bottom: 12px;
  }
  .trials-plot:empty {
    display: none;
  }
  .best-trial td {
    font-weight: 600;
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
    margin-bottom: 12px;
    padding: 8px 12px;
    border: 1px solid #fca5a5;
    border-radius: 6px;
    background: #fee2e2;
    color: #b91c1c;
    font-size: 13px;
  }
</style>
