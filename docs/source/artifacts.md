# Artifacts

## Introduction

An **artifact** is a versioned, named bundle of files attached to a project — a trained model, a dataset, a set of evaluation outputs. Logging files as artifacts (rather than leaving them on disk) gives you:

- **Versioning** — each time you log under the same name, Trackio records a new version (`v0`, `v1`, ...). Identical content is de-duplicated, so re-logging unchanged files reuses the existing version.
- **Aliases** — moving pointers such as `latest` (assigned automatically) or your own (`prod`, `best`) that always resolve to a single version.
- **Lineage** — artifacts are linked to the runs that produced and consumed them, so you can trace which run created a model and which runs used it.

Artifacts work fully offline against local storage, and sync to a Hugging Face Space (or self-hosted server) when one is configured, exactly like metrics.

## Logging an artifact

The quickest way is to log a file or directory directly. This creates a new artifact, adds the path, and records it as an output of the current run:

```python
import trackio

trackio.init(project="my_project")

# ... training ...

trackio.log_artifact("checkpoints/model.safetensors", type="model")
```

When you pass a path, the artifact `name` defaults to `run-<run_id>-<basename>` and `type` defaults to `"unspecified"`. Pass `name` and `type` to set them explicitly:

```python
trackio.log_artifact("checkpoints/", name="my-model", type="model")
```

### Artifact types

Artifact `type` is a free-form category string. Trackio does not enforce a fixed list of types, but common conventions are:

| Type | Use it for |
| --- | --- |
| `"model"` | Model checkpoints, adapter weights, tokenizers, model configs |
| `"dataset"` | Training, validation, test, or generated datasets |
| `"evaluation"` | Evaluation outputs, predictions, benchmark results, score files |
| `"report"` | Figures, plots, tables, notebooks, or human-readable analysis bundles |
| `"unspecified"` | The default when no type is provided |

Use stable type names within a project so you can filter artifacts consistently and use `trackio.use_artifact(..., type="...")` to assert that a run is consuming the expected kind of artifact.

### Building an artifact explicitly

For finer control — multiple files, custom logical paths, a description, or metadata — construct an [`Artifact`], add files to it, then log it:

```python
artifact = trackio.Artifact(
    name="my-model",
    type="model",
    description="Fine-tuned on the v2 dataset",
    metadata={"base_model": "bert-base", "epochs": 3},
)
artifact.add_file("checkpoints/model.safetensors")
artifact.add_file("checkpoints/config.json")
artifact.add_dir("tokenizer/")

logged = trackio.log_artifact(artifact)
```

After logging, the artifact is frozen and its `version`, `aliases`, `size`, and `manifest` are populated:

```python
print(logged.version)   # "v0"
print(logged.aliases)   # ("latest",)
```

### Versions and aliases

Each log under an existing name creates the next integer version and moves the `latest` alias onto it. Assign your own aliases with `aliases=`:

```python
trackio.log_artifact(artifact, aliases=["prod", "best"])
```

Aliases are moving pointers: logging a new version with the same alias re-points it. Version specifiers (`v0`, `v1`, ...) are reserved and cannot be used as aliases.

If you log content identical to an existing version, Trackio reuses that version instead of creating a new one. Any explicit `aliases` you pass still rotate onto it, but `latest` is left where it is — re-logging identical (or older) content never moves it backward.

## Using an artifact

[`use_artifact`] fetches an artifact and records it as an **input** to the current run, which is what builds lineage between a consuming run and the artifact it used:

```python
trackio.init(project="my_project")

artifact = trackio.use_artifact("my-model")          # resolves to :latest
artifact = trackio.use_artifact("my-model:v2")       # pin a version
artifact = trackio.use_artifact("my-model:prod")     # resolve an alias
```

Pass `type` to assert the artifact's type, raising if it doesn't match:

```python
artifact = trackio.use_artifact("my-model", type="model")
```

### Downloading files

`use_artifact` returns an [`Artifact`] whose files you materialize with `download()`:

```python
artifact = trackio.use_artifact("my-model:latest")
path = artifact.download()
# files are now under ./.trackio/artifact-downloads/my_project/my-model_v2/
```

By default, files are written to `./.trackio/artifact-downloads/<project>/<name>_v<version>/`, keyed by project so same-named artifacts from different projects never collide; pass `root` to choose another directory. `download()` is idempotent — files already present are skipped — and when the run is backed by a Space, any file missing locally is fetched from the remote.

## Referencing external data

Some data is too large to copy, or already lives in durable storage you don't want duplicated. `add_reference` records such data by **URI** in the manifest *without staging any bytes* into Trackio's storage, so you still get versioning, de-duplication, aliases, and lineage over data that never moves:

```python
artifact = trackio.Artifact(name="training-set", type="dataset")
artifact.add_reference("file:///mnt/nvme/datasets/corpus.parquet")
artifact.add_reference("s3://my-bucket/shards/")                       # a prefix — expands to one entry per object
artifact.add_reference("gs://my-bucket/eval.json")
artifact.add_reference("hf://datasets/username/my-dataset/train.parquet")
trackio.log_artifact(artifact)
```

Supported schemes are `file://`, `http(s)://`, `hf://`, `s3://`, `gs://`, and Azure blob URLs (`https://<account>.blob.core.windows.net/...`). With `checksum=True` (the default), Trackio probes the source to fill in `size` and a checksum:

- `file://` is stream-hashed to a sha256; its size is read from disk.
- `hf://` uses the LFS sha256 (or the git blob id); `http(s)://` and the cloud stores use the server `ETag`.
- `http(s)://` and `hf://` need no extra dependency. `s3://`, `gs://`, and private Azure blobs use optional SDKs — `pip install trackio[s3]`, `trackio[gcs]`, or `trackio[azure]`; a *public* Azure blob works with no SDK (Trackio falls back to a plain HTTPS request).

Every checksum is stored in a single `digest` field — the sha256 for local/LFS references, or the provider's ETag for cloud/HTTP references.

A URI that denotes a directory (`file://`) or an object prefix (`s3://`, `gs://`, `hf://`, Azure) is **expanded** into one reference entry per object, each named by its path relative to the prefix (nested under `name=` when given). `max_objects` (default 10,000) caps the expansion and raises if exceeded.

When no checksum can be obtained — a server with no `ETag`, a cloud object whose SDK isn't installed, or an unrecognized scheme like `dvc://` — the reference is still recorded, using **the URI itself as the `digest`**, and a warning is emitted. A local `file://` path that doesn't exist is the exception: it raises rather than being recorded, since a missing local file is almost always a mistake — use `add_file` to stage a local file. Pass `checksum=False` to skip the per-object checksum — a single object then records just its URI, while an object-store prefix still expands (each object's `digest` set to its URI); `size=` / `digest=` to supply values for a single object; and `name=` to set the logical path.

A reference's version identity comes from its URI, size, and `digest`, so re-logging identical references de-duplicates to one version, while a changed URI, size, or checksum creates a new one — exactly like file content. When the URI is used as the `digest`, identity therefore tracks the URI and not the content.

Reference bytes are never uploaded to a Space or bucket, but they can be fetched on demand. `download()` downloads each referenced object into the directory (via `httpx`, `huggingface_hub`, or the cloud SDK), which can transfer a large amount of data; each object is verified against its recorded checksum (a source that changed since it was logged raises), written atomically, and one already present on disk is skipped, so repeated calls are cheap and idempotent:

```python
artifact = trackio.use_artifact("training-set:latest")
path = artifact.download()   # downloads staged files AND referenced objects
```

To work with the pointers *without* downloading, read them from the artifact instead:

```python
print(artifact.references)                  # [{'path': ..., 'ref': 's3://...', 'size': ..., 'digest': ...}, ...]
print(artifact.get_entry_uri("eval.json"))  # "gs://my-bucket/eval.json"
```

An unfetchable reference (a missing local file, an unreachable URL, a missing SDK, or an opaque-pointer scheme) raises when `download()` reaches it.

## Remote storage

When your run targets a Hugging Face Space or self-hosted server (see [Track](track.md)), artifact files are content-addressed and uploaded once: Trackio skips blobs the server already has, so re-logging shared files is cheap. Artifact metadata and blobs are persisted alongside your other run data to the configured HF Dataset or bucket.
