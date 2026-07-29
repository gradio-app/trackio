import golden from "./lineage_golden.json";

export { golden };

export function goldenTables() {
  return {
    artifacts: golden.artifacts,
    versions: golden.artifact_versions.map((v) => ({
      ...v,
      manifest: JSON.stringify(v.manifest),
    })),
    aliases: golden.artifact_aliases,
    links: golden.run_artifact_links,
  };
}
