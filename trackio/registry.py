from dataclasses import dataclass

from trackio.registry_storage import RegistryStorage, validate_registry_name


@dataclass(frozen=True)
class Collection:
    """A read-only snapshot of one registry collection.

    Returned by `Registry.create_collection`, `Registry.collection`, and
    `Registry.collections`.
    """

    name: str
    """Collection name, unique within the registry."""

    type: str
    """The artifact type the collection accepts."""

    description: str | None
    """Human-readable description, or None if unset."""

    created_at: str
    """When the collection was created, as an ISO 8601 timestamp."""

    num_links: int
    """Number of versions currently linked into the collection."""

    latest_version: int | None
    """Newest collection version number, or None if nothing is linked."""

    links: list[dict]
    """The linked versions, newest first. Each is a dict with the
    `collection_version`, the source coordinates (`source_project`,
    `source_artifact`, `source_version`), the `manifest_digest` snapshot,
    and the current `aliases`."""


class Registry:
    """
    A handle on one artifact registry.

    A registry is a shared catalog of artifact versions, organized into
    collections. You publish into it with `Run.link_artifact` and promote
    versions by moving aliases such as `"staging"` or `"production"`. See
    the Registry guide for the full picture.

    You do not construct a `Registry` yourself. Create a registry with
    `trackio.Api().create_registry(name)` or fetch an existing one with
    `trackio.Api().registry(name)`; both return this handle.

    Args:
        name (`str`):
            Registry name, e.g. `"models"`. Must match `^[A-Za-z0-9_-]+$`
            (letters, digits, underscore, hyphen).

    Example:
        ```python
        import trackio

        registry = trackio.Api().create_registry("models")
        registry.create_collection(
            "my-model", artifact_type="model", description="My favorite model"
        )

        run = trackio.init(project="my-experiments")
        artifact = trackio.log_artifact("model.pt", name="resnet", type="model")
        run.link_artifact(artifact, "registry-models/my-model", aliases=["staging"])
        trackio.finish()

        registry.collection("my-model").links
        ```
    """

    def __init__(self, name: str):
        validate_registry_name(name)
        self._name = name

    @property
    def name(self) -> str:
        """The registry's name."""
        return self._name

    @property
    def description(self) -> str | None:
        """The registry's description, or None if unset."""
        record = RegistryStorage.get_registry(self._name)
        return record["description"] if record is not None else None

    def create_collection(
        self,
        name: str,
        artifact_type: str,
        description: str | None = None,
    ) -> Collection:
        """Create a collection in this registry.

        Collections are also created automatically on first link, so this
        is mainly useful to set a description up front. If the collection
        already exists, it is returned as-is and a non-None `description`
        is applied.

        Args:
            name (`str`):
                Collection name, unique within the registry. Must match
                `^[A-Za-z0-9._-]+$`.
            artifact_type (`str`):
                The artifact type the collection accepts, e.g. `"model"` or
                `"dataset"`. The type is fixed at creation; linking an
                artifact of a different type raises.
            description (`str`, *optional*):
                Human-readable description of the collection.

        Returns:
            The [`Collection`].
        """
        RegistryStorage.create_collection(
            self._name, name, artifact_type, description=description
        )
        return self.collection(name)

    def collection(self, name: str) -> Collection | None:
        """Describe one collection.

        Returns None if the registry or the collection does not exist."""
        record = RegistryStorage.get_collection(self._name, name)
        if record is None:
            return None
        links = record["links"]
        return Collection(
            name=record["name"],
            type=record["type"],
            description=record["description"],
            created_at=record["created_at"],
            num_links=len(links),
            latest_version=links[0]["collection_version"] if len(links) > 0 else None,
            links=links,
        )

    def collections(self) -> list[Collection]:
        """List the registry's collections, links included.

        Returns an empty list if the registry does not exist."""
        return [
            Collection(**summary)
            for summary in RegistryStorage.list_collections(self._name)
        ]

    def events(self) -> list[dict]:
        """Return the registry's audit log, oldest event first.

        Each event has an `id`, a `ts` timestamp, a `kind` (`"create"`,
        `"link"`, `"promote"`, `"update"`, or `"unlink"`), and a `payload`
        describing the mutation. A `create` payload without a `collection`
        key records the creation of the registry itself."""
        return RegistryStorage.get_events(self._name)

    def __repr__(self) -> str:
        return f"Registry({self._name!r})"
