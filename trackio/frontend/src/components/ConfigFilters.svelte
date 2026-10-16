<script>
  import { configFilterKeys } from "../lib/runFilters.js";

  let { configs = {}, groups = $bindable([]), matchCount = null } = $props();
  let keys = $derived(configFilterKeys(configs));
  let activeGroups = $derived(groups.map((group) => group.filter((rule) => rule.key)).filter((group) => group.length));
  let count = $derived(activeGroups.flat().length);
  let dialog;
  let draft = $state([]);

  function edit() {
    draft = groups.map((group) => group.map((rule) => ({ ...rule })));
    dialog.showModal();
  }

  function apply() {
    groups = draft.map((group) => group.filter((rule) => rule.key)).filter((group) => group.length);
    dialog.close();
  }
  const newRule = () => ({ key: "", operator: "=", value: "" });

  function remove(groupIndex, ruleIndex) {
    draft = draft.map((group, i) => i === groupIndex
      ? group.filter((_, j) => j !== ruleIndex) : group).filter((group) => group.length);
  }
</script>

<div class="config-filters">
  <div class="filter-heading">
    <button onclick={edit} aria-haspopup="dialog">Config filters{count ? ` (${count})` : ""}</button>
    {#if count}<button onclick={() => { groups = []; }}>Clear</button>{/if}
  </div>
  {#if count}
    <div class="active-filters" aria-label="Active configuration filters">
      {#each activeGroups as group, i}
        {#if i > 0}<div class="join">OR</div>{/if}
        {#each group as rule, j}
          <div class="filter-summary">{j > 0 ? "AND " : ""}{JSON.parse(rule.key).join(".")} {rule.operator} {JSON.stringify(rule.value)}</div>
        {/each}
      {/each}
    </div>
    {#if matchCount === 0}<p role="status">No runs match the current filters. Edit or clear filters to show runs.</p>{/if}
  {/if}
</div>

<dialog bind:this={dialog} aria-labelledby="config-filter-title">
  <div class="dialog-heading">
    <h2 id="config-filter-title">Config filters</h2>
    <button aria-label="Close configuration filters" onclick={() => dialog.close()}>×</button>
  </div>
  <p>Match all conditions in a group, or any of the groups.</p>
  <div class="editor">
  {#each draft as group, i}
    {#if i > 0}<div class="join">OR</div>{/if}
    <div class="filter-group">
      {#each group as rule, j}
        {#if j > 0}<div class="join">AND</div>{/if}
        <div class="rule">
          <select aria-label="Configuration key" bind:value={rule.key}>
            <option value="">Select config key</option>
            {#each keys as key}<option value={key.value}>{key.label}</option>{/each}
          </select>
          <select aria-label="Comparison operator" bind:value={rule.operator}>
            {#each ["=", "!=", ">", ">=", "<", "<=", "contains"] as operator}
              <option value={operator}>{operator}</option>
            {/each}
          </select>
          <input aria-label="Configuration value" placeholder="Value" bind:value={rule.value} />
          <button class="remove" aria-label="Remove condition" onclick={() => remove(i, j)}>×</button>
        </div>
      {/each}
      <button onclick={() => { draft[i] = [...group, newRule()]; }}>+ AND</button>
    </div>
  {/each}
  <div class="actions">
    <button onclick={() => { draft = [...draft, [newRule()]]; }}>{draft.length ? "+ OR group" : "+ Add filter"}</button>
    {#if draft.length}<button onclick={() => { draft = []; }}>Clear draft</button>{/if}
  </div>
  </div>
  <div class="dialog-actions">
    <button onclick={() => dialog.close()}>Cancel</button>
    <button class="apply" onclick={apply}>Apply filters</button>
  </div>
</dialog>

<style>
  .config-filters { margin-top: 8px; font-size: 12px; color: var(--body-text-color); }
  .filter-heading, .dialog-heading, .dialog-actions { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .active-filters { max-height: 112px; overflow-y: auto; margin-top: 6px; padding: 6px 8px; background: var(--input-background-fill); border: 1px solid var(--border-color-primary); border-radius: 6px; }
  .filter-summary { overflow-wrap: anywhere; line-height: 1.5; }
  dialog { margin: auto; width: min(560px, calc(100vw - 32px)); max-height: calc(100dvh - 48px); box-sizing: border-box; padding: 20px; border: 1px solid var(--border-color-primary); border-radius: 12px; background: var(--body-background-fill, white); color: var(--body-text-color); box-shadow: 0 12px 40px #0003; font-size: 13px; }
  dialog::backdrop { background: #0006; }
  h2 { font-size: 16px; margin: 0; }
  p { line-height: 1.5; margin: 8px 0; }
  .editor { max-height: 55dvh; overflow-y: auto; }
  .filter-group { border: 1px solid var(--border-color-primary); border-radius: 6px; padding: 8px; margin-top: 6px; }
  .rule { display: grid; grid-template-columns: minmax(0, 1fr) 68px minmax(0, 1fr) 24px; gap: 4px; }
  .rule select:first-child { grid-column: 1; }
  .rule .remove { grid-column: 4; grid-row: 1; }
  .rule select:nth-of-type(2) { grid-column: 2; grid-row: 1; }
  .rule input { grid-column: 3; grid-row: 1; }
  input, select, button { font: inherit; color: inherit; border: 1px solid var(--border-color-primary); border-radius: 4px; background: var(--input-background-fill); padding: 6px; min-width: 0; }
  button { cursor: pointer; }
  .filter-group > button { margin-top: 8px; }
  .join { font-size: 10px; margin: 6px 0; opacity: 0.7; }
  .actions { display: flex; gap: 6px; margin-top: 8px; }
  .dialog-actions { justify-content: flex-end; padding-top: 16px; }
  .apply { background: var(--button-primary-background-fill, #f97316); color: var(--button-primary-text-color, white); }
  @media (max-width: 480px) {
    .rule { grid-template-columns: 68px minmax(0, 1fr) 24px; }
    .rule select:first-child { grid-column: 1 / 3; }
    .rule .remove { grid-column: 3; }
    .rule select:nth-of-type(2) { grid-column: 1; grid-row: 2; }
    .rule input { grid-column: 2 / 4; grid-row: 2; }
  }
</style>
