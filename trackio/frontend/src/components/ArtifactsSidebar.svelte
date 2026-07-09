<script>
  import { tick } from "svelte";
  import ProjectSelector from "./ProjectSelector.svelte";
  import Logo from "./Logo.svelte";
  import IndentGuides from "./IndentGuides.svelte";
  import { listArtifacts } from "../lib/api.js";
  import {
    getArtifactSelectionFromUrl,
    setArtifactSelectionParams,
  } from "../lib/router.js";

  let {
    project = $bindable(null),
    projects = [],
    projectLocked = false,
    logoUrls = undefined,
    darkMode = false,
    selection = $bindable(null),
    // eslint-disable-next-line no-useless-assignment -- write-only bindable output
    empty = $bindable(false),
  } = $props();

  let artifacts = $state([]);
  let loading = $state(false);
  let error = $state(false);
  let search = $state("");
  let expandedTypes = $state({});
  let expandedArtifacts = $state({});

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

  // Type groups are expanded by default; only an explicit collapse hides them.
  function typeOpen(type) {
    return searching || expandedTypes[type] !== false;
  }

  function artifactOpen(name) {
    return searching || !!expandedArtifacts[name];
  }

  function toggleType(type) {
    if (searching) return;
    expandedTypes[type] = !typeOpen(type);
  }

  function toggleArtifact(name) {
    if (searching) return;
    expandedArtifacts[name] = !expandedArtifacts[name];
  }

  function selectVersion(artifact, version) {
    selection = { name: artifact.name, version: version.version };
    setArtifactSelectionParams(artifact.name, version.version);
  }

  function isSelected(name, version) {
    return selection && selection.name === name && selection.version === version;
  }

  async function applyInitialSelection() {
    const target = getArtifactSelectionFromUrl();
    let artifact = target.name
      ? artifacts.find((a) => a.name === target.name)
      : null;
    if (!artifact) artifact = artifacts[0];
    if (!artifact || !artifact.versions.length) return;

    let version =
      target.version != null
        ? artifact.versions.find((v) => v.version === target.version)
        : null;
    if (!version) version = artifact.versions[0];

    expandedArtifacts[artifact.name] = true;
    selectVersion(artifact, version);

    await tick();
    document
      .getElementById("tree-" + verKey(artifact.name, version.version))
      ?.scrollIntoView({ block: "nearest" });
  }

  let loadSeq = 0;

  async function loadArtifacts() {
    const seq = ++loadSeq;
    expandedTypes = {};
    expandedArtifacts = {};
    selection = null;
    empty = false;
    error = false;
    if (!project) {
      artifacts = [];
      return;
    }
    loading = true;
    try {
      const result = await listArtifacts(project);
      if (seq !== loadSeq) return;
      artifacts = result;
    } catch {
      if (seq !== loadSeq) return;
      artifacts = [];
      error = true;
    } finally {
      if (seq === loadSeq) loading = false;
    }
    empty = !error && artifacts.length === 0;
    if (!error && artifacts.length) {
      await applyInitialSelection();
    }
  }

  $effect(() => {
    project;
    loadArtifacts();
  });
</script>

{#snippet chevronIcon()}
  <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true"
    ><path d="M4 3L8 6 4 9Z" fill="currentColor" /></svg
  >
{/snippet}

<aside class="artifacts-sidebar">
  <div class="tree-header">
    <Logo {logoUrls} {darkMode} />
    <ProjectSelector {projects} bind:selectedProject={project} {projectLocked} />
    <div class="tree-search">
      <span class="search-label">Artifacts</span>
      <div class="search-box">
        <svg
          class="search-icon"
          width="14"
          height="14"
          viewBox="0 0 16 16"
          fill="none"
        >
          <circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.5" />
          <path
            d="M11 11l3 3"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
          />
        </svg>
        <input type="text" placeholder="Search artifacts…" bind:value={search} />
        {#if search}
          <button
            class="clear-search"
            onclick={() => (search = "")}
            title="Clear search">×</button
          >
        {/if}
      </div>
    </div>
  </div>

  <div class="tree">
    {#if loading}
      <div class="tree-empty">Loading…</div>
    {:else if error}
      <div class="tree-empty">Couldn't load artifacts.</div>
    {:else if artifacts.length === 0}
      <div class="tree-empty">No artifacts in this project.</div>
    {:else if filteredGroups.length === 0}
      <div class="tree-empty">No artifacts match “{search}”.</div>
    {:else}
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
                  <IndentGuides depth={1} />
                  <span class="chevron" class:open={artifactOpen(artifact.name)}
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
                      <IndentGuides depth={2} />
                      <span class="tree-chevron-spacer"></span>
                      <span class="version-label">v{version.version}</span>
                      {#each version.aliases as alias}
                        <span class="alias-pill" class:latest={alias === "latest"}
                          >{alias}</span
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
    {/if}
  </div>
</aside>

<style>
  .artifacts-sidebar {
    width: 300px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-primary, #fff);
    overflow: hidden;
  }

  .tree-header {
    padding: 16px 16px 10px;
    flex-shrink: 0;
  }

  .tree-search {
    margin-top: 14px;
  }
  .search-label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--body-text-color-subdued, #6b7280);
    margin-bottom: 6px;
  }
  .search-box {
    position: relative;
    display: flex;
    align-items: center;
  }
  .search-icon {
    position: absolute;
    left: 10px;
    color: var(--body-text-color-subdued, #9ca3af);
    pointer-events: none;
  }
  .search-box input {
    width: 100%;
    padding: 6px 26px 6px 30px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-secondary, #f9fafb);
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-sm, 13px);
    outline: none;
  }
  .search-box input:focus {
    border-color: var(--color-accent, #f97316);
  }
  .clear-search {
    position: absolute;
    right: 8px;
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
</style>
