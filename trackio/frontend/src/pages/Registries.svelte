<script>
  import { onMount } from "svelte";
  import AliasPill from "../components/AliasPill.svelte";
  import {
    getRegistries,
    getRegistryBuckets,
    getRegistryDetails,
  } from "../lib/api.js";

  let source = $state("local");
  let buckets = $state([]);
  let bucketInput = $state("");
  let bucketId = $state(null);
  let registries = $state([]);
  let selectedRegistry = $state(null);
  let details = $state(null);
  let selectedCollection = $state(null);
  let loading = $state(true);
  let error = $state("");
  let staticUnavailable = $state(false);
  let requestId = 0;

  let collection = $derived(
    details?.collections?.find((item) => item.name === selectedCollection) ??
      details?.collections?.[0] ??
      null,
  );

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }

  function sourceLocation(link) {
    if (link.source_space_id) return `Space · ${link.source_space_id}`;
    if (link.source_bucket_id) return `Bucket · ${link.source_bucket_id}`;
    return "Local";
  }

  async function loadDetails(registryName, id) {
    if (!registryName) {
      details = null;
      selectedCollection = null;
      return;
    }
    const result = await getRegistryDetails(registryName, bucketId);
    if (id !== requestId) return;
    details = result;
    selectedCollection = result.collections?.[0]?.name ?? null;
  }

  async function loadRegistries() {
    const id = ++requestId;
    loading = true;
    error = "";
    details = null;
    selectedCollection = null;
    try {
      const result = await getRegistries(bucketId);
      if (id !== requestId) return;
      registries = result ?? [];
      selectedRegistry = registries[0]?.name ?? null;
      await loadDetails(selectedRegistry, id);
    } catch (e) {
      if (id !== requestId) return;
      registries = [];
      selectedRegistry = null;
      error = e?.message || "Could not load registries.";
    } finally {
      if (id === requestId) loading = false;
    }
  }

  async function selectRegistry(name) {
    if (name === selectedRegistry) return;
    const id = ++requestId;
    selectedRegistry = name;
    details = null;
    selectedCollection = null;
    loading = true;
    error = "";
    try {
      await loadDetails(name, id);
    } catch (e) {
      if (id === requestId) error = e?.message || "Could not load registry.";
    } finally {
      if (id === requestId) loading = false;
    }
  }

  function useLocal() {
    source = "local";
    bucketId = null;
    loadRegistries();
  }

  function openBucket() {
    const value = bucketInput.trim();
    if (!value) return;
    source = "bucket";
    bucketId = value;
    if (!buckets.includes(value)) buckets = [...buckets, value].sort();
    loadRegistries();
  }

  onMount(() => {
    loadRegistries();
    getRegistryBuckets()
      .then((result) => {
        staticUnavailable = !!result?.unavailable;
        buckets = result?.buckets ?? [];
        if (!bucketInput) {
          bucketInput = result?.default_bucket_id ?? buckets[0] ?? "";
        }
      })
      .catch(() => {
        // The bucket id can still be entered manually.
      });
  });
</script>

<div class="registry-page">
  <header class="page-header">
    <div>
      <h1>Registries</h1>
      <p>Browse promoted artifact versions across projects.</p>
    </div>
    <div class="source-controls" aria-label="Registry location">
      <div class="source-toggle">
        <button class:active={source === "local"} onclick={useLocal}>Local</button>
        <button
          class:active={source === "bucket"}
          onclick={() => {
            source = "bucket";
            if (bucketInput) openBucket();
          }}>HF Bucket</button
        >
      </div>
      {#if source === "bucket"}
        <div class="bucket-picker">
          <input
            aria-label="Registry bucket"
            list="registry-buckets"
            bind:value={bucketInput}
            onkeydown={(event) => event.key === "Enter" && openBucket()}
            placeholder="owner/bucket"
          />
          <datalist id="registry-buckets">
            {#each buckets as bucket}
              <option value={bucket}></option>
            {/each}
          </datalist>
          <button class="open-button" onclick={openBucket}>Open</button>
        </div>
      {/if}
    </div>
  </header>

  {#if staticUnavailable}
    <div class="empty-state">
      <h2>A live Trackio server is required</h2>
      <p>Registry browsing is not available in a static dashboard snapshot.</p>
    </div>
  {:else if error}
    <div class="empty-state error-state">
      <h2>Couldn’t load registries</h2>
      <p>{error}</p>
    </div>
  {:else}
    <div class="registry-layout">
      <aside class="registry-sidebar">
        <div class="sidebar-heading">
          <span>{source === "local" ? "Local registries" : bucketId}</span>
          <span class="count">{registries.length}</span>
        </div>
        {#if loading && registries.length === 0}
          <div class="sidebar-empty">Loading…</div>
        {:else if registries.length === 0}
          <div class="sidebar-empty">No registries found.</div>
        {:else}
          {#each registries as registry}
            <button
              class="registry-row"
              class:selected={registry.name === selectedRegistry}
              onclick={() => selectRegistry(registry.name)}
            >
              <span class="registry-name">{registry.name}</span>
              {#if registry.description}
                <span class="registry-description">{registry.description}</span>
              {/if}
            </button>
          {/each}
        {/if}
      </aside>

      <main class="registry-detail">
        {#if loading && !details}
          <div class="detail-empty">Loading registry…</div>
        {:else if !details}
          <div class="detail-empty">Select a registry to inspect it.</div>
        {:else}
          <section class="registry-summary">
            <div>
              <div class="eyebrow">Registry</div>
              <h2>{details.name}</h2>
              {#if details.description}<p>{details.description}</p>{/if}
            </div>
            <div class="summary-meta">
              <span>{details.bucket_id ? `Bucket · ${details.bucket_id}` : "Local"}</span>
              <span>Created {formatDate(details.created_at)}</span>
            </div>
          </section>

          <div class="content-grid">
            <section class="collections-panel">
              <div class="section-title">
                <h3>Collections</h3>
                <span>{details.collections.length}</span>
              </div>
              {#if details.collections.length === 0}
                <div class="panel-empty">No collections in this registry.</div>
              {:else}
                <div class="collection-list">
                  {#each details.collections as item}
                    <button
                      class="collection-row"
                      class:selected={item.name === collection?.name}
                      onclick={() => (selectedCollection = item.name)}
                    >
                      <span>
                        <strong>{item.name}</strong>
                        <small>{item.type}</small>
                      </span>
                      <span class="collection-stats">
                        {item.num_links} {item.num_links === 1 ? "version" : "versions"}
                      </span>
                    </button>
                  {/each}
                </div>
              {/if}
            </section>

            <section class="versions-panel">
              {#if collection}
                <div class="collection-header">
                  <div>
                    <div class="eyebrow">{collection.type} collection</div>
                    <h3>{collection.name}</h3>
                    {#if collection.description}<p>{collection.description}</p>{/if}
                  </div>
                  <span class="version-count">{collection.num_links} linked</span>
                </div>
                {#if collection.links.length === 0}
                  <div class="panel-empty">No versions have been linked.</div>
                {:else}
                  <div class="versions-table-wrap">
                    <table class="versions-table">
                      <thead>
                        <tr><th>Version</th><th>Aliases</th><th>Source</th><th>Storage</th><th>Linked</th></tr>
                      </thead>
                      <tbody>
                        {#each collection.links as link}
                          <tr>
                            <td><strong>v{link.collection_version}</strong></td>
                            <td>
                              <div class="aliases">
                                {#each link.aliases as alias}<AliasPill {alias} />{/each}
                                {#if link.aliases.length === 0}<span class="muted">—</span>{/if}
                              </div>
                            </td>
                            <td><code>{link.source_project}/{link.source_artifact}:v{link.source_version}</code></td>
                            <td>{sourceLocation(link)}</td>
                            <td>{formatDate(link.created_at)}</td>
                          </tr>
                        {/each}
                      </tbody>
                    </table>
                  </div>
                {/if}
              {:else}
                <div class="panel-empty">Select a collection.</div>
              {/if}
            </section>
          </div>

          <section class="events-panel">
            <div class="section-title">
              <h3>Audit history</h3>
              <span>{details.events.length}</span>
            </div>
            {#if details.events.length === 0}
              <div class="panel-empty">No registry events.</div>
            {:else}
              <div class="event-list">
                {#each [...details.events].reverse() as event}
                  <div class="event-row">
                    <span class="event-kind">{event.kind}</span>
                    <span class="event-description">
                      {event.payload.collection ?? details.name}
                      {#if event.payload.collection_version != null} · v{event.payload.collection_version}{/if}
                      {#if event.payload.alias} · {event.payload.alias}{/if}
                    </span>
                    <time>{formatDate(event.ts)}</time>
                  </div>
                {/each}
              </div>
            {/if}
          </section>
        {/if}
      </main>
    </div>
  {/if}
</div>

<style>
  .registry-page { width: 100%; min-width: 0; overflow: auto; background: var(--background-fill-secondary, #f9fafb); }
  .page-header { min-height: 86px; padding: 18px 24px; display: flex; align-items: center; justify-content: space-between; gap: 24px; border-bottom: 1px solid var(--border-color-primary, #e5e7eb); background: var(--background-fill-primary, white); }
  h1, h2, h3, p { margin: 0; }
  h1 { font-size: 22px; line-height: 1.2; }
  .page-header p, .registry-summary p, .collection-header p { margin-top: 5px; color: var(--body-text-color-subdued, #6b7280); font-size: 13px; }
  .source-controls, .bucket-picker, .source-toggle { display: flex; align-items: center; gap: 8px; }
  .source-toggle { padding: 3px; border: 1px solid var(--border-color-primary, #e5e7eb); border-radius: 8px; background: var(--background-fill-secondary, #f9fafb); }
  .source-toggle button, .open-button { border: 0; border-radius: 6px; padding: 7px 11px; background: transparent; color: var(--body-text-color-subdued, #6b7280); cursor: pointer; font: inherit; font-size: 13px; }
  .source-toggle button.active { background: var(--background-fill-primary, white); color: var(--body-text-color, #1f2937); box-shadow: var(--shadow-drop, 0 1px 2px rgba(0,0,0,.05)); font-weight: 600; }
  .bucket-picker input { width: 230px; border: 1px solid var(--border-color-primary, #e5e7eb); border-radius: 7px; padding: 8px 10px; background: var(--input-background-fill, white); color: var(--body-text-color, #1f2937); font: inherit; font-size: 13px; }
  .open-button { background: var(--color-accent, #f97316); color: white; }
  .registry-layout { min-height: calc(100vh - 131px); display: grid; grid-template-columns: 250px minmax(0, 1fr); }
  .registry-sidebar { border-right: 1px solid var(--border-color-primary, #e5e7eb); background: var(--background-fill-primary, white); padding: 12px; }
  .sidebar-heading, .section-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: var(--body-text-color-subdued, #6b7280); font-size: 12px; font-weight: 600; padding: 6px 8px 10px; }
  .sidebar-heading > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .count, .section-title span { min-width: 20px; text-align: center; border-radius: 10px; padding: 1px 6px; background: var(--background-fill-secondary, #f3f4f6); }
  .registry-row { width: 100%; display: flex; flex-direction: column; align-items: flex-start; gap: 3px; padding: 10px; border: 0; border-radius: 7px; background: transparent; color: inherit; text-align: left; cursor: pointer; }
  .registry-row:hover, .registry-row.selected { background: var(--background-fill-secondary, #f3f4f6); }
  .registry-row.selected { box-shadow: inset 3px 0 0 var(--color-accent, #f97316); }
  .registry-name { font-weight: 600; }
  .registry-description { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--body-text-color-subdued, #6b7280); font-size: 12px; }
  .sidebar-empty, .detail-empty, .panel-empty { padding: 22px 10px; color: var(--body-text-color-subdued, #6b7280); font-size: 13px; }
  .registry-detail { min-width: 0; padding: 22px 26px 40px; overflow: auto; }
  .registry-summary { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 18px; }
  .registry-summary h2 { font-size: 24px; }
  .eyebrow { margin-bottom: 4px; color: var(--body-text-color-subdued, #6b7280); font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
  .summary-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; color: var(--body-text-color-subdued, #6b7280); font-size: 12px; }
  .content-grid { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 14px; align-items: start; }
  .collections-panel, .versions-panel, .events-panel { border: 1px solid var(--border-color-primary, #e5e7eb); border-radius: 9px; background: var(--background-fill-primary, white); overflow: hidden; }
  .section-title { border-bottom: 1px solid var(--border-color-primary, #e5e7eb); padding: 10px 12px; }
  .section-title h3 { color: var(--body-text-color, #1f2937); font-size: 13px; }
  .collection-list { padding: 6px; }
  .collection-row { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 0; border-radius: 6px; padding: 9px 8px; background: transparent; color: inherit; text-align: left; cursor: pointer; }
  .collection-row:hover, .collection-row.selected { background: var(--background-fill-secondary, #f3f4f6); }
  .collection-row span:first-child { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .collection-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
  .collection-row small, .collection-stats { color: var(--body-text-color-subdued, #6b7280); font-size: 11px; }
  .collection-stats { flex-shrink: 0; }
  .collection-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 15px 16px; border-bottom: 1px solid var(--border-color-primary, #e5e7eb); }
  .collection-header h3 { font-size: 18px; }
  .version-count { padding: 3px 8px; border-radius: 10px; background: var(--background-fill-secondary, #f3f4f6); color: var(--body-text-color-subdued, #6b7280); font-size: 11px; white-space: nowrap; }
  .versions-table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 10px 12px; border-bottom: 1px solid var(--border-color-primary, #e5e7eb); text-align: left; vertical-align: top; font-size: 12px; white-space: nowrap; }
  th { color: var(--body-text-color-subdued, #6b7280); background: var(--background-fill-secondary, #f9fafb); font-weight: 600; }
  tbody tr:last-child td { border-bottom: 0; }
  code { color: var(--body-text-color, #1f2937); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
  .aliases { display: flex; flex-wrap: wrap; gap: 4px; }
  .muted { color: var(--body-text-color-subdued, #9ca3af); }
  .events-panel { margin-top: 14px; }
  .event-list { max-height: 260px; overflow: auto; }
  .event-row { display: grid; grid-template-columns: 78px minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 9px 12px; border-bottom: 1px solid var(--border-color-primary, #e5e7eb); font-size: 12px; }
  .event-row:last-child { border-bottom: 0; }
  .event-kind { width: fit-content; border-radius: 10px; padding: 2px 7px; color: var(--color-accent, #f97316); background: var(--color-accent-soft, #fff7ed); font-weight: 600; }
  .event-description { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  time { color: var(--body-text-color-subdued, #6b7280); }
  .empty-state { max-width: 560px; margin: 70px auto; padding: 28px; text-align: center; color: var(--body-text-color-subdued, #6b7280); }
  .empty-state h2 { margin-bottom: 7px; color: var(--body-text-color, #1f2937); }
  .error-state { color: #b91c1c; }
  @media (max-width: 900px) {
    .page-header { align-items: flex-start; flex-direction: column; }
    .source-controls { width: 100%; flex-wrap: wrap; }
    .bucket-picker { flex: 1; }
    .bucket-picker input { width: 100%; min-width: 170px; }
    .registry-layout { grid-template-columns: 190px minmax(0, 1fr); }
    .content-grid { grid-template-columns: 1fr; }
    .registry-detail { padding: 18px; }
    .summary-meta { display: none; }
  }
</style>
