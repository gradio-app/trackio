<script>
  let {
    label = "",
    info = "",
    value = $bindable(""),
    placeholder = "",
    showLabel = true,
  } = $props();
</script>

<div class="textbox-container">
  {#if showLabel && label}
    <span class="label">{label}</span>
  {/if}
  {#if info}
    <span class="info">{info}</span>
  {/if}
  <div class="input-wrap">
    <input
      type="text"
      bind:value
      {placeholder}
    />
  </div>
</div>

<style>
  .textbox-container {
    width: 100%;
  }
  .label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--body-text-color-subdued, #6b7280);
    margin-bottom: 6px;
  }
  .info {
    display: block;
    font-size: 12px;
    color: var(--body-text-color-subdued, #9ca3af);
    margin-bottom: 4px;
  }
  .input-wrap {
    border-radius: var(--input-radius, 8px);
    background: var(--input-background-fill, white);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  .input-wrap:focus-within {
    border-color: var(--input-border-color-focus, #fdba74);
    box-shadow: 0 0 0 2px var(--primary-50, #fff7ed);
  }
  input {
    width: 100%;
    padding: 7px 10px;
    outline: none;
    border: none;
    background: transparent;
    color: var(--body-text-color, #1f2937);
    font-size: 13px;
    font-family: inherit;
    border-radius: var(--input-radius, 8px);
  }
  input::placeholder {
    color: var(--input-placeholder-color, #9ca3af);
  }
</style>
