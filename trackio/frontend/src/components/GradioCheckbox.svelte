<script>
  let {
    label = "",
    checked = $bindable(false),
    showLabel = true,
  } = $props();

  function handleInput(e) {
    checked = e.currentTarget.checked;
  }
</script>

<label class="checkbox-container">
  <input
    bind:checked
    oninput={handleInput}
    type="checkbox"
  />
  {#if showLabel && label}
    <span class="label-text">{label}</span>
  {/if}
</label>

<style>
  .checkbox-container {
    display: flex;
    align-items: center;
    gap: var(--spacing-lg, 8px);
    cursor: pointer;
  }

  .label-text {
    color: var(--body-text-color, #1f2937);
    font-size: var(--checkbox-label-text-size, 14px);
    line-height: var(--line-sm, 1.4);
  }

  input[type="checkbox"] {
    --ring-color: transparent;
    position: relative;
    appearance: none;
    -webkit-appearance: none;
    width: 18px;
    height: 18px;
    box-shadow: var(--checkbox-shadow);
    border: 1px solid var(--checkbox-border-color, #d1d5db);
    border-radius: var(--checkbox-border-radius, 4px);
    background-color: var(--checkbox-background-color, white);
    line-height: var(--line-sm, 1.4);
    flex-shrink: 0;
    cursor: pointer;
    transition: background-color 0.15s, border-color 0.15s;
  }

  input[type="checkbox"]:checked,
  input[type="checkbox"]:checked:hover,
  input[type="checkbox"]:checked:focus {
    background-image: var(--checkbox-check);
    background-color: var(--checkbox-background-color-selected, #2563eb);
    border-color: var(--checkbox-border-color-focus, #3b82f6);
  }

  input[type="checkbox"]:hover {
    border-color: var(--checkbox-border-color-hover, #d1d5db);
    background-color: var(--checkbox-background-color-hover, white);
  }

  input[type="checkbox"]:focus {
    border-color: var(--checkbox-border-color-focus, #3b82f6);
    background-color: var(--checkbox-background-color-focus, white);
    outline: none;
  }
</style>
