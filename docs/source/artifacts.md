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
artifact.add_reference("file:///mnt/nvme/datasets/shards/")            # a directory — expands to one entry per file
artifact.add_reference("https://example.com/data/eval.json")
artifact.add_reference("hf://datasets/username/my-dataset/train.parquet")
trackio.log_artifact(artifact)
```

Built-in schemes are `file://`, `http(s)://`, and `hf://` — all served by Trackio's existing dependencies. Any other scheme (`s3://`, `gs://`, Azure blob URLs, ...) is supported by registering a custom handler; see [Referencing other stores](#referencing-other-stores-s3-gcs-azure) below for complete S3, GCS, and Azure examples. With `checksum=True` (the default), Trackio probes the source to fill in `size` and a checksum:

- `file://` is stream-hashed to a sha256; its size is read from disk.
- `hf://` uses the LFS sha256 (or the git blob id); `http(s)://` uses the server `ETag`.

Every checksum is stored in a single `digest` field — the sha256 for local/LFS references, or the provider's ETag for HTTP or object-store references.

A URI that denotes a directory (`file://`) or a repo path (`hf://`) is **expanded** into one reference entry per object, each named by its path relative to the prefix (nested under `name=` when given). `max_objects` (default 10,000) caps the expansion and raises if exceeded.

When no checksum can be obtained — for example a server with no `ETag` — the reference is still recorded, using **the URI itself as the `digest`**, and a warning is emitted. A local `file://` path that doesn't exist is the exception: it raises rather than being recorded, since a missing local file is almost always a mistake — use `add_file` to stage a local file. Pass `checksum=False` to skip the per-object checksum — a single object then records just its URI — and `name=` to set the logical path.

A reference's version identity comes from its URI, size, and `digest`, so re-logging identical references de-duplicates to one version, while a changed URI, size, or checksum creates a new one — exactly like file content. When the URI is used as the `digest`, identity therefore tracks the URI and not the content.

URIs are recorded verbatim, and manifests can be synced to a Hugging Face Dataset. A URI that embeds a credential — a presigned `https://` URL or an Azure SAS token — would expose that credential to anyone who can read the Dataset, so `add_reference` warns when a URI's query string looks signed; prefer the object's canonical unsigned URI (e.g. `s3://bucket/key`).

Reference bytes are never uploaded to a Space or bucket, but they can be fetched on demand. `download()` downloads each referenced object into the directory (via `httpx`, `huggingface_hub`, or your registered handler), which can transfer a large amount of data. Before fetching, each object's source is re-probed and its current checksum compared against the recorded one — a mismatch warns that the source may have changed but the download proceeds. Each object is written atomically, and one already present on disk is skipped without re-checking the source, so repeated calls are cheap and idempotent:

```python
artifact = trackio.use_artifact("training-set:latest")
path = artifact.download()   # downloads staged files AND referenced objects
```

To work with the pointers *without* downloading, read them from the artifact instead:

```python
print(artifact.references)                  # [{'path': ..., 'ref': 's3://...', 'size': ..., 'digest': ...}, ...]
print(artifact.get_entry_uri("eval.json"))  # "s3://my-bucket/eval.json"
```

An unfetchable reference (a missing local file, an unreachable URL, or a scheme with no registered handler) raises when `download()` reaches it.

## Referencing other stores (S3, GCS, Azure)

Trackio deliberately ships no cloud-vendor SDKs. To reference objects in a store it doesn't handle natively, subclass `trackio.ReferenceHandler` and register an instance with `trackio.register_reference_handler`. A handler implements four methods:

- `matches(scheme, uri)` — whether this handler owns the URI. Registered handlers are consulted *before* the built-ins, so a handler may also claim specific `https://` hosts (as the Azure example below does) ahead of the generic HTTP handler.
- `resolve(uri, checksum, max_objects)` — probe the source and return a list of `trackio.ResolvedReference` entries: one entry with `relkey=None` for a single object, or one entry per object (with `relkey` set to the object's path relative to the prefix) when the URI denotes a prefix. Set `size` and `digest` when the source can be probed (the provider's ETag works fine as a digest — Trackio treats reference digests as opaque tokens); return them as `None` to record the reference un-checksummed, in which case Trackio falls back to the URI as the digest and warns.
- `fetch(uri, dest)` — download the single object at `uri` to the local path `dest` (called by `Artifact.download()`).
- `hint()` — a one-line actionable message shown in the warning when `resolve` produced no checksum.

Keys discovered during prefix expansion should be percent-encoded when synthesizing each entry's `uri` (and decoded in `fetch`), since manifest URIs may not contain spaces.

### S3 (`s3://`, via `boto3`)

```python
from urllib.parse import quote, unquote, urlsplit

import boto3

import trackio


class S3Handler(trackio.ReferenceHandler):
    def matches(self, scheme, uri):
        return scheme == "s3"

    def resolve(self, uri, checksum, max_objects):
        parts = urlsplit(uri)
        bucket, key = parts.netloc, unquote(parts.path.lstrip("/"))
        client = boto3.client("s3")
        if key and not key.endswith("/"):
            head = client.head_object(Bucket=bucket, Key=key)
            return [
                trackio.ResolvedReference(
                    relkey=None,
                    uri=uri,
                    size=int(head["ContentLength"]),
                    digest=head["ETag"].strip('"') if checksum else None,
                )
            ]
        base = key[: key.rfind("/") + 1]
        entries = []
        pages = client.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=key
        )
        for page in pages:
            for obj in page.get("Contents", []):
                if obj["Key"].endswith("/"):
                    continue
                if len(entries) >= max_objects:
                    raise ValueError(
                        f"{uri} expands to more than {max_objects} objects; "
                        "pass max_objects= to raise the limit."
                    )
                entries.append(
                    trackio.ResolvedReference(
                        relkey=obj["Key"][len(base):],
                        uri=f"s3://{bucket}/{quote(obj['Key'], safe='/')}",
                        size=int(obj["Size"]),
                        digest=obj["ETag"].strip('"') if checksum else None,
                    )
                )
        return entries

    def fetch(self, uri, dest):
        parts = urlsplit(uri)
        with open(dest, "wb") as f:
            boto3.client("s3").download_fileobj(
                parts.netloc, unquote(parts.path.lstrip("/")), f
            )

    def hint(self):
        return "Configure AWS credentials so the object can be probed for an ETag."


trackio.register_reference_handler(S3Handler())

artifact = trackio.Artifact(name="training-set", type="dataset")
artifact.add_reference("s3://my-bucket/shards/")   # expands to one entry per object
trackio.log_artifact(artifact)
```

### Google Cloud Storage (`gs://`, via `google-cloud-storage`)

```python
from urllib.parse import quote, unquote, urlsplit

from google.cloud import storage

import trackio


class GcsHandler(trackio.ReferenceHandler):
    def matches(self, scheme, uri):
        return scheme == "gs"

    def resolve(self, uri, checksum, max_objects):
        parts = urlsplit(uri)
        bucket, key = parts.netloc, unquote(parts.path.lstrip("/"))
        client = storage.Client()
        if key and not key.endswith("/"):
            blob = client.bucket(bucket).get_blob(key)
            if blob is None:
                raise ValueError(f"No such GCS object: {uri}")
            return [
                trackio.ResolvedReference(
                    relkey=None,
                    uri=uri,
                    size=blob.size,
                    digest=blob.etag.strip('"') if checksum else None,
                )
            ]
        base = key[: key.rfind("/") + 1]
        entries = []
        for blob in client.list_blobs(bucket, prefix=key):
            if blob.name.endswith("/"):
                continue
            if len(entries) >= max_objects:
                raise ValueError(
                    f"{uri} expands to more than {max_objects} objects; "
                    "pass max_objects= to raise the limit."
                )
            entries.append(
                trackio.ResolvedReference(
                    relkey=blob.name[len(base):],
                    uri=f"gs://{bucket}/{quote(blob.name, safe='/')}",
                    size=blob.size,
                    digest=blob.etag.strip('"') if checksum else None,
                )
            )
        return entries

    def fetch(self, uri, dest):
        parts = urlsplit(uri)
        key = unquote(parts.path.lstrip("/"))
        storage.Client().bucket(parts.netloc).blob(key).download_to_filename(
            str(dest)
        )

    def hint(self):
        return "Configure GCP credentials so the object can be probed for an ETag."


trackio.register_reference_handler(GcsHandler())
```

### Azure Blob Storage (via `azure-storage-blob` + `azure-identity`)

Azure blobs are addressed by plain `https://` URLs (`https://<account>.blob.core.windows.net/<container>/<blob>`), so this handler claims them by host suffix — registering it makes it win over Trackio's generic HTTP handler:

```python
from urllib.parse import quote, unquote, urlsplit

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

import trackio


class AzureHandler(trackio.ReferenceHandler):
    def matches(self, scheme, uri):
        return scheme in ("http", "https") and urlsplit(
            uri
        ).netloc.lower().endswith(".blob.core.windows.net")

    def _split(self, uri):
        parts = urlsplit(uri)
        container, _, blob_name = parts.path.lstrip("/").partition("/")
        return f"{parts.scheme}://{parts.netloc}", container, unquote(blob_name)

    def _service(self, account_url):
        return BlobServiceClient(account_url, credential=DefaultAzureCredential())

    def resolve(self, uri, checksum, max_objects):
        account_url, container, blob_name = self._split(uri)
        service = self._service(account_url)
        if blob_name and not blob_name.endswith("/"):
            props = service.get_blob_client(container, blob_name).get_blob_properties()
            return [
                trackio.ResolvedReference(
                    relkey=None,
                    uri=uri,
                    size=props.size,
                    digest=props.etag.strip('"') if checksum else None,
                )
            ]
        base = blob_name[: blob_name.rfind("/") + 1]
        entries = []
        container_client = service.get_container_client(container)
        for blob in container_client.list_blobs(name_starts_with=blob_name):
            if blob.name.endswith("/"):
                continue
            if len(entries) >= max_objects:
                raise ValueError(
                    f"{uri} expands to more than {max_objects} objects; "
                    "pass max_objects= to raise the limit."
                )
            entries.append(
                trackio.ResolvedReference(
                    relkey=blob.name[len(base):],
                    uri=f"{account_url}/{container}/{quote(blob.name, safe='/')}",
                    size=blob.size,
                    digest=blob.etag.strip('"') if checksum else None,
                )
            )
        return entries

    def fetch(self, uri, dest):
        account_url, container, blob_name = self._split(uri)
        downloader = (
            self._service(account_url)
            .get_blob_client(container, blob_name)
            .download_blob()
        )
        with open(dest, "wb") as f:
            downloader.readinto(f)

    def hint(self):
        return "Configure Azure credentials so the blob can be probed for an ETag."


trackio.register_reference_handler(AzureHandler())
```

These handlers raise when the source can't be probed; if you'd rather record an un-checksummed reference in that case (for example, when cataloging data behind auth you can't reach at log time), catch the provider error inside `resolve` and return `[trackio.ResolvedReference(relkey=None, uri=uri)]` — Trackio will fall back to the URI as the digest and warn, using your `hint()`.

Register handlers in every process that adds *or downloads* such references: `Artifact.download()` needs the handler to fetch the bytes, and a URI whose scheme has no registered handler raises.

## Remote storage

When your run targets a Hugging Face Space or self-hosted server (see [Track](track.md)), artifact files are content-addressed and uploaded once: Trackio skips blobs the server already has, so re-logging shared files is cheap. Artifact metadata and blobs are persisted alongside your other run data to the configured HF Dataset or bucket.
