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
    gap: 8px;
    cursor: pointer;
    margin: 8px 0px;
  }

  .label-text {
    color: var(--body-text-color, #1f2937);
    font-size: 13px;
    line-height: 1.4;
  }

  input[type="checkbox"] {
    --ring-color: transparent;
    position: relative;
    appearance: none;
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    box-shadow: var(--checkbox-shadow);
    border: 1px solid var(--checkbox-border-color, #d1d5db);
    border-radius: var(--checkbox-border-radius, 4px);
    background-color: var(--checkbox-background-color, white);
    flex-shrink: 0;
    cursor: pointer;
    transition: background-color 0.15s, border-color 0.15s;
  }

  input[type="checkbox"]:checked,
  input[type="checkbox"]:checked:hover,
  input[type="checkbox"]:checked:focus {
    background-image: var(--checkbox-check);
    background-color: var(--checkbox-background-color-selected, #f97316);
    border-color: var(--checkbox-border-color-selected, #f97316);
  }

  input[type="checkbox"]:hover {
    border-color: var(--checkbox-border-color-hover, #d1d5db);
    background-color: var(--checkbox-background-color-hover, white);
  }

  input[type="checkbox"]:focus {
    border-color: var(--checkbox-border-color-focus, #f97316);
    background-color: var(--checkbox-background-color-focus, white);
    outline: none;
  }
</style>
