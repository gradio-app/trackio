# Storage Schema and Direct Queries

Trackio stores each project in its own SQLite database and can export that data to parquet for syncing, static Spaces, and direct analysis. This page documents the live SQLite schema, the derived parquet layout, and the new `trackio query` command for running read-only SQL.

## Where Data Lives

- Local project databases live in `TRACKIO_DIR`, which defaults to `~/.cache/huggingface/trackio`.
- Each project is stored as a separate SQLite file: `{project}.db`.
- Media and uploaded files live under `TRACKIO_DIR/media/`.
- When syncing to Hugging Face, Trackio exports parquet files from the SQLite database before upload.

## Querying Data Directly

Use the CLI when you need a catch-all query that is not already covered by `trackio list` or `trackio get`:

```sh
trackio query project --project "my-project" --sql "SELECT run_name, MAX(step) AS last_step FROM metrics GROUP BY run_name ORDER BY last_step DESC"
```

Add `--json` for machine-readable output:

```sh
trackio query project --project "my-project" --sql "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name" --json
```

The same command works against a remote Space:

```sh
trackio query project --project "my-project" --sql "SELECT COUNT(*) AS num_alerts FROM alerts" --space username/my-space --json
```

`trackio query` only accepts read-only `SELECT`, `WITH`, and safe schema `PRAGMA` queries.

## SQLite Schema

The live schema is defined in `trackio/sqlite_storage.py` by `SQLiteStorage.init_db()`.

### `metrics`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `INTEGER` | Primary key |
| `timestamp` | `TEXT` | ISO timestamp |
| `run_name` | `TEXT` | Run identifier |
| `step` | `INTEGER` | Training step |
| `metrics` | `TEXT` | JSON blob containing logged metric values |
| `log_id` | `TEXT` | Optional deduplication key added by additive migration |
| `space_id` | `TEXT` | Optional pending-sync marker added by additive migration |

Indexes:

- `idx_metrics_run_step` on `(run_name, step)`
- `idx_metrics_run_timestamp` on `(run_name, timestamp)`
- `idx_metrics_log_id` unique partial index on `log_id`
- `idx_metrics_pending` partial index on `space_id`

### `configs`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `INTEGER` | Primary key |
| `run_name` | `TEXT` | Run identifier |
| `config` | `TEXT` | JSON blob containing run config |
| `created_at` | `TEXT` | ISO timestamp |

Indexes and constraints:

- `UNIQUE(run_name)`
- `idx_configs_run_name` on `(run_name)`

### `system_metrics`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `INTEGER` | Primary key |
| `timestamp` | `TEXT` | ISO timestamp |
| `run_name` | `TEXT` | Run identifier |
| `metrics` | `TEXT` | JSON blob containing system metrics |
| `log_id` | `TEXT` | Optional deduplication key added by additive migration |
| `space_id` | `TEXT` | Optional pending-sync marker added by additive migration |

Indexes:

- `idx_system_metrics_run_timestamp` on `(run_name, timestamp)`
- `idx_system_metrics_log_id` unique partial index on `log_id`
- `idx_system_metrics_pending` partial index on `space_id`

### `project_metadata`

| Column | Type | Notes |
|--------|------|-------|
| `key` | `TEXT` | Primary key |
| `value` | `TEXT` | Metadata value |

### `pending_uploads`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `INTEGER` | Primary key |
| `space_id` | `TEXT` | Destination Space |
| `run_name` | `TEXT` | Optional run name |
| `step` | `INTEGER` | Optional step |
| `file_path` | `TEXT` | Absolute local path |
| `relative_path` | `TEXT` | Relative media path |
| `created_at` | `TEXT` | ISO timestamp |

### `alerts`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `INTEGER` | Primary key |
| `timestamp` | `TEXT` | ISO timestamp |
| `run_name` | `TEXT` | Run identifier |
| `title` | `TEXT` | Alert title |
| `text` | `TEXT` | Optional alert body |
| `level` | `TEXT` | `info`, `warn`, or `error` |
| `step` | `INTEGER` | Optional training step |
| `alert_id` | `TEXT` | Optional deduplication key |

Indexes:

- `idx_alerts_run` on `(run_name)`
- `idx_alerts_timestamp` on `(timestamp)`
- `idx_alerts_alert_id` unique partial index on `alert_id`

### `artifacts`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `INTEGER` | Primary key |
| `name` | `TEXT` | Artifact name |
| `type` | `TEXT` | Free-form category such as `model` or `dataset` |
| `description` | `TEXT` | Optional description |
| `created_at` | `TEXT` | ISO timestamp |

Indexes and constraints:

- `UNIQUE(name)`

### `artifact_versions`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `INTEGER` | Primary key |
| `artifact_id` | `INTEGER` | References `artifacts.id` |
| `version` | `INTEGER` | Sequential version number starting at 0 |
| `manifest_digest` | `TEXT` | SHA-256 hex digest of the canonical manifest JSON |
| `manifest` | `TEXT` | JSON blob listing manifest entries with `path`, `digest`, `size`, and optional `ref` |
| `metadata` | `TEXT` | Optional JSON metadata |
| `size_bytes` | `INTEGER` | Total size of the version's manifest entries (sum of `size`) in bytes |
| `producer_run_id` | `TEXT` | Optional identifier of the producing run |
| `producer_run_name` | `TEXT` | Optional name of the producing run |
| `created_at` | `TEXT` | ISO timestamp |

Indexes and constraints:

- `UNIQUE(artifact_id, version)`
- `UNIQUE(artifact_id, manifest_digest)`

### `artifact_aliases`

| Column | Type | Notes |
|--------|------|-------|
| `artifact_id` | `INTEGER` | References `artifacts.id` |
| `alias` | `TEXT` | Alias name such as `latest` |
| `artifact_version_id` | `INTEGER` | References `artifact_versions.id` |

Indexes and constraints:

- `PRIMARY KEY (artifact_id, alias)`

### `run_artifact_links`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `INTEGER` | Primary key |
| `run_id` | `TEXT` | Optional run identifier |
| `run_name` | `TEXT` | Optional run name |
| `artifact_version_id` | `INTEGER` | References `artifact_versions.id` |
| `direction` | `TEXT` | `input` or `output` |
| `created_at` | `TEXT` | ISO timestamp |

Indexes and constraints:

- `CHECK(direction IN ('input', 'output'))`
- `idx_run_artifact_links_run` on `(run_id, run_name)`
- `idx_run_artifact_links_version` on `(artifact_version_id)`
- `idx_run_artifact_links_unique` unique index on `(run_id, artifact_version_id, direction)`

## How Metric Payloads Are Stored

- User metrics are stored as JSON text in `metrics.metrics`.
- System metrics are stored as JSON text in `system_metrics.metrics`.
- Run configuration is stored as JSON text in `configs.config`.
- Trackio's higher-level APIs deserialize these JSON blobs before returning them.

Common direct-query pattern:

```sh
trackio query project --project "my-project" --sql "SELECT timestamp, step, metrics FROM metrics WHERE run_name = 'run-1' ORDER BY step DESC LIMIT 5"
```

Schema introspection example:

```sh
trackio query project --project "my-project" --sql "PRAGMA table_info(metrics)"
```

## Parquet Layout

Trackio derives parquet files from SQLite by flattening JSON columns into regular columns.

### Local parquet exports

`SQLiteStorage.export_to_parquet()` writes:

- `{project}.parquet` from `metrics`
- `{project}_system.parquet` from `system_metrics`
- `{project}_configs.parquet` from `configs`
- `{project}_traces.parquet` from `traces`
- `{project}_{table}.parquet` for each artifact table (`artifacts`, `artifact_versions`, `artifact_aliases`, `run_artifact_links`)

The flattened parquet files keep the structural columns such as `timestamp`, `run_name`, and `step`, then add one column per key found in the JSON payload.

### Static Space and dataset exports

`SQLiteStorage.export_for_static_space()` writes:

- `metrics.parquet`
- `aux/system_metrics.parquet`
- `aux/configs.parquet`
- `aux/traces.parquet`
- `aux/artifacts.parquet`, `aux/artifact_versions.parquet`, `aux/artifact_aliases.parquet`, and `aux/run_artifact_links.parquet`
- `runs.json`
- `settings.json`

Static deployment copies media files to `media/` and artifact blobs to `artifacts/blobs/sha256/{prefix}/{digest}` alongside these exports, so the browser-only dashboard can serve artifact downloads directly from the dataset or bucket.

This is the layout used for static Spaces and exported datasets.

## Useful Query Examples

List tables:

```sh
trackio query project --project "my-project" --sql "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
```

Find the latest step for each run:

```sh
trackio query project --project "my-project" --sql "SELECT run_name, MAX(step) AS last_step FROM metrics GROUP BY run_name ORDER BY last_step DESC"
```

Inspect recent alerts:

```sh
trackio query project --project "my-project" --sql "SELECT timestamp, run_name, level, title, step FROM alerts ORDER BY timestamp DESC LIMIT 20"
```

Inspect stored configs:

```sh
trackio query project --project "my-project" --sql "SELECT run_name, created_at, config FROM configs ORDER BY created_at DESC"
```

## Stability Notes

Trackio is still in beta. The schema is documented here so humans and agents can query it directly, but future releases may evolve the schema and require migrations or regenerated local databases.
