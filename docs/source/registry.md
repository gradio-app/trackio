# Registry

> [!NOTE]
> The registry is under active development ([#607](https://github.com/gradio-app/trackio/issues/607)). Publishing — linking and promoting versions, described on this page — and read-only dashboard browsing are available today. Resolving registry versions with `use_artifact` and CLI commands are planned follow-ups.

A **registry** is a shared catalog of your best artifact versions. A project lists the artifacts your experiments produced; a registry lists selected artifacts **across** projects.

A registry contains **collections**. Each collection represents one asset — a model you retrain over time, a golden evaluation set — and holds the versions of it you chose to publish. You *link* an artifact version into a collection. A link is a pointer to the source version: nothing is copied. You then promote a linked version through lifecycle stages by moving aliases such as `staging` and `production`.

For example, a registry named `models` might contain one collection per deployable model, and a registry named `datasets` one collection per benchmark. How you split assets across registries and collections is up to you.

![How projects, artifact versions, collections, links, and aliases relate](https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/trackio/registry-overview.png)

A collection has its own version line (`v0`, `v1`, …) that is independent of the source artifacts' version numbers, and its versions may point at different source artifacts in different projects. Aliases name exactly one version per collection.

A registry is either **local** — stored next to your other Trackio data as a project named `registry-models` (the `registry-` prefix is reserved) — or backed by a **Hugging Face bucket**, which is what makes it reachable from other machines and from runs that log to a Space. See [Remote registries](#remote-registries).

## Create a registry

Create a registry with [`Api.create_registry`]:

```python
import trackio

registry = trackio.Api().create_registry("models", description="Our deployable models")
```

The optional `description` is stored on the registry and readable as `registry.description`.

Registries are never created implicitly. Linking into a registry that does not exist raises an error.

Use [`Api.registry`] to fetch an existing registry. It also raises if the registry does not exist.

## Create a collection

A *collection* is a set of linked artifact versions within a registry, with a single version history. The versions may come from different source artifacts: if a resnet-based and a unet-based model are candidates for the same deployable product, link them into one collection and they become successive versions of it. If they are separate products, give each its own collection.

You usually don't create collections manually: linking into a collection that does not exist creates it automatically. Create one explicitly when you want to set a description up front:

```python
registry.create_collection("my-model", "model", description="The model we deploy")
```

### Collection types

Each collection accepts a single *type* of artifact, fixed when the collection is created. The type comes from the artifact itself — the `type` field you pass to `trackio.Artifact` or `trackio.log_artifact` — so a collection created by a first link adopts that artifact's type.

For example, if you link a `"dataset"` artifact into a collection that accepts `"model"` artifacts, Trackio raises an error.

The registry itself accepts every type: a model collection and a dataset collection can live side by side in the same registry.

## Link an artifact version to a collection

Publish an artifact version with [`Run.link_artifact`]:

```python
import trackio

trackio.Api().create_registry("models")

run = trackio.init(project="my-experiments")
artifact = trackio.log_artifact("model.pt", name="resnet", type="model")

run.link_artifact(artifact, "registry-models/my-model", aliases=["staging"])
```

The target path is `"registry-<registry>/<collection>"`. The first segment is the registry's full name, prefix included.

`link_artifact` takes the artifact object itself, so the version you hold is exactly the version that gets published:

| Use case | How | What gets recorded |
| --- | --- | --- |
| Link the artifact you just logged | `run.link_artifact(artifact, ...)` | A link, published by the run |
| Link a specific existing version | `run.link_artifact(run.use_artifact("resnet:v3"), ...)` | The run consumes `resnet:v3`, then a link, published by the run |
| Link an artifact that was never logged | `run.link_artifact(draft_artifact, ...)` | The artifact is logged to the run's project first, then linked |

You can also link from the artifact itself with [`Artifact.link`], handy when the run isn't in scope:

```python
artifact.link("registry-models/my-model", aliases=["staging"])
```

`Artifact.link` requires the artifact to be already logged or fetched — it won't log a draft for you — and the link records no publishing run.

### The linked artifact

`link_artifact` returns the artifact at its registry location. Its `name` is the collection, its `project` is the registry, and its `version` and `aliases` are the collection's. Its content — `manifest`, `manifest_digest`, `size`, `metadata` — is the source version's, and the `source_project`, `source_name`, `source_version`, and `source_qualified_name` properties point back at it:

```python
linked = run.link_artifact(artifact, "registry-models/my-model")
linked.qualified_name         # "registry-models/my-model:v0"
linked.source_qualified_name  # "my-experiments/resnet:v0"
```

Linking a linked artifact links its source version directly (with a warning), so links never chain.

> [!NOTE]
> Downloading through a registry location is not supported yet; it arrives together with registry resolution. Until then, download the source artifact version.

### Collection versions

Each new link gets the next version number in the collection, starting at `v0`. Collection versions are independent of the source artifacts' own version numbers, because linked versions typically come from different artifacts and projects.

Linking a source version that is already in the collection does not create a new version. You get the existing version back, and any `aliases` you passed still move. Version numbers are never reused, so a published `my-model:v3` can never silently change meaning.

## Promote a version with aliases

An alias references one version per collection. Assigning an alias that another version already holds moves it — that move *is* the promotion. Consumers that resolve `my-model:production` follow the alias, so nothing downstream changes when it moves.

Most promotions happen at publish time: you link a new version and place the alias in the same call.

```python
run.link_artifact(artifact, "registry-models/my-model", aliases=["staging"])
```

To promote a version that is *already* in the collection, re-link it with the alias. Re-linking creates nothing new — you get the existing collection version back, and the aliases you pass move onto it. Find the version's source in the collection's links, fetch it, and link it again:

```python
registry.collection("my-model").links
# [..., {"collection_version": 1, "source_project": "my-experiments",
#        "source_artifact": "resnet", "source_version": 3, ...}]

candidate = run.use_artifact("resnet:v3")
run.link_artifact(candidate, "registry-models/my-model", aliases=["production"])
```

Today the candidate is fetched by its source name, as recorded in the collection's links. Fetching it from the registry directly — `use_artifact("registry-models/my-model:v1")` — arrives together with registry resolution; the re-link step stays the same. Rolling an alias back to an older version works the same way.

Trackio manages the `latest` alias for you: it always points at the newest linked version.

## Unlink a version

Remove a link with [`Artifact.unlink`], called on the linked artifact:

```python
linked = run.link_artifact(artifact, "registry-models/my-model")
linked.unlink()
```

The source artifact and its files are untouched — only the collection membership is removed. Any aliases on the link go with it, and the collection version number is never reused, so `my-model:v0` can't later mean something else. If the version you remove held `latest`, that alias moves to the highest remaining version, so `latest` keeps pointing at the newest version in the collection.

## Remote registries

A local registry only exists on the machine that wrote it. To share a catalog across machines — or to publish from a run that logs to a Space or a self-hosted server — back the registry with a **Hugging Face bucket** by passing `bucket_id`:

```python
registry = trackio.Api().create_registry(
    "models", description="Our deployable models", bucket_id="my-org/models-registry"
)
```

The bucket is created (private) if it does not exist. Set `TRACKIO_REGISTRY_BUCKET_ID` to make it the default for every registry call in a process, so scripts don't have to pass it.

Fetching, inspecting, and publishing all take the same argument:

```python
registry = trackio.Api().registry("models", bucket_id="my-org/models-registry")

run = trackio.init(project="my-experiments", space_id="my-org/my-dashboard")
artifact = trackio.log_artifact("model.pt", name="resnet", type="model")

run.link_artifact(
    artifact,
    "registry-models/my-model",
    aliases=["staging"],
    bucket_id="my-org/models-registry",
)
```

Everyone with access to the bucket writes to it directly with their own Hugging Face credentials — there is no server in the path, so a registry is not tied to any one Space and outlives all of them. `Artifact.link` and `Artifact.unlink` accept `bucket_id` the same way, and a linked artifact remembers the bucket it came from, so `linked.unlink()` goes back to the right registry.

The registry's own bucket is deliberately *not* the run's bucket: a registry is a cross-project catalog, so you name it explicitly rather than inheriting wherever metrics happen to go.

### What lives in the bucket

Each mutation is stored as one immutable object, and state is a fold of that log:

```
trackio/registries/<registry>/registry.json            name, description, created_at
trackio/registries/<registry>/events/<event_uid>.json  one object per mutation
```

Reading a remote registry folds those events into a local projection database under `registry-cache/`, which is a cache: delete it and the next read rebuilds it from the bucket.

### Concurrency

Object storage has no compare-and-swap, so writers cannot take a lock — they can only add objects nobody else is writing. Two consequences, both by design:

- **Version numbers are assigned by the fold, not by the writer.** Concurrent links are ordered by their event id (timestamp, then writer, then sequence), so each gets a distinct, never-reused number. A version reported by one writer can shift once a concurrent writer's events are folded in.
- **Alias moves are last-writer-wins** under that same order, `latest` included. Two people promoting `production` at the same instant is settled by event order.

Links stay pure pointers: nothing is copied into the registry bucket, so resolving a version reads the source project's storage, which has to stay reachable. Copying (pinning) a version's bytes into the registry is a planned follow-up.

## Inspect a registry

The [`Registry`] handle lists collections and their linked versions. Reads return [`Collection`] snapshots:

```python
registry = trackio.Api().registry("models")

registry.collections()
# [Collection(name="my-model", type="model", num_links=2, latest_version=1, ...)]

registry.collection("my-model").links
# [{"collection_version": 1, "source_project": "my-experiments",
#   "source_artifact": "resnet", "source_version": 4,
#   "aliases": ["latest", "production"], ...}]
```

Each link records where the version came from (`source_project`, `source_artifact`, `source_version`), the source's storage coordinates when it is not local (`source_space_id`, `source_bucket_id`), and the aliases currently on it. A link is a pure pointer to that source version; resolving it (a follow-up) reads the source version directly.

### Browse registries in the dashboard

Launch the standalone, read-only registry dashboard to browse registry descriptions, collections, linked versions, aliases, source locations, and audit events:

```bash
trackio show registry
```

Or launch it from Python with `trackio.show(dashboard="registry")`. The registry dashboard is separate from the project dashboard because registries catalog artifacts across projects.

The **Local** source shows registries stored on the dashboard machine. Choose **HF Bucket** to select an accessible Hugging Face bucket or enter a bucket id such as `my-org/models-registry`. On a Space, private bucket access uses the signed-in viewer's Hugging Face credentials. A self-hosted dashboard only uses its saved Hugging Face token for viewers who opened its write-access URL. Public read-only dashboards never expose buckets through a server-owned token. Registry browsing is not included in static dashboard snapshots.

## Audit history

Every mutation appends an event to the registry's audit log: registry and collection creation (`create`), `link`, `promote`, description changes (`update`), and `unlink`. The log answers questions like "which version was in production last month, and which run published it?":

```python
registry.events()
# [{"id": 1, "ts": "...", "kind": "create", "payload": {...}},
#  {"id": 2, "ts": "...", "kind": "link",
#   "payload": {"collection": "my-model", "collection_version": 0,
#               "source_project": "my-experiments", "run_name": "exp-1", ...}},
#  {"id": 3, "ts": "...", "kind": "promote",
#   "payload": {"alias": "staging", "collection_version": 0,
#               "previous_version": None, ...}}]
```

Link and promote events record the publishing run. Promote events also record the version the alias moved from.
