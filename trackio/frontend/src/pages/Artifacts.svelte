<script>
  import { tick } from "svelte";
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import {
    listArtifacts,
    getArtifactManifest,
    getArtifactConsumers,
    getArtifactBlobUrl,
  } from "../lib/api.js";
  import { navigateTo, setQueryParam, getQueryParam } from "../lib/router.js";

  let { project = null } = $props();

  let artifacts = $state([]);
  let loading = $state(false);
  let expanded = $state({});
  let expandedVer = $state({});
  let manifests = $state({});
  let consumers = $state({});

  let groups = $derived.by(() => {
    const byType = new Map();
    for (const a of artifacts) {
      if (!byType.has(a.type)) byType.set(a.type, []);
      byType.get(a.type).push(a);
    }
    return [...byType.entries()].map(([type, items]) => ({ type, items }));
  });

  function formatSize(bytes) {
    if (bytes == null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024)
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function formatDate(iso) {
    if (!iso) return "";
    try {
      return new Date(iso).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return iso;
    }
  }

  function verKey(name, version) {
    return `${name}@v${version}`;
  }

  function openRun(runName, runId) {
    setQueryParam("selected_run_id", runId);
    setQueryParam("selected_run", runName);
    navigateTo("run-detail");
  }

  function toggleArtifact(name) {
    expanded[name] = !expanded[name];
  }

  async function toggleVersion(name, version) {
    const key = verKey(name, version.version);
    expandedVer[key] = !expandedVer[key];
    if (expandedVer[key] && !manifests[key]) {
      manifests[key] = { loading: true, files: null, error: false };
      consumers[key] = { loading: true, runs: [] };
      const [m, c] = await Promise.allSettled([
        getArtifactManifest(project, name, `v${version.version}`),
        getArtifactConsumers(project, version.version_id),
      ]);
      manifests[key] =
        m.status === "fulfilled"
          ? { loading: false, files: m.value?.manifest || [], error: false }
          : { loading: false, files: null, error: true };
      consumers[key] = {
        loading: false,
        runs: c.status === "fulfilled" ? c.value || [] : [],
      };
    }
  }

  async function loadArtifacts() {
    expanded = {};
    expandedVer = {};
    manifests = {};
    consumers = {};
    if (!project) {
      artifacts = [];
      return;
    }
    loading = true;
    try {
      artifacts = await listArtifacts(project);
    } catch {
      artifacts = [];
    } finally {
      loading = false;
    }
    const target = getQueryParam("selected_artifact");
    if (target && artifacts.some((a) => a.name === target)) {
      expanded[target] = true;
      await tick();
      document
        .getElementById(`artifact-${target}`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  $effect(() => {
    project;
    loadArtifacts();
  });
</script>

<div class="artifacts-page">
  {#if loading}
    <LoadingTrackio />
  {:else if artifacts.length === 0}
    <div class="empty-state">
      <h2>No artifacts in this project</h2>
      <p>
        Artifacts are versioned, content-addressed files (models, datasets, …)
        logged from a run. After <code>trackio.init()</code>, log one with
        <code>trackio.log_artifact()</code>:
      </p>
      <pre><code
          >{'import trackio\n\ntrackio.init(project="my-project")\ntrackio.log_artifact("model.pt", name="my-model", type="model")'}</code
        ></pre>
      <p>
        You can also build a multi-file artifact with
        <code>add_file()</code>/<code>add_dir()</code>. Logged artifacts list
        here, grouped by type, with their versions and files.
      </p>
    </div>
  {:else}
    <h2 class="page-title">Artifacts</h2>
    <p class="page-subtitle">
      Showing artifacts logged across all runs in this project.
    </p>

    {#each groups as group}
      <div class="type-group">
        <div class="type-heading">
          {group.type}
          <span class="type-count">{group.items.length}</span>
        </div>
        <div class="artifact-list">
          {#each group.items as artifact}
            {@const latest = artifact.versions[0]}
            <div
              class="artifact-item"
              id={"artifact-" + artifact.name}
              class:expanded={expanded[artifact.name]}
            >
              <button
                class="artifact-row"
                onclick={() => toggleArtifact(artifact.name)}
              >
                <span class="chevron" class:open={expanded[artifact.name]}
                  >▸</span
                >
                <span class="artifact-name">{artifact.name}</span>
                {#if latest}
                  <span class="version-badge">v{latest.version}</span>
                {/if}
                <span class="spacer"></span>
                <span class="artifact-meta">
                  {artifact.num_versions}
                  {artifact.num_versions === 1 ? "version" : "versions"}
                </span>
                {#if latest}
                  <span class="artifact-meta">{formatSize(latest.size_bytes)}</span
                  >
                {/if}
              </button>

              {#if expanded[artifact.name]}
                <div class="version-list">
                  {#if artifact.description}
                    <p class="artifact-description">{artifact.description}</p>
                  {/if}
                  {#each artifact.versions as version}
                    {@const vkey = verKey(artifact.name, version.version)}
                    <div class="version-item" class:expanded={expandedVer[vkey]}>
                      <button
                        class="version-row"
                        onclick={() => toggleVersion(artifact.name, version)}
                      >
                        <span class="chevron" class:open={expandedVer[vkey]}
                          >▸</span
                        >
                        <span class="version-label">v{version.version}</span>
                        <span class="alias-pills">
                          {#each version.aliases as alias}
                            <span
                              class="alias-pill"
                              class:latest={alias === "latest"}>{alias}</span
                            >
                          {/each}
                        </span>
                        <span class="spacer"></span>
                        <span class="version-meta">
                          {version.num_files}
                          {version.num_files === 1 ? "file" : "files"}
                        </span>
                        <span class="version-meta"
                          >{formatSize(version.size_bytes)}</span
                        >
                        <span class="version-meta"
                          >{formatDate(version.created_at)}</span
                        >
                      </button>

                      {#if expandedVer[vkey]}
                        <div class="version-detail">
                          <div class="detail-grid">
                            {#if version.producer_run_name}
                              <span class="detail-key">Produced by</span>
                              <span class="detail-val">
                                <button
                                  class="run-link"
                                  onclick={() =>
                                    openRun(
                                      version.producer_run_name,
                                      version.producer_run_id,
                                    )}>{version.producer_run_name}</button
                                >
                              </span>
                            {/if}
                            {#if consumers[vkey]?.runs?.length}
                              <span class="detail-key">Used by</span>
                              <span class="detail-val">
                                {#each consumers[vkey].runs as c, ci}<button
                                    class="run-link"
                                    onclick={() =>
                                      openRun(
                                        c.run_name,
                                        c.run_id,
                                      )}>{c.run_name ?? c.run_id}</button
                                  >{ci < consumers[vkey].runs.length - 1
                                    ? ", "
                                    : ""}{/each}
                              </span>
                            {/if}
                            <span class="detail-key">Digest</span>
                            <span class="detail-val mono"
                              >{version.manifest_digest?.slice(0, 16)}…</span
                            >
                            {#if version.metadata && Object.keys(version.metadata).length}
                              {#each Object.entries(version.metadata) as [k, v]}
                                <span class="detail-key">{k}</span>
                                <span class="detail-val"
                                  >{typeof v === "object"
                                    ? JSON.stringify(v)
                                    : String(v)}</span
                                >
                              {/each}
                            {/if}
                          </div>

                          <div class="file-table">
                            {#if manifests[vkey]?.loading}
                              <div class="file-status">Loading files…</div>
                            {:else if manifests[vkey]?.error}
                              <div class="file-status">
                                Failed to load files.
                              </div>
                            {:else if manifests[vkey]?.files}
                              {#each manifests[vkey].files as file}
                                <div class="file-entry">
                                  <span class="file-path">{file.path}</span>
                                  <span class="spacer"></span>
                                  <span class="file-size"
                                    >{formatSize(file.size)}</span
                                  >
                                  <a
                                    class="download-btn"
                                    href={getArtifactBlobUrl(
                                      project,
                                      file.digest,
                                    )}
                                    download={file.path}
                                    title="Download"
                                  >
                                    <svg
                                      width="16"
                                      height="16"
                                      viewBox="0 0 16 16"
                                      fill="none"
                                    >
                                      <path
                                        d="M8 1v9m0 0L5 7m3 3l3-3M2 12v1a2 2 0 002 2h8a2 2 0 002-2v-1"
                                        stroke="currentColor"
                                        stroke-width="1.5"
                                        stroke-linecap="round"
                                        stroke-linejoin="round"
                                      />
                                    </svg>
                                  </a>
                                </div>
                              {/each}
                            {/if}
                          </div>
                        </div>
                      {/if}
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          {/each}
        </div>
      </div>
    {/each}
  {/if}
</div>

<style>
  .artifacts-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }
  .page-title {
    color: var(--body-text-color, #1f2937);
    font-size: 16px;
    font-weight: 700;
    margin: 0 0 4px;
  }
  .page-subtitle {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-sm, 12px);
    margin: 0 0 16px;
  }
  .type-group {
    margin-bottom: 20px;
  }
  .type-heading {
    display: flex;
    align-items: center;
    gap: 8px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: var(--text-xs, 11px);
    font-weight: 600;
    color: var(--body-text-color-subdued, #6b7280);
    margin: 0 0 8px;
  }
  .type-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    border-radius: 9px;
    background: var(--background-fill-secondary, #f3f4f6);
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-xs, 10px);
    letter-spacing: 0;
  }
  .artifact-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .artifact-item {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    background: var(--background-fill-primary, white);
    overflow: hidden;
  }
  .artifact-item.expanded {
    border-color: var(--color-accent, #f97316);
  }
  .artifact-row,
  .version-row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-md, 14px);
    padding: 10px 14px;
  }
  .artifact-row:hover,
  .version-row:hover {
    background: var(--background-fill-secondary, #f9fafb);
  }
  .chevron {
    flex-shrink: 0;
    color: var(--body-text-color-subdued, #9ca3af);
    font-size: 11px;
    transition: transform 0.12s ease;
  }
  .chevron.open {
    transform: rotate(90deg);
  }
  .artifact-name {
    font-weight: 600;
  }
  .spacer {
    flex: 1 1 auto;
  }
  .version-badge {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: var(--text-xs, 11px);
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-secondary, #f3f4f6);
    border-radius: var(--radius-sm, 4px);
    padding: 1px 6px;
  }
  .artifact-meta,
  .version-meta {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
    white-space: nowrap;
  }
  .version-list {
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-secondary, #f9fafb);
    padding: 6px 8px 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .artifact-description {
    margin: 4px 6px 8px;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .version-item {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, white);
    overflow: hidden;
  }
  .version-label {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-weight: 600;
    flex-shrink: 0;
  }
  .alias-pills {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
  }
  .alias-pill {
    font-size: var(--text-xs, 11px);
    padding: 1px 7px;
    border-radius: 9px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-secondary, #f3f4f6);
    white-space: nowrap;
  }
  .alias-pill.latest {
    color: var(--color-accent, #f97316);
    border-color: var(--color-accent, #f97316);
    background: transparent;
  }
  .version-detail {
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
    padding: 10px 14px 12px;
    background: var(--background-fill-secondary, #f9fafb);
  }
  .detail-grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 2px 16px;
    margin-bottom: 10px;
  }
  .detail-key {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .detail-val {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    word-break: break-word;
  }
  .mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .run-link {
    background: none;
    border: none;
    padding: 0;
    font-size: var(--text-sm, 12px);
    color: var(--color-accent, #f97316);
    cursor: pointer;
    text-align: left;
  }
  .run-link:hover {
    text-decoration: underline;
  }
  .file-table {
    display: flex;
    flex-direction: column;
  }
  .file-entry {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
  }
  .file-entry:first-child {
    border-top: none;
  }
  .file-path {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    word-break: break-all;
  }
  .file-size {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
    white-space: nowrap;
  }
  .download-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    flex-shrink: 0;
    border-radius: var(--radius-md, 6px);
    color: var(--body-text-color-subdued, #6b7280);
    transition:
      background-color 0.15s,
      color 0.15s;
  }
  .download-btn:hover {
    background: var(--background-fill-primary, #fff);
    color: var(--color-accent, #f97316);
  }
  .file-status {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
    padding: 6px 0;
  }
  .empty-state {
    max-width: 640px;
    padding: 40px 24px;
    color: var(--body-text-color, #1f2937);
  }
  .empty-state h2 {
    margin: 0 0 8px;
    font-size: 20px;
    font-weight: 700;
  }
  .empty-state p {
    margin: 12px 0 8px;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .empty-state pre {
    background: var(--background-fill-secondary, #f9fafb);
    padding: 16px;
    border-radius: var(--radius-lg, 8px);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    font-size: 13px;
    overflow-x: auto;
  }
  .empty-state code {
    background: var(--background-fill-secondary, #f0f0f0);
    padding: 1px 5px;
    border-radius: var(--radius-sm, 4px);
    font-size: 13px;
  }
  .empty-state pre code {
    background: none;
    padding: 0;
  }
</style>
