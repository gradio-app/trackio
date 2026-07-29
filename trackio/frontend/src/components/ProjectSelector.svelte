<script>
  import Dropdown from "./Dropdown.svelte";

  let {
    projects = [],
    selectedProject = $bindable(null),
    projectLocked = false,
  } = $props();
</script>

{#if projectLocked}
  <div class="section-label">Project</div>
  <div class="locked-project">{selectedProject ?? "—"}</div>
{:else}
  <Dropdown
    label="Project"
    choices={projects}
    bind:value={selectedProject}
    filterable={true}
  />
{/if}

<style>
  .section-label {
    font-size: 13px;
    font-weight: 500;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .locked-project {
    margin-top: 4px;
    font-size: 13px;
    font-weight: 500;
    color: var(--body-text-color, #1f2937);
    padding: 8px 10px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-secondary, #f9fafb);
  }
</style>
