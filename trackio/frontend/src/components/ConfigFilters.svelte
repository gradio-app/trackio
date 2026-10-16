<script>
  import { configFilterKeys } from "../lib/runFilters.js";

  let { configs = {}, groups = $bindable([]) } = $props();
  let keys = $derived(configFilterKeys(configs));
  let count = $derived(groups.flat().filter((rule) => rule.key).length);
  const newRule = () => ({ key: "", operator: "=", value: "" });

  function remove(groupIndex, ruleIndex) {
    groups = groups.map((group, i) => i === groupIndex
      ? group.filter((_, j) => j !== ruleIndex) : group).filter((group) => group.length);
  }
</script>

<details class="config-filters">
  <summary>Config filters{count ? ` (${count})` : ""}</summary>
  {#each groups as group, i}
    {#if i > 0}<div class="join">OR</div>{/if}
    <div class="filter-group">
      {#each group as rule, j}
        {#if j > 0}<div class="join">AND</div>{/if}
        <div class="rule">
          <select aria-label="Configuration key" bind:value={rule.key}>
            <option value="">Select config key</option>
            {#each keys as key}<option value={key.value}>{key.label}</option>{/each}
          </select>
          <button class="remove" aria-label="Remove condition" onclick={() => remove(i, j)}>×</button>
          <select aria-label="Comparison operator" bind:value={rule.operator}>
            {#each ["=", "!=", ">", ">=", "<", "<=", "contains"] as operator}
              <option value={operator}>{operator}</option>
            {/each}
          </select>
          <input aria-label="Configuration value" placeholder="Value" bind:value={rule.value} />
        </div>
      {/each}
      <button onclick={() => { groups[i] = [...group, newRule()]; }}>+ AND</button>
    </div>
  {/each}
  <div class="actions">
    <button onclick={() => { groups = [...groups, [newRule()]]; }}>{groups.length ? "+ OR group" : "+ Add filter"}</button>
    {#if groups.length}<button onclick={() => { groups = []; }}>Clear</button>{/if}
  </div>
</details>

<style>
  .config-filters { margin-top: 8px; font-size: 12px; color: var(--body-text-color); }
  summary { cursor: pointer; padding: 4px 0; }
  .filter-group { border: 1px solid var(--border-color-primary); border-radius: 6px; padding: 8px; margin-top: 6px; }
  .rule { display: grid; grid-template-columns: 68px minmax(0, 1fr) 24px; gap: 4px; }
  .rule select:first-child { grid-column: 1 / 3; }
  .rule input { grid-column: 2 / 4; }
  input, select, button { font: inherit; color: inherit; border: 1px solid var(--border-color-primary); border-radius: 4px; background: var(--input-background-fill); padding: 5px; min-width: 0; }
  button { cursor: pointer; margin-top: 6px; }
  .remove { margin: 0; }
  .join { font-size: 10px; margin: 6px 0; opacity: 0.7; }
  .actions { display: flex; gap: 6px; }
</style>
