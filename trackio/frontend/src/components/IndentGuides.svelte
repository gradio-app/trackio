<script>
  let { depth = 0 } = $props();
</script>

{#if depth > 0}
  <span class="indent"
    >{#each Array.from({ length: depth }) as _}<span class="indent-guide"
      ></span>{/each}</span
  >
{/if}

<style>
  .indent {
    display: flex;
    align-self: stretch;
    flex-shrink: 0;
  }
  .indent-guide {
    width: 16px;
    align-self: stretch;
    position: relative;
  }
  .indent-guide::before {
    content: "";
    position: absolute;
    left: 6px;
    top: 0;
    bottom: 0;
    border-left: 1px solid var(--border-color-primary, #e5e7eb);
  }
</style>
