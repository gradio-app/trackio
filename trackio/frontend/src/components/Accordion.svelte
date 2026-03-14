<script>
  let { label = "", open = $bindable(true), hidden = false, children } = $props();

  function toggle() {
    open = !open;
  }
</script>

{#if hidden}
  <div class="accordion-hidden">
    {#if children}{@render children()}{/if}
  </div>
{:else}
  <div class="accordion">
    <button class="accordion-header" onclick={toggle}>
      <span class="arrow" class:rotated={open}>▾</span>
      <span class="accordion-label">{label}</span>
    </button>
    {#if open}
      <div class="accordion-body">
        {#if children}{@render children()}{/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .accordion {
    margin-bottom: 12px;
    overflow: hidden;
  }
  .accordion-hidden {
    margin-bottom: 8px;
  }
  .accordion-header {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 10px 14px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    background: var(--background-fill-primary, white);
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-md, 14px);
    font-weight: 600;
    cursor: pointer;
    text-align: left;
  }
  .accordion-header:hover {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .arrow {
    font-size: 14px;
    transition: transform 0.15s;
    color: var(--body-text-color, #1f2937);
    display: inline-block;
  }
  .arrow:not(.rotated) {
    transform: rotate(-90deg);
  }
  .accordion-body {
    padding: 12px 0;
  }
</style>
