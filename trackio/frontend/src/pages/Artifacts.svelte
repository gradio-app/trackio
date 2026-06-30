<script>
  import { tick } from "svelte";
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import ArtifactVersionDetail from "../components/ArtifactVersionDetail.svelte";
  import { listArtifacts } from "../lib/api.js";
  import { getQueryParam, setQueryParam } from "../lib/router.js";

  let { project = null } = $props();

  let artifacts = $state([]);
  let loading = $state(false);
  let error = $state(false);
  let search = $state("");
  let expandedTypes = $state({});
  let expandedArtifacts = $state({});
  let selected = $state(null);

  function verKey(name, version) {
    return `${name}@v${version}`;
  }

  let filteredGroups = $derived.by(() => {
    const q = search.trim().toLowerCase();
    const byType = new Map();
    for (const a of artifacts) {
      if (
        q &&
        !a.name.toLowerCase().includes(q) &&
        !a.type.toLowerCase().includes(q)
      )
        continue;
      if (!byType.has(a.type)) byType.set(a.type, []);
      byType.get(a.type).push(a);
    }
    return [...byType.entries()].map(([type, items]) => ({
      type,
      artifacts: items,
    }));
  });

  let searching = $derived(search.trim().length > 0);

  function typeOpen(type) {
    return searching || !!expandedTypes[type];
  }

  function artifactOpen(name) {
    return searching || !!expandedArtifacts[name];
  }

  function toggleType(type) {
    if (searching) return;
    expandedTypes[type] = !expandedTypes[type];
  }

  function toggleArtifact(name) {
    if (searching) return;
    expandedArtifacts[name] = !expandedArtifacts[name];
  }

  function selectVersion(artifact, version) {
    selected = {
      name: artifact.name,
      version: version.version,
      type: artifact.type,
    };
    setQueryParam("selected_artifact", artifact.name);
    setQueryParam("selected_version", `v${version.version}`);
  }

  function isSelected(name, version) {
    return (
      selected && selected.name === name && selected.version === version
    );
  }

  async function applyInitialSelection() {
    const target = getQueryParam("selected_artifact");
    const verParam = getQueryParam("selected_version");
    let artifact = target ? artifacts.find((a) => a.name === target) : null;
    if (!artifact) artifact = artifacts[0];
    if (!artifact || !artifact.versions.length) return;

    let version = null;
    if (verParam) {
      const vnum = parseInt(String(verParam).replace(/^v/i, ""), 10);
      version = artifact.versions.find((v) => v.version === vnum);
    }
    if (!version) version = artifact.versions[0];

    expandedTypes[artifact.type] = true;
    expandedArtifacts[artifact.name] = true;
    selectVersion(artifact, version);

    await tick();
    document
      .getElementById("tree-" + verKey(artifact.name, version.version))
      ?.scrollIntoView({ block: "nearest" });
  }

  async function loadArtifacts() {
    expandedTypes = {};
    expandedArtifacts = {};
    selected = null;
    error = false;
    if (!project) {
      artifacts = [];
      return;
    }
    loading = true;
    try {
      artifacts = await listArtifacts(project);
    } catch {
      artifacts = [];
      error = true;
    } finally {
      loading = false;
    }
    if (!error && artifacts.length) {
      await applyInitialSelection();
    }
  }

  $effect(() => {
    project;
    loadArtifacts();
  });
</script>

{#snippet treeGuides(depth)}
  <span class="indent"
    >{#each Array.from({ length: depth }) as _}<span class="indent-guide"
      ></span>{/each}</span
  >
{/snippet}

{#snippet chevronIcon()}
  <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true"
    ><path d="M4 3L8 6 4 9Z" fill="currentColor" /></svg
  >
{/snippet}

<div class="artifacts-page">
  {#if loading}
    <LoadingTrackio />
  {:else if error}
    <div class="empty-state">
      <h2>Couldn't load artifacts</h2>
      <p>
        Something went wrong fetching artifacts for this project. Try reloading
        the page.
      </p>
    </div>
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
    <div class="artifacts-layout">
      <aside class="tree-pane">
        <div class="tree-search">
          <svg
            class="search-icon"
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
          >
            <circle
              cx="7"
              cy="7"
              r="5"
              stroke="currentColor"
              stroke-width="1.5"
            />
            <path
              d="M11 11l3 3"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
            />
          </svg>
          <input
            type="text"
            placeholder="Search artifacts…"
            bind:value={search}
          />
          {#if search}
            <button
              class="clear-search"
              onclick={() => (search = "")}
              title="Clear search">×</button
            >
          {/if}
        </div>

        <div class="tree">
          {#if filteredGroups.length === 0}
            <div class="tree-empty">No artifacts match “{search}”.</div>
          {/if}
          {#each filteredGroups as group}
            <div class="tree-type">
              <button
                class="tree-row type-row"
                onclick={() => toggleType(group.type)}
              >
                <span class="chevron" class:open={typeOpen(group.type)}
                  >{@render chevronIcon()}</span
                >
                <span class="type-label">{group.type}</span>
                <span class="spacer"></span>
                <span class="node-count">{group.artifacts.length}</span>
              </button>

              {#if typeOpen(group.type)}
                {#each group.artifacts as artifact}
                  <div class="tree-artifact">
                    <button
                      class="tree-row artifact-row"
                      onclick={() => toggleArtifact(artifact.name)}
                    >
                      {@render treeGuides(1)}
                      <span
                        class="chevron"
                        class:open={artifactOpen(artifact.name)}
                        >{@render chevronIcon()}</span
                      >
                      <span class="artifact-label" title={artifact.name}
                        >{artifact.name}</span
                      >
                      <span class="spacer"></span>
                      <span class="node-count">{artifact.num_versions}</span>
                    </button>

                    {#if artifactOpen(artifact.name)}
                      {#each artifact.versions as version}
                        <button
                          id={"tree-" + verKey(artifact.name, version.version)}
                          class="tree-row version-row"
                          class:selected={isSelected(
                            artifact.name,
                            version.version,
                          )}
                          onclick={() => selectVersion(artifact, version)}
                        >
                          {@render treeGuides(2)}
                          <span class="tree-chevron-spacer"></span>
                          <span class="version-label">v{version.version}</span>
                          {#each version.aliases as alias}
                            <span
                              class="alias-pill"
                              class:latest={alias === "latest"}>{alias}</span
                            >
                          {/each}
                        </button>
                      {/each}
                    {/if}
                  </div>
                {/each}
              {/if}
            </div>
          {/each}
        </div>
      </aside>

      <section class="detail-pane">
        {#if selected}
          {#key verKey(selected.name, selected.version)}
            <ArtifactVersionDetail
              variant="panel"
              {project}
              name={selected.name}
              version={selected.version}
            />
          {/key}
        {:else}
          <div class="detail-empty">
            Select an artifact version to view its details.
          </div>
        {/if}
      </section>
    </div>
  {/if}
</div>

<style>
  .artifacts-page {
    flex: 1;
    min-height: 0;
    display: flex;
    overflow: hidden;
  }

  .artifacts-layout {
    flex: 1;
    min-height: 0;
    display: flex;
    overflow: hidden;
  }

  .tree-pane {
    width: 300px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-primary, #fff);
    overflow: hidden;
  }

  .tree-search {
    position: relative;
    display: flex;
    align-items: center;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    flex-shrink: 0;
  }
  .search-icon {
    position: absolute;
    left: 22px;
    color: var(--body-text-color-subdued, #9ca3af);
    pointer-events: none;
  }
  .tree-search input {
    width: 100%;
    padding: 6px 26px 6px 30px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-secondary, #f9fafb);
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-sm, 13px);
    outline: none;
  }
  .tree-search input:focus {
    border-color: var(--color-accent, #f97316);
  }
  .clear-search {
    position: absolute;
    right: 20px;
    border: none;
    background: none;
    color: var(--body-text-color-subdued, #9ca3af);
    font-size: 18px;
    line-height: 1;
    cursor: pointer;
    padding: 0 2px;
  }
  .clear-search:hover {
    color: var(--body-text-color, #1f2937);
  }

  .tree {
    flex: 1;
    overflow-y: auto;
    padding: 6px 0 12px;
  }
  .tree-empty {
    padding: 16px 14px;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }

  .tree-row {
    display: flex;
    align-items: center;
    width: 100%;
    min-height: 30px;
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-sm, 13px);
    padding: 0 12px;
    border-radius: 0;
  }
  .tree-row:hover {
    background: var(--background-fill-secondary, #f3f4f6);
  }

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
  .tree-chevron-spacer {
    display: inline-block;
    width: 12px;
    margin-right: 6px;
    flex-shrink: 0;
  }

  .chevron {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-right: 6px;
    color: var(--body-text-color-subdued, #6b7280);
    width: 12px;
    height: 12px;
    transition: transform 0.15s;
  }
  .chevron.open {
    transform: rotate(90deg);
  }

  .type-label {
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: var(--text-xs, 11px);
    font-weight: 700;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .artifact-label {
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .version-label {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-weight: 600;
    flex-shrink: 0;
  }
  .version-row .alias-pill {
    margin-left: 6px;
  }

  .spacer {
    flex: 1 1 auto;
  }
  .node-count {
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
    flex-shrink: 0;
  }

  .version-row.selected {
    background: var(--background-fill-secondary, #f3f4f6);
    box-shadow: inset 3px 0 0 var(--color-accent, #f97316);
  }
  .version-row.selected .version-label {
    color: var(--color-accent, #f97316);
  }

  .alias-pill {
    font-size: var(--text-xs, 10px);
    padding: 0 6px;
    border-radius: 9px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-secondary, #f3f4f6);
    white-space: nowrap;
    line-height: 16px;
  }
  .alias-pill.latest {
    color: var(--color-accent, #f97316);
    border-color: var(--color-accent, #f97316);
    background: transparent;
  }

  .detail-pane {
    flex: 1;
    min-width: 0;
    overflow-y: auto;
    padding: 20px 28px;
  }
  .detail-empty {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-sm, 13px);
    padding: 12px 0;
  }

  .empty-state {
    max-width: 640px;
    padding: 40px 24px;
    overflow-y: auto;
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
