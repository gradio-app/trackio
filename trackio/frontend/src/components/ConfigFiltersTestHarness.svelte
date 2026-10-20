<script>
  import ConfigFilters from "./ConfigFilters.svelte";
  let configs = $state({ a: { size: 32 } });
</script>
<button onclick={() => { configs = { a: { size: 64 } }; }}>Poll configs</button>
<ConfigFilters {configs} />
