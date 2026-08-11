"""Publish artifact versions into a local registry.

A registry is a curated catalog that spans projects: you *link* artifact
versions into typed collections and promote them by moving aliases such as
`staging` and `production`. A link is a pointer — nothing is copied — so the
files stay in the project that produced them.

This example trains two candidate models in two different projects, publishes
both into one collection, promotes one of them, and prints the resulting catalog
and audit log. Everything stays in the local Trackio cache.

See `examples/registry-on-bucket.py` for the shared, bucket-backed version that
runs pushing to a Space can publish into.
"""

import json
import random
import tempfile
from pathlib import Path

import trackio as wandb

SUFFIX = random.randint(100000, 999999)
REGISTRY = f"models-{SUFFIX}"
COLLECTION = "churn-model"
TARGET = f"registry-{REGISTRY}/{COLLECTION}"
CANDIDATES = [
    ("resnet-experiments", "resnet", 0.42),
    ("unet-experiments", "unet", 0.31),
]


def write_checkpoint(directory: Path, name: str, loss: float) -> None:
    """Write a tiny fake model checkpoint and its config to `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.json").write_text(
        json.dumps({"arch": name, "hidden_size": 256, "num_layers": 4}, indent=2)
    )
    (directory / "weights.bin").write_bytes(
        random.randbytes(1024) + f"loss={loss:.4f}".encode()
    )


registry = wandb.Api().create_registry(
    REGISTRY, description="Models we consider deployable"
)
print(f"Created registry {registry.name!r}: {registry.description}")

# Two teams train two different architectures in two different projects, and
# each publishes its candidate into the same collection. They become successive
# versions of one asset — v0 and v1 — with their own version line, unrelated to
# each artifact's own version numbers.
for project, arch, loss in CANDIDATES:
    run = wandb.init(project=project, name=f"train-{arch}", config={"arch": arch})
    wandb.log({"train/loss": loss})

    with tempfile.TemporaryDirectory() as tmp:
        ckpt_dir = Path(tmp) / "checkpoint"
        write_checkpoint(ckpt_dir, arch, loss)

        artifact = wandb.Artifact(
            name=arch,
            type="model",
            description=f"{arch} candidate",
            metadata={"loss": loss},
        )
        artifact.add_dir(ckpt_dir)
        logged = wandb.log_artifact(artifact)

        linked = run.link_artifact(logged, TARGET, aliases=["staging"])
        print(
            f"\n{project}: published {linked.source_qualified_name} "
            f"as {linked.qualified_name} (aliases={sorted(linked.aliases)})"
        )
    wandb.finish()

# Promoting a version already in the collection means re-linking it with the
# alias: you get the same collection version back, and the alias moves onto it.
# Find the version's source in the collection's links, fetch it, link it again.
first_link = min(
    registry.collection(COLLECTION).links, key=lambda link: link["collection_version"]
)
run = wandb.init(project=first_link["source_project"], name="promote")
candidate = run.use_artifact(
    f"{first_link['source_artifact']}:v{first_link['source_version']}"
)
promoted = run.link_artifact(candidate, TARGET, aliases=["production"])
print(
    f"\nPromoted {promoted.qualified_name} to production "
    f"(aliases={sorted(promoted.aliases)}); re-linking created no new version"
)
wandb.finish()

collection = registry.collection(COLLECTION)
print(f"\nCollection {collection.name!r} ({collection.type}):")
for link in collection.links:
    print(
        f"  v{link['collection_version']} -> "
        f"{link['source_project']}/{link['source_artifact']}"
        f":v{link['source_version']}  aliases={link['aliases']}"
    )
print(f"latest_version={collection.latest_version}, num_links={collection.num_links}")

# Unlinking removes collection membership only: the source artifact and its
# files are untouched, the version number is never reused, and `latest` moves
# back to the highest remaining version. `unlink` is called on a linked
# artifact, so re-link the version first to get a handle on it (re-linking an
# already-linked version creates nothing).
newest = registry.collection(COLLECTION).links[0]
run = wandb.init(project=newest["source_project"], name="retire")
retired = run.link_artifact(
    run.use_artifact(f"{newest['source_artifact']}:v{newest['source_version']}"), TARGET
)
retired.unlink()
wandb.finish()
print(f"\nUnlinked {retired.qualified_name}; remaining versions:")
for link in registry.collection(COLLECTION).links:
    print(f"  v{link['collection_version']}  aliases={link['aliases']}")

print("\nAudit log:")
for event in registry.events():
    payload = {
        key: value
        for key, value in event["payload"].items()
        if key not in ("registry", "run_name", "run_id") and value is not None
    }
    print(f"  {event['kind']:<8} {payload}")
