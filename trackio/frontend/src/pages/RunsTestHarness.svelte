<script>
  import Runs from "./Runs.svelte";
  let { onRunsChanged } = $props();
  let project = $state("demo");
  let filterText = $state("");
</script>

<button onclick={() => { project = "other"; }}>Switch project</button>
<button onclick={() => { filterText = "control"; }}>Filter control</button>
<Runs {project} {filterText} {onRunsChanged} />
