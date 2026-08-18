"""Publish artifact versions into a registry backed by a Hugging Face bucket.

A local registry only exists on the machine that wrote it. Passing `bucket_id`
stores the registry in a Hugging Face bucket instead, so it is shared: anyone
with access to the bucket reads and writes it directly with their own HF
credentials, and a run that logs to a Space can publish into it too (a local
registry would be unreachable from the Space's side).

What lives in the bucket is an append-only log — object storage has no
compare-and-swap, so concurrent writers can only add objects, never edit shared
state:

    trackio/registries/<registry>/registry.json            name, description, created_at
    trackio/registries/<registry>/events/<event_uid>.json  one object per mutation

Readers fold that log into a local projection cache, which is why the last step
below can delete the cache and still see the whole catalog.

Requires a Hugging Face token with write access (`hf auth login`). The bucket is
created private. Set TRACKIO_EXAMPLE_SPACE_ID to also publish from a run that
logs to a Space (that deploys a Space and takes a few minutes).
"""

import json
import os
import random
import tempfile
from pathlib import Path

import huggingface_hub
from huggingface_hub.utils import disable_progress_bars

import trackio as wandb
from trackio.registry_bucket import BucketRegistryStorage

# Registry events are a few hundred bytes each; their upload bars add nothing.
disable_progress_bars()

SUFFIX = random.randint(100000, 999999)
NAMESPACE = huggingface_hub.whoami()["name"]
BUCKET = os.environ.get(
    "TRACKIO_EXAMPLE_BUCKET_ID", f"{NAMESPACE}/trackio-registry-demo-{SUFFIX}"
)
REGISTRY = f"models-{SUFFIX}"
COLLECTION = "churn-model"
TARGET = f"registry-{REGISTRY}/{COLLECTION}"
SPACE_ID = os.environ.get("TRACKIO_EXAMPLE_SPACE_ID")


def write_checkpoint(directory: Path, name: str, loss: float) -> None:
    """Write a tiny fake model checkpoint and its config to `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.json").write_text(
        json.dumps({"arch": name, "hidden_size": 256, "num_layers": 4}, indent=2)
    )
    (directory / "weights.bin").write_bytes(
        random.randbytes(1024) + f"loss={loss:.4f}".encode()
    )


def publish(project: str, arch: str, loss: float, aliases: list[str]) -> None:
    """Train a candidate in `project` and link it into the bucket registry."""
    run = wandb.init(
        project=project,
        name=f"train-{arch}",
        config={"arch": arch},
        space_id=SPACE_ID,
    )
    wandb.log({"train/loss": loss})
    with tempfile.TemporaryDirectory() as tmp:
        ckpt_dir = Path(tmp) / "checkpoint"
        write_checkpoint(ckpt_dir, arch, loss)

        artifact = wandb.Artifact(
            name=arch, type="model", metadata={"loss": loss}, description=f"{arch} run"
        )
        artifact.add_dir(ckpt_dir)
        logged = wandb.log_artifact(artifact)

        linked = run.link_artifact(logged, TARGET, aliases=aliases, bucket_id=BUCKET)
        print(
            f"  published {linked.source_qualified_name} as {linked.qualified_name} "
            f"(aliases={sorted(linked.aliases)})"
        )
    wandb.finish()


print(f"Bucket:   {BUCKET}")
print(f"Registry: {REGISTRY}")
if SPACE_ID:
    print(f"Space:    {SPACE_ID} (runs log there; the registry stays in the bucket)")
else:
    print(
        "Space:    not set — set TRACKIO_EXAMPLE_SPACE_ID to publish from a Space run"
    )

registry = wandb.Api().create_registry(
    REGISTRY, description="Models we consider deployable", bucket_id=BUCKET
)
print(f"\nCreated registry {registry.name!r} in bucket {registry.bucket_id}")

print("\nPublishing two candidates from two projects:")
publish("resnet-experiments", "resnet", 0.42, aliases=["staging"])
publish("unet-experiments", "unet", 0.31, aliases=["staging"])

collection = registry.collection(COLLECTION)
print(f"\nCollection {collection.name!r} ({collection.type}):")
for link in collection.links:
    print(
        f"  v{link['collection_version']} -> "
        f"{link['source_project']}/{link['source_artifact']}"
        f":v{link['source_version']}  aliases={link['aliases']}"
        f"  source_space_id={link['source_space_id']}"
    )

# A different machine has none of this locally. Deleting the projection cache
# makes this process one: the next read folds the event objects from the bucket
# and reconstructs the same catalog.
cache_db = BucketRegistryStorage(BUCKET).cache_db_path(REGISTRY)
cache_db.unlink(missing_ok=True)
print(f"\nDeleted the local projection cache ({cache_db.name}); reading again:")
cold = wandb.Api().registry(REGISTRY, bucket_id=BUCKET).collection(COLLECTION)
for link in cold.links:
    print(f"  v{link['collection_version']}  aliases={link['aliases']}")
assert [link["collection_version"] for link in cold.links] == [
    link["collection_version"] for link in collection.links
]
print("  (rebuilt from the bucket alone)")

objects = sorted(
    item.path
    for item in huggingface_hub.list_bucket_tree(
        BUCKET, prefix=f"trackio/registries/{REGISTRY}", recursive=True
    )
    if getattr(item, "type", None) == "file"
)
print(f"\n{len(objects)} objects in the bucket:")
for path in objects:
    print(f"  {path}")

print("\nAudit log:")
for event in wandb.Api().registry(REGISTRY, bucket_id=BUCKET).events():
    payload = {
        key: value
        for key, value in event["payload"].items()
        if key not in ("registry", "run_name", "run_id") and value is not None
    }
    print(f"  {event['kind']:<8} {payload}")

print(f"\nInspect the bucket at: https://huggingface.co/buckets/{BUCKET}")
print("Delete it when you are done with:")
print(
    f"  python -c \"import huggingface_hub; huggingface_hub.delete_bucket('{BUCKET}')\""
)
