<script>
  import { tick } from "svelte";
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import ArtifactVersionDetail from "../components/ArtifactVersionDetail.svelte";
  import { listArtifacts } from "../lib/api.js";
  import { getQueryParam } from "../lib/router.js";

  let { project = null } = $props();

  let artifacts = $state([]);
  let loading = $state(false);
  let expanded = $state({});
  let expandedVer = $state({});

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

  function toggleArtifact(name) {
    const opening = !expanded[name];
    expanded[name] = opening;
    if (opening) {
      const latest = artifacts.find((a) => a.name === name)?.versions?.[0];
      if (latest) expandedVer[verKey(name, latest.version)] = true;
    }
  }

  function toggleVersion(name, version) {
    const key = verKey(name, version);
    expandedVer[key] = !expandedVer[key];
  }

  async function loadArtifacts() {
    expanded = {};
    expandedVer = {};
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
            <div class="artifact-item" id={"artifact-" + artifact.name}>
              <button
                class="artifact-row"
                onclick={() => toggleArtifact(artifact.name)}
              >
                <span class="chevron" class:open={expanded[artifact.name]}
                  >▾</span
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
                    <div class="version-item">
                      <button
                        class="version-row"
                        onclick={() =>
                          toggleVersion(artifact.name, version.version)}
                      >
                        <span class="chevron" class:open={expandedVer[vkey]}
                          >▾</span
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
                        <ArtifactVersionDetail
                          {project}
                          name={artifact.name}
                          version={version.version}
                        />
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
    --artifacts-max-width: 860px;
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }
  .page-title {
    color: var(--body-text-color, #1f2937);
    font-size: 16px;
    font-weight: 700;
    margin: 0 0 4px;
    max-width: var(--artifacts-max-width);
  }
  .page-subtitle {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-sm, 12px);
    margin: 0 0 16px;
    max-width: var(--artifacts-max-width);
  }
  .type-group {
    margin-bottom: 20px;
    max-width: var(--artifacts-max-width);
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
    display: inline-block;
    color: var(--body-text-color, #1f2937);
    font-size: 14px;
    transition: transform 0.15s;
    transform: rotate(-90deg);
  }
  .chevron.open {
    transform: none;
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
