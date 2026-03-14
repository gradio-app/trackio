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
    <span class="block-title">{label}</span>
  {/if}
  {#if info}
    <span class="block-info">{info}</span>
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
  .block-title {
    display: block;
    font-size: var(--block-title-text-size, 14px);
    font-weight: var(--block-title-text-weight, 400);
    color: var(--block-title-text-color, #6b7280);
    margin-bottom: var(--spacing-lg, 8px);
  }
  .block-info {
    display: block;
    font-size: var(--block-info-text-size, 12px);
    color: var(--block-info-text-color, #9ca3af);
    margin-bottom: var(--spacing-md, 6px);
  }
  .input-wrap {
    border-radius: var(--input-radius, 8px);
    background: var(--input-background-fill, white);
    box-shadow: var(--input-shadow);
    border: var(--input-border-width, 1px) solid var(--border-color-primary, #e5e7eb);
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  .input-wrap:focus-within {
    box-shadow: var(--input-shadow-focus);
    border-color: var(--input-border-color-focus, #93c5fd);
  }
  input {
    width: 100%;
    padding: var(--input-padding, 10px);
    outline: none;
    border: none;
    background: transparent;
    color: var(--body-text-color, #1f2937);
    font-size: var(--input-text-size, 14px);
    font-family: inherit;
    border-radius: var(--input-radius, 8px);
  }
  input::placeholder {
    color: var(--input-placeholder-color, #9ca3af);
  }
</style>
