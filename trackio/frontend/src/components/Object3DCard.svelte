<script>
  let {
    item,
    compact = false,
    color = "#9ca3af",
    onopen = () => {},
  } = $props();

  function pointSummary() {
    const original = item.original_point_count;
    const rendered = item.rendered_point_count;
    if (!Number.isFinite(original)) return null;
    return rendered < original
      ? `${original.toLocaleString()} points · ${rendered.toLocaleString()} shown`
      : `${original.toLocaleString()} points`;
  }
</script>

{#snippet preview()}
  <svg viewBox="0 0 64 64" fill="none" aria-hidden="true">
    <path d="M32 7 53 19.5v25L32 57 11 44.5v-25L32 7Z" stroke="currentColor" stroke-width="2"/>
    <path d="m11 19.5 21 13 21-13M32 32.5V57" stroke="currentColor" stroke-width="2"/>
    {#if item.kind === "point_cloud" || item.kind === "gaussian_splat"}
      <circle cx="23" cy="21" r="2.5" fill="currentColor"/>
      <circle cx="38" cy="18" r="1.8" fill="currentColor"/>
      <circle cx="43" cy="33" r="2.2" fill="currentColor"/>
      <circle cx="26" cy="41" r="1.7" fill="currentColor"/>
    {/if}
  </svg>
  <span class="format-badge">{item.format?.toUpperCase() || "3D"}</span>
{/snippet}

{#if compact}
  <button
    class="object-frame compact"
    type="button"
    onclick={() => onopen(item)}
    aria-label={`Open 3D object ${item.caption || item.key || ""}`}
    title={item.caption || item.key || "3D object"}
  >
    {@render preview()}
  </button>
{:else}
  <div class="object-card">
    <div class="object-label">{item.key || "3D object"}</div>
    <button
      class="object-frame"
      type="button"
      onclick={() => onopen(item)}
      aria-label={`Open 3D object ${item.caption || item.key || ""}`}
    >
      {@render preview()}
    </button>
    {#if item.caption}
      <div class="object-caption">{item.caption}</div>
    {/if}
    <div class="object-kind">
      {item.kind?.replaceAll("_", " ") || "model"}{pointSummary()
        ? ` · ${pointSummary()}`
        : ""}
    </div>
    {#if item._run !== undefined}
      <div class="object-meta">
        <span class="run-dot" style:background={color}></span>
        <span class="meta-text">{item._run}, Step: {item.step}</span>
      </div>
    {/if}
  </div>
{/if}

<style>
  .object-card {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    background: var(--background-fill-secondary, #f9fafb);
    overflow: hidden;
  }
  .object-label {
    font-size: var(--text-sm, 12px);
    font-weight: 500;
    color: var(--body-text-color, #1f2937);
    word-break: break-word;
  }
  .object-frame {
    position: relative;
    display: grid;
    width: 100%;
    aspect-ratio: 4 / 3;
    place-items: center;
    overflow: hidden;
    border: 0;
    border-radius: var(--radius-sm, 4px);
    background: linear-gradient(145deg, #111827, #293241);
    color: #ff9f43;
    cursor: zoom-in;
    font: inherit;
    padding: 0;
  }
  .object-frame.compact {
    width: 120px;
    height: 80px;
    aspect-ratio: auto;
  }
  .object-frame svg {
    width: 46%;
    max-width: 64px;
    height: auto;
    opacity: 0.9;
  }
  .format-badge {
    position: absolute;
    right: 5px;
    bottom: 4px;
    color: #dbe4ee;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.08em;
  }
  .object-caption,
  .object-kind {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #9ca3af);
  }
  .object-kind {
    font-size: var(--text-xs, 11px);
    text-transform: capitalize;
  }
  .object-meta {
    display: flex;
    align-items: center;
    gap: 3px;
    font-size: var(--text-xs, 11px);
    color: var(--body-text-color-subdued, #9ca3af);
    font-variant-numeric: tabular-nums;
  }
  .run-dot {
    width: 8px;
    height: 8px;
    flex-shrink: 0;
    border-radius: 50%;
    margin: 0 2px;
  }
  .meta-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
