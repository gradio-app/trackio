<script>
  let {
    item,
    compact = false,
    selected = false,
    color = "#9ca3af",
    onselect = () => {},
    onopen = () => {},
  } = $props();

  function activate(event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onopen(item);
  }

  function pointSummary() {
    const original = item.original_point_count;
    const rendered = item.rendered_point_count;
    if (!Number.isFinite(original)) return null;
    return rendered < original
      ? `${original.toLocaleString()} points · ${rendered.toLocaleString()} shown`
      : `${original.toLocaleString()} points`;
  }
</script>

<div
  class:compact
  class:selected
  class="object-card"
  role="button"
  tabindex="0"
  aria-label={`Open 3D object ${item.caption || item.key || ""}`}
  onclick={() => onselect(item)}
  ondblclick={() => onopen(item)}
  onkeydown={activate}
>
  <div class="object-preview" aria-hidden="true">
    <svg viewBox="0 0 64 64" fill="none">
      <path d="M32 7 53 19.5v25L32 57 11 44.5v-25L32 7Z" stroke="currentColor" stroke-width="2"/>
      <path d="m11 19.5 21 13 21-13M32 32.5V57" stroke="currentColor" stroke-width="2"/>
      {#if item.kind === "point_cloud" || item.kind === "gaussian_splat"}
        <circle cx="23" cy="21" r="2.5" fill="currentColor"/>
        <circle cx="38" cy="18" r="1.8" fill="currentColor"/>
        <circle cx="43" cy="33" r="2.2" fill="currentColor"/>
        <circle cx="26" cy="41" r="1.7" fill="currentColor"/>
      {/if}
    </svg>
    <span>{item.format?.toUpperCase() || "3D"}</span>
  </div>
  <div class="object-info">
    <div class="object-title">{item.caption || item.key || "3D object"}</div>
    {#if item.caption && item.key}<div class="object-key">{item.key}</div>{/if}
    <div class="object-kind">{item.kind?.replaceAll("_", " ") || "model"}</div>
    {#if pointSummary()}<div class="object-points">{pointSummary()}</div>{/if}
    {#if item._run !== undefined}
      <div class="object-meta">
        <span class="run-dot" style:background={color}></span>
        <span>{item._run} · step {item.step}</span>
      </div>
    {/if}
  </div>
  <button
    class="open-button"
    type="button"
    onclick={(event) => {
      event.stopPropagation();
      onopen(item);
    }}
  >Open</button>
</div>

<style>
  .object-card {
    display: grid;
    grid-template-columns: 86px minmax(0, 1fr) auto;
    min-height: 96px;
    align-items: center;
    gap: 10px;
    padding: 8px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    background: var(--background-fill-secondary, #f9fafb);
    color: var(--body-text-color, #1f2937);
    cursor: pointer;
    outline: none;
  }
  .object-card:hover,
  .object-card:focus-visible,
  .object-card.selected {
    border-color: var(--primary-500, #f97316);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-500, #f97316) 18%, transparent);
  }
  .object-card.compact {
    grid-template-columns: 58px minmax(100px, 1fr);
    min-width: 220px;
    min-height: 66px;
    padding: 5px;
  }
  .object-preview {
    position: relative;
    display: grid;
    min-height: 78px;
    place-items: center;
    border-radius: var(--radius-sm, 4px);
    background: linear-gradient(145deg, #111827, #293241);
    color: #ff9f43;
  }
  .compact .object-preview { min-height: 56px; }
  .object-preview svg { width: 54px; height: 54px; opacity: 0.9; }
  .compact .object-preview svg { width: 40px; height: 40px; }
  .object-preview span {
    position: absolute;
    right: 5px;
    bottom: 4px;
    color: #dbe4ee;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.08em;
  }
  .object-info { min-width: 0; }
  .object-title {
    overflow: hidden;
    font-size: var(--text-sm, 12px);
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .object-key,
  .object-kind,
  .object-points,
  .object-meta {
    margin-top: 2px;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-xs, 11px);
  }
  .object-kind { text-transform: capitalize; }
  .object-meta { display: flex; align-items: center; gap: 5px; }
  .run-dot { width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; }
  .open-button {
    align-self: end;
    border: 1px solid var(--border-color-primary, #d1d5db);
    border-radius: var(--radius-sm, 4px);
    background: var(--background-fill-primary, white);
    color: inherit;
    cursor: pointer;
    font: inherit;
    font-size: 11px;
    padding: 4px 8px;
  }
  .compact .open-button { display: none; }
</style>
