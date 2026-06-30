import asyncio
import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import trackio
from trackio import asgi_app, server
from trackio.artifact import Artifact
from trackio.sqlite_storage import SQLiteStorage


class _StubStreamResponse:
    def __init__(self, file_response):
        self._file_response = file_response
        self.status_code = getattr(file_response, "status_code", 200)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_bytes(self, chunk_size: int = 64 * 1024):
        if self.status_code >= 400:
            return
        path = Path(self._file_response.path)
        with path.open("rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk


@pytest.fixture
def in_process_remote(monkeypatch):
    """Mock RemoteClient + httpx.stream that route to in-process handlers."""
    monkeypatch.setattr(server, "assert_can_write_metrics", lambda req, tok: None)
    monkeypatch.setattr(
        server,
        "consume_uploaded_temp_file",
        lambda req, fd: Path(fd["path"]),
    )
    monkeypatch.setattr(server, "cleanup_uploaded_temp_file", lambda p: None)
    mock_request = MagicMock()

    class _MockClient:
        def __init__(self):
            self.calls: list[tuple[str, dict]] = []

        def predict(self, api_name, **kwargs):
            self.calls.append((api_name, kwargs))
            kwargs.pop("hf_token", None)
            if api_name == "/check_artifact_blobs":
                return server.check_artifact_blobs(request=mock_request, **kwargs)
            if api_name == "/bulk_upload_artifact_blob":
                return server.bulk_upload_artifact_blob(
                    request=mock_request, hf_token=None, **kwargs
                )
            if api_name == "/artifact_log":
                return server.artifact_log(
                    request=mock_request, hf_token=None, **kwargs
                )
            if api_name == "/get_artifact_manifest":
                return server.get_artifact_manifest(**kwargs)
            if api_name == "/log_artifact_use":
                return server.log_artifact_use(
                    request=mock_request, hf_token=None, **kwargs
                )
            raise AssertionError(f"unexpected api: {api_name}")

    def _stub_httpx_stream(method, url, **kwargs):
        assert method == "GET"
        marker = "/artifact_blob/"
        if marker not in url:
            return _StubStreamResponse(MagicMock(status_code=404))
        project, digest = url.split(marker, 1)[1].split("/", 1)
        request = MagicMock()
        request.path_params = {"project": project, "digest": digest}
        response = asyncio.run(asgi_app.artifact_blob_handler(request))
        return _StubStreamResponse(response)

    import httpx

    monkeypatch.setattr(httpx, "stream", _stub_httpx_stream)
    return _MockClient()


def _setup_remote_run(name: str, project: str, client) -> "trackio.Run":
    run = trackio.init(project=project, name=name)
    run._is_local = False
    run._space_id = "user/space"
    run._server_base_url = None
    run._remote_storage_key = "user/space"
    run._client = client
    return run


def _api_calls(client) -> list[str]:
    return [name for name, _ in client.calls]


def test_full_round_trip_producer_to_consumer(temp_dir, tmp_path, in_process_remote):
    weights = tmp_path / "weights.bin"
    payload = b"hello-world-checkpoint"
    weights.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    producer = _setup_remote_run("producer", "art-e2e", in_process_remote)
    art = Artifact(name="my-model", type="model", metadata={"acc": 0.91})
    art.add_file(weights)
    producer.log_artifact(art, aliases=["best"])

    assert art.version == "v0"
    assert "best" in art.aliases and "latest" in art.aliases
    assert art.metadata == {"acc": 0.91}
    assert _api_calls(in_process_remote) == [
        "/check_artifact_blobs",
        "/artifact_log",
    ]

    assert SQLiteStorage.get_artifact_manifest("art-e2e", "my-model", "v1") is None
    lineage = SQLiteStorage.get_run_artifacts("art-e2e", "producer", producer.id)
    assert len(lineage["output"]) == 1
    producer._client = None
    trackio.finish()

    consumer = _setup_remote_run("consumer", "art-e2e", in_process_remote)
    fetched = consumer.use_artifact("my-model:latest")
    assert fetched.version == "v0"
    assert fetched._remote_source == {
        "space_id": "user/space",
        "server_base_url": None,
        "write_token": None,
    }

    out = fetched.download(tmp_path / "dl")
    assert (Path(out) / "weights.bin").read_bytes() == payload

    consumer_lineage = SQLiteStorage.get_run_artifacts(
        "art-e2e", "consumer", consumer.id
    )
    assert len(consumer_lineage["input"]) == 1

    consumer._client = None
    trackio.finish()

    blob_path = (
        Path(temp_dir)
        / "artifacts"
        / "art-e2e"
        / "blobs"
        / "sha256"
        / digest[:2]
        / digest
    )
    assert blob_path.read_bytes() == payload


def test_relog_identical_bytes_dedups_at_db_layer(
    temp_dir, tmp_path, in_process_remote
):
    """Two runs log identical bytes → server creates one version row, both
    runs attributed as producers. The blob upload is skipped on both calls
    here (shared CAS), but the DB-layer dedup is what we're pinning."""
    weights = tmp_path / "w.bin"
    weights.write_bytes(b"same-bytes")

    run_a = _setup_remote_run("run-a", "art-relog", in_process_remote)
    art_a = Artifact(name="m", type="model")
    art_a.add_file(weights)
    run_a.log_artifact(art_a, aliases=["best"])
    run_a._client = None
    trackio.finish()

    run_b = _setup_remote_run("run-b", "art-relog", in_process_remote)
    art_b = Artifact(name="m", type="model")
    art_b.add_file(weights)
    run_b.log_artifact(art_b)
    run_b._client = None
    trackio.finish()

    record = SQLiteStorage.get_artifact_manifest("art-relog", "m", None)
    assert record["version"] == 0
    assert "best" in record["aliases"] and "latest" in record["aliases"]
    assert SQLiteStorage.get_artifact_manifest("art-relog", "m", "v1") is None

    lineage_a = SQLiteStorage.get_run_artifacts("art-relog", "run-a", run_a.id)
    lineage_b = SQLiteStorage.get_run_artifacts("art-relog", "run-b", run_b.id)
    assert len(lineage_a["output"]) == 1
    assert len(lineage_b["output"]) == 1
    assert lineage_a["output"][0]["version_id"] == lineage_b["output"][0]["version_id"]


def test_consumer_download_after_finish(temp_dir, tmp_path, in_process_remote):
    """`download()` works after `finish()` because `_remote_source` was
    snapshotted onto the Artifact at `use_artifact` time."""
    weights = tmp_path / "w.bin"
    payload = b"post-finish-payload"
    weights.write_bytes(payload)

    producer = _setup_remote_run("producer", "art-after-finish", in_process_remote)
    art = Artifact(name="m", type="model")
    art.add_file(weights)
    producer.log_artifact(art)
    producer._client = None
    trackio.finish()

    consumer = _setup_remote_run("consumer", "art-after-finish", in_process_remote)
    fetched = consumer.use_artifact("m:latest")
    consumer._client = None
    trackio.finish()

    assert fetched._remote_source is not None
    out = fetched.download(tmp_path / "dl")
    assert (Path(out) / "w.bin").read_bytes() == payload
