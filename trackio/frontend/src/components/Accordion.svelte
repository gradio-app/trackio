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
      <span class="arrow" class:rotated={open}>▶</span>
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
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    margin-bottom: 8px;
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
    padding: 8px 12px;
    border: none;
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    text-align: left;
  }
  .accordion-header:hover {
    background: var(--bg-tertiary);
  }
  .arrow {
    font-size: 10px;
    transition: transform 0.15s;
    color: var(--text-secondary);
  }
  .arrow.rotated {
    transform: rotate(90deg);
  }
  .accordion-body {
    padding: 8px;
  }
</style>
