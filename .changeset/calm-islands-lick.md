---
"trackio": minor
---

feat: Add an interactive artifact lineage graph to the dashboard. Each artifact version's detail view now includes a Lineage section rendering the version's lineage of runs and artifact versions as a left-to-right DAG, with pan/zoom, a click-to-preview panel, and navigation to runs and versions. Groups of five or more similarly-connected nodes collapse into searchable cluster nodes that individual runs or versions can be extracted from. Backed by a new `get_artifact_lineage` API endpoint with full static-mode (parquet) parity.
