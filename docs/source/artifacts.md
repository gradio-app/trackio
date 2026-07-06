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

## Remote storage

When your run targets a Hugging Face Space or self-hosted server (see [Track](track.md)), artifact files are content-addressed and uploaded once: Trackio skips blobs the server already has, so re-logging shared files is cheap. Artifact metadata and blobs are persisted alongside your other run data to the configured HF Dataset or bucket.
