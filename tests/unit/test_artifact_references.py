import hashlib
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import httpx
import pytest
from starlette.testclient import TestClient

import trackio
from trackio import Run, bucket_storage, cas, references
from trackio import server as trackio_server
from trackio.asgi_app import create_trackio_starlette_app
from trackio.sqlite_storage import SQLiteStorage

FILE_ONLY_GOLDEN_DIGEST = (
    "257f92310c4bf3cd303d599398b0a07b2825488bbfa85681539074d1633e38cd"
)


class _Resp:
    def __init__(self, headers=None, body=b""):
        self.headers = headers or {}
        self._body = body

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeHfFs:
    def __init__(self, info=None, find=None, files=None):
        self._info = info or {}
        self._find = find or {}
        self._files = files or {}

    def info(self, path):
        if path in self._find:
            return self._find[path]
        return self._info

    def find(self, path, detail=True):
        return self._find

    def get_file(self, rpath, lpath):
        Path(lpath).write_bytes(self._files.get(rpath, b""))


class _MemoryStoreHandler(references.ReferenceHandler):
    """Custom handler for mem://bucket/key URIs backed by an in-memory dict,
    mirroring the object-store handlers shown in the artifacts documentation."""

    def __init__(self, objects, etags=None):
        self._objects = objects
        self._etags = etags or {}

    def matches(self, scheme, uri):
        return scheme == "mem"

    def resolve(self, uri, checksum, max_objects):
        parts = urlsplit(uri)
        bucket, key = parts.netloc, unquote(parts.path.lstrip("/"))
        if key and not key.endswith("/"):
            body = self._objects[key]
            return [
                references.ResolvedReference(
                    relkey=None,
                    uri=uri,
                    size=len(body),
                    digest=self._etags.get(key) if checksum else None,
                )
            ]
        base = key[: key.rfind("/") + 1]
        entries = []
        for obj_key in sorted(self._objects):
            if not obj_key.startswith(key):
                continue
            if len(entries) >= max_objects:
                raise ValueError(f"{uri} expands to more than {max_objects} objects")
            entries.append(
                references.ResolvedReference(
                    relkey=obj_key[len(base) :],
                    uri=f"mem://{bucket}/{quote(obj_key, safe='/')}",
                    size=len(self._objects[obj_key]),
                    digest=self._etags.get(obj_key) if checksum else None,
                )
            )
        return entries

    def fetch(self, uri, dest):
        parts = urlsplit(uri)
        key = unquote(parts.path.lstrip("/"))
        Path(dest).write_bytes(self._objects[key])

    def hint(self):
        return "Provide an etag for the object."


def _prepend_handler(monkeypatch, handler):
    monkeypatch.setattr(references, "_HANDLERS", [handler, *references._HANDLERS])


def test_validate_reference_uri_accepts_any_scheme():
    assert references.validate_reference_uri("s3://bucket/key") == (
        "s3",
        "s3://bucket/key",
    )
    assert references.validate_reference_uri("file:///data/x.bin")[0] == "file"
    assert references.validate_reference_uri("https://host/a.bin")[0] == "https"
    assert references.validate_reference_uri("gs://bucket/obj")[0] == "gs"
    assert references.validate_reference_uri("hf://datasets/u/r/f")[0] == "hf"
    assert references.validate_reference_uri("dvc://repo/obj")[0] == "dvc"
    assert references.validate_reference_uri("S3://Bucket/Key")[0] == "s3"


@pytest.mark.parametrize(
    "uri, match",
    [
        ("", "non-empty"),
        ("/plain/local/path", "a scheme is required"),
        ("relative/path", "a scheme is required"),
        ("  s3://bucket/key", "whitespace"),
        ("s3://bucket/\tkey", "whitespace"),
    ],
)
def test_validate_reference_uri_rejects(uri, match):
    with pytest.raises(ValueError, match=match):
        references.validate_reference_uri(uri)


def test_handler_dispatch_by_scheme():
    select = references._select
    assert isinstance(select("file", "file:///data/x.bin"), references.FileHandler)
    assert isinstance(select("http", "http://example.com/x"), references.HttpHandler)
    assert isinstance(select("https", "https://example.com/x"), references.HttpHandler)
    assert isinstance(select("hf", "hf://datasets/u/r/f"), references.HfHandler)
    with pytest.raises(ValueError, match="No reference handler"):
        select("s3", "s3://b/k")
    with pytest.raises(ValueError, match="register_reference_handler"):
        select("dvc", "dvc://x")


def test_register_reference_handler_public_api():
    handler = _MemoryStoreHandler({"k": b"v"})
    trackio.register_reference_handler(handler)
    try:
        assert references._select("mem", "mem://b/k") is handler
    finally:
        references._HANDLERS.remove(handler)


def test_register_reference_handler_rejects_non_handler():
    with pytest.raises(TypeError, match="ReferenceHandler instance"):
        trackio.register_reference_handler("not-a-handler")


def test_registered_handler_wins_over_builtin_http(monkeypatch):
    class _StoreHandler(_MemoryStoreHandler):
        def matches(self, scheme, uri):
            return scheme == "https" and urlsplit(uri).netloc == "store.example.com"

    handler = _StoreHandler({"obj": b"x"})
    _prepend_handler(monkeypatch, handler)
    assert references._select("https", "https://store.example.com/obj") is handler
    assert isinstance(
        references._select("https", "https://example.com/obj"),
        references.HttpHandler,
    )


def test_default_reference_name_uses_last_segment():
    assert (
        references.default_reference_name("s3://bucket/path/to/model.bin")
        == "model.bin"
    )
    assert references.default_reference_name("s3://bucket/prefix/") == "prefix"
    assert references.default_reference_name("s3://bucket") == "bucket"


def test_is_reference_entry_discriminates():
    assert (
        references.is_reference_entry({"path": "a", "ref": "s3://b/k", "size": 1})
        is True
    )
    assert (
        references.is_reference_entry({"path": "a", "digest": "x", "size": 1}) is False
    )


def test_looks_signed_detects_credentialed_queries():
    signed = references.looks_signed
    assert signed("https://b.s3.amazonaws.com/k?X-Amz-Algorithm=x&X-Amz-Signature=y")
    assert signed("https://acct.blob.core.windows.net/c/b?sv=2024-01-01&sig=abc")
    assert signed("https://storage.googleapis.com/b/o?X-Goog-Signature=00ff")
    assert signed("https://cdn.example.com/data.bin?token=secret")
    assert signed(
        "https://cdn.example.com/data.bin?Expires=1&Signature=x&Key-Pair-Id=y"
    )
    assert not signed("https://example.com/data.bin")
    assert not signed("https://example.com/data.bin?version=3&format=json")
    assert not signed("https://example.com/data.bin?significant=1")
    assert not signed("s3://bucket/key")
    assert not signed("gs://bucket/key")


def test_local_path_from_file_uri_round_trips(tmp_path):
    f = tmp_path / "sub" / "data.bin"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"payload")
    resolved = references.local_path_from_file_uri(f.resolve().as_uri())
    assert resolved.is_file()
    assert resolved.read_bytes() == b"payload"


def test_file_only_manifest_digest_is_unchanged_by_reference_support():
    manifest = [
        {"path": "w.bin", "digest": "a" * 64, "size": 10},
        {"path": "c.json", "digest": "b" * 64, "size": 3},
    ]
    canonical, digest, size = SQLiteStorage._canonical_manifest(manifest)
    assert digest == FILE_ONLY_GOLDEN_DIGEST
    assert size == 13
    assert all("ref" not in e for e in canonical)


def test_canonical_manifest_reference_identity_and_dedup():
    variants = [
        [{"path": "d", "ref": "s3://b/k", "size": 100, "digest": "s3://b/k"}],
        [{"path": "d", "ref": "s3://b/other", "size": 100, "digest": "s3://b/other"}],
        [{"path": "d", "ref": "s3://b/k", "size": 200, "digest": "s3://b/k"}],
        [{"path": "d", "ref": "s3://b/k", "size": 100, "digest": "c" * 64}],
        [{"path": "d", "ref": "s3://b/k", "size": 100, "digest": "e" * 64}],
        [{"path": "d", "ref": "s3://b/k", "size": 100, "digest": "opaque-etag-token"}],
    ]
    digests = [SQLiteStorage._canonical_manifest(v)[1] for v in variants]
    dup = SQLiteStorage._canonical_manifest(
        [{"path": "d", "ref": "s3://b/k", "size": 100, "digest": "s3://b/k"}]
    )[1]
    assert digests[0] == dup
    assert len(set(digests)) == 6


def test_add_reference_file_uri_autofills_checksum_and_size(temp_dir, tmp_path):
    payload = b"reference-bytes-1234"
    src = tmp_path / "dataset.bin"
    src.write_bytes(payload)

    trackio.init(project="ref-file")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(src.resolve().as_uri())
    logged = trackio.log_artifact(art)
    trackio.finish()

    refs = logged.references
    assert len(refs) == 1
    assert refs[0]["path"] == "dataset.bin"
    assert refs[0]["size"] == len(payload)
    assert refs[0]["digest"] == hashlib.sha256(payload).hexdigest()


def test_add_reference_checksum_false_falls_back_to_uri_digest(temp_dir, tmp_path):
    src = tmp_path / "dataset.bin"
    src.write_bytes(b"no-checksum")

    trackio.init(project="ref-nochecksum")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(src.resolve().as_uri(), checksum=False)
    logged = trackio.log_artifact(art)
    trackio.finish()

    ref = logged.references[0]
    assert ref["size"] == len(b"no-checksum")
    assert ref["digest"] == src.resolve().as_uri()


def test_add_reference_file_directory_expands(temp_dir, tmp_path):
    root = tmp_path / "tree"
    (root / "sub").mkdir(parents=True)
    (root / "a.bin").write_bytes(b"alpha")
    (root / "sub" / "b.bin").write_bytes(b"beta")

    trackio.init(project="ref-dir")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(root.resolve().as_uri(), name="tree")
    logged = trackio.log_artifact(art)
    trackio.finish()

    by_path = {r["path"]: r for r in logged.references}
    assert set(by_path) == {"tree/a.bin", "tree/sub/b.bin"}
    assert by_path["tree/a.bin"]["digest"] == hashlib.sha256(b"alpha").hexdigest()
    assert by_path["tree/sub/b.bin"]["size"] == len(b"beta")


def test_add_reference_directory_respects_max_objects(temp_dir, tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.bin").write_bytes(b"a")
    (root / "b.bin").write_bytes(b"b")

    art = trackio.Artifact(name="ds", type="dataset")
    with pytest.raises(ValueError, match="expands to more than 1 objects"):
        art.add_reference(root.resolve().as_uri(), max_objects=1)


def test_add_reference_http_probes_size_and_digest(temp_dir, monkeypatch):
    monkeypatch.setattr(
        references.httpx,
        "head",
        lambda *a, **k: _Resp({"content-length": "2048", "etag": '"abc123"'}),
    )
    trackio.init(project="ref-http")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("https://example.com/data.bin")
    logged = trackio.log_artifact(art)
    trackio.finish()

    ref = logged.references[0]
    assert ref["path"] == "data.bin"
    assert ref["size"] == 2048
    assert ref["digest"] == "abc123"


def test_add_reference_http_unreachable_records_uri_only(temp_dir, monkeypatch):
    def _boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(references.httpx, "head", _boom)
    trackio.init(project="ref-http-down")
    art = trackio.Artifact(name="ds", type="dataset")
    with pytest.warns(UserWarning, match="without a content checksum"):
        art.add_reference("https://example.com/data.bin")
    logged = trackio.log_artifact(art)
    trackio.finish()

    ref = logged.references[0]
    assert ref["size"] == 0
    assert ref["digest"] == "https://example.com/data.bin"


@pytest.mark.parametrize(
    "uri",
    [
        "https://b.s3.amazonaws.com/k?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeef",
        "https://acct.blob.core.windows.net/c/b.bin?sv=2024-01-01&sig=abc%2Bdef",
        "https://storage.googleapis.com/b/o.bin?X-Goog-Signature=00ff",
        "https://cdn.example.com/data.bin?token=secret123",
    ],
)
def test_add_reference_signed_url_warns(uri):
    art = trackio.Artifact(name="ds", type="dataset")
    with pytest.warns(UserWarning, match="signed URL"):
        art.add_reference(uri, checksum=False)
    assert art._pending_references[0][1] == uri


def test_add_reference_unsigned_url_does_not_warn(recwarn):
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("https://example.com/data.bin?version=3", checksum=False)
    assert [w for w in recwarn if "signed URL" in str(w.message)] == []


def test_download_fetches_http_reference(temp_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(
        references.httpx,
        "head",
        lambda *a, **k: _Resp({"content-length": "5", "etag": '"h"'}),
    )
    monkeypatch.setattr(
        references.httpx,
        "stream",
        lambda *a, **k: _Resp(body=b"hello"),
    )
    trackio.init(project="ref-http-dl")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("https://example.com/data.bin")
    trackio.log_artifact(art)
    trackio.finish()

    trackio.init(project="ref-http-dl", name="consumer")
    fetched = trackio.use_artifact("ds:latest")
    out = Path(fetched.download(tmp_path / "dl"))
    trackio.finish()
    assert (out / "data.bin").read_bytes() == b"hello"


def test_registered_handler_probes_size_and_digest(temp_dir, monkeypatch):
    handler = _MemoryStoreHandler(
        {"prefix/model.bin": b"1234"}, etags={"prefix/model.bin": "etag-1"}
    )
    _prepend_handler(monkeypatch, handler)
    trackio.init(project="ref-custom")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("mem://bucket/prefix/model.bin")
    logged = trackio.log_artifact(art)
    trackio.finish()

    ref = logged.references[0]
    assert ref["path"] == "model.bin"
    assert ref["size"] == 4
    assert ref["digest"] == "etag-1"


def test_registered_handler_prefix_expands_encodes_and_fetches(
    temp_dir, tmp_path, monkeypatch
):
    objects = {"shards/my file.bin": b"payload!", "shards/sub/b.bin": b"beta"}
    handler = _MemoryStoreHandler(
        objects, etags={key: f"e{i}" for i, key in enumerate(sorted(objects))}
    )
    _prepend_handler(monkeypatch, handler)
    trackio.init(project="ref-custom-prefix")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("mem://bucket/shards/", name="data")
    logged = trackio.log_artifact(art)
    trackio.finish()

    by_path = {r["path"]: r for r in logged.references}
    assert set(by_path) == {"data/my file.bin", "data/sub/b.bin"}
    assert by_path["data/my file.bin"]["ref"] == "mem://bucket/shards/my%20file.bin"

    trackio.init(project="ref-custom-prefix", name="consumer")
    fetched = trackio.use_artifact("ds:latest")
    out = Path(fetched.download(tmp_path / "dl"))
    trackio.finish()
    assert (out / "data" / "my file.bin").read_bytes() == b"payload!"
    assert (out / "data" / "sub" / "b.bin").read_bytes() == b"beta"


def test_registered_handler_unchecksummed_resolve_warns_with_hint(
    temp_dir, monkeypatch
):
    handler = _MemoryStoreHandler({"obj": b"data"})
    _prepend_handler(monkeypatch, handler)
    trackio.init(project="ref-custom-nodigest")
    art = trackio.Artifact(name="ds", type="dataset")
    with pytest.warns(UserWarning, match="Provide an etag"):
        art.add_reference("mem://bucket/obj")
    logged = trackio.log_artifact(art)
    trackio.finish()
    assert logged.references[0]["digest"] == "mem://bucket/obj"


def test_add_reference_hf_lfs_uses_sha256_digest(temp_dir, monkeypatch):
    info = {"type": "file", "size": 20, "lfs": {"sha256": "a" * 64}}
    monkeypatch.setattr(references.HfHandler, "_fs", lambda self: _FakeHfFs(info=info))
    trackio.init(project="ref-hf")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("hf://datasets/user/repo/data.bin")
    logged = trackio.log_artifact(art)
    trackio.finish()

    ref = logged.references[0]
    assert ref["path"] == "data.bin"
    assert ref["size"] == 20
    assert ref["digest"] == "a" * 64


def test_add_reference_hf_non_lfs_uses_blob_id_digest(temp_dir, monkeypatch):
    info = {"type": "file", "size": 8, "blob_id": "deadbeef"}
    monkeypatch.setattr(references.HfHandler, "_fs", lambda self: _FakeHfFs(info=info))
    trackio.init(project="ref-hf-blob")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("hf://user/repo/config.json")
    logged = trackio.log_artifact(art)
    trackio.finish()

    ref = logged.references[0]
    assert ref["digest"] == "deadbeef"


def test_add_reference_hf_directory_expands_and_fetches(
    temp_dir, tmp_path, monkeypatch
):
    info = {"type": "directory"}
    find = {
        "datasets/u/r/a.txt": {"type": "file", "size": 3, "blob_id": "b1"},
        "datasets/u/r/sub/b.txt": {"type": "file", "size": 4, "blob_id": "b2"},
    }
    files = {"datasets/u/r/a.txt": b"aaa", "datasets/u/r/sub/b.txt": b"bbbb"}
    fs = _FakeHfFs(info=info, find=find, files=files)
    monkeypatch.setattr(references.HfHandler, "_fs", lambda self: fs)

    trackio.init(project="ref-hf-dir")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("hf://datasets/u/r", name="data")
    trackio.log_artifact(art)
    trackio.finish()

    trackio.init(project="ref-hf-dir", name="consumer")
    fetched = trackio.use_artifact("ds:latest")
    assert {r["path"] for r in fetched.references} == {"data/a.txt", "data/sub/b.txt"}
    out = Path(fetched.download(tmp_path / "dl"))
    trackio.finish()
    assert (out / "data" / "a.txt").read_bytes() == b"aaa"
    assert (out / "data" / "sub" / "b.txt").read_bytes() == b"bbbb"


def test_add_reference_unknown_scheme_raises(temp_dir):
    art = trackio.Artifact(name="ds", type="dataset")
    with pytest.raises(ValueError, match="register_reference_handler"):
        art.add_reference("dvc://repo/models/model.pkl")
    with pytest.raises(ValueError, match="No reference handler"):
        art.add_reference("s3://bucket/key", checksum=False)
    assert art._pending_references == []


def test_download_unknown_scheme_reference_raises(temp_dir, tmp_path):
    SQLiteStorage.commit_artifact_version(
        project="ref-dvc-dl",
        name="ds",
        type="dataset",
        description=None,
        manifest=[
            {
                "path": "obj",
                "ref": "dvc://repo/obj",
                "digest": "dvc://repo/obj",
                "size": 0,
            }
        ],
        metadata=None,
        aliases=None,
        run_name="r",
        run_id=None,
    )
    trackio.init(project="ref-dvc-dl", name="consumer")
    fetched = trackio.use_artifact("ds:latest")
    with pytest.raises(ValueError, match="No reference handler"):
        fetched.download(tmp_path / "dl")
    trackio.finish()


def test_add_reference_rejects_size_and_digest_kwargs():
    art = trackio.Artifact(name="ds", type="dataset")
    with pytest.raises(TypeError):
        art.add_reference("s3://bucket/big.parquet", size=4096)
    with pytest.raises(TypeError):
        art.add_reference("s3://bucket/big.parquet", digest="d" * 64)


def test_add_reference_rejects_schemeless_uri(temp_dir):
    art = trackio.Artifact(name="ds", type="dataset")
    with pytest.raises(ValueError, match="a scheme is required"):
        art.add_reference("/local/path/file.bin")


def test_add_reference_missing_local_file_raises(temp_dir, tmp_path):
    missing = (tmp_path / "nope.bin").resolve().as_uri()
    art = trackio.Artifact(name="ds", type="dataset")
    with pytest.raises(ValueError, match="not an existing file or directory"):
        art.add_reference(missing)
    with pytest.raises(ValueError, match="not an existing file or directory"):
        art.add_reference(missing, checksum=False)


def test_add_reference_after_log_raises(temp_dir):
    trackio.init(project="ref-after-log")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("https://example.com/obj", checksum=False)
    trackio.log_artifact(art)
    trackio.finish()
    with pytest.raises(RuntimeError, match="already been logged"):
        art.add_reference("https://example.com/other")


def test_reference_and_file_path_collision_is_rejected(temp_dir, tmp_path):
    src = tmp_path / "a.bin"
    src.write_bytes(b"x")
    trackio.init(project="ref-collision")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_file(src, name="shared")
    art.add_reference("https://example.com/obj", name="shared", checksum=False)
    with pytest.raises(ValueError, match="Duplicate logical path"):
        trackio.log_artifact(art)
    trackio.finish()


def test_mixed_file_and_reference_round_trip(temp_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(
        references.httpx,
        "head",
        lambda *a, **k: _Resp({"content-length": "5", "etag": '"h"'}),
    )
    monkeypatch.setattr(
        references.httpx, "stream", lambda *a, **k: _Resp(body=b"hello")
    )
    weights = tmp_path / "weights.bin"
    weights.write_bytes(b"\x01\x02\x03weights")
    local_ref = tmp_path / "local_ref.bin"
    local_ref.write_bytes(b"local-reference-data")

    trackio.init(project="ref-mixed", name="producer")
    art = trackio.Artifact(name="bundle", type="model")
    art.add_file(weights)
    art.add_reference(local_ref.resolve().as_uri(), name="refs/local.bin")
    art.add_reference("https://example.com/remote.bin")
    trackio.log_artifact(art)
    trackio.finish()

    trackio.init(project="ref-mixed", name="consumer")
    fetched = trackio.use_artifact("bundle:latest")
    out = Path(fetched.download(tmp_path / "dl"))
    trackio.finish()

    assert (out / "weights.bin").read_bytes() == b"\x01\x02\x03weights"
    assert (out / "refs" / "local.bin").read_bytes() == b"local-reference-data"
    assert (out / "remote.bin").read_bytes() == b"hello"
    assert fetched.get_entry_uri("remote.bin") == "https://example.com/remote.bin"


def test_download_missing_local_file_reference_raises(temp_dir, tmp_path):
    src = tmp_path / "gone.bin"
    src.write_bytes(b"temporary")
    uri = src.resolve().as_uri()

    trackio.init(project="ref-missing")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(uri, name="data.bin")
    trackio.log_artifact(art)
    trackio.finish()
    src.unlink()

    trackio.init(project="ref-missing", name="consumer")
    fetched = trackio.use_artifact("ds:latest")
    with pytest.raises(FileNotFoundError):
        fetched.download(tmp_path / "dl")
    trackio.finish()


def test_identical_reference_manifests_dedupe_to_one_version(temp_dir):
    for _ in range(2):
        trackio.init(project="ref-dedup")
        art = trackio.Artifact(name="ds", type="dataset")
        art.add_reference("https://example.com/key", checksum=False)
        logged = trackio.log_artifact(art)
        trackio.finish()
        assert logged.version == "v0"

    trackio.init(project="ref-dedup", name="consumer")
    assert trackio.use_artifact("ds:latest").version == "v0"
    with pytest.raises(ValueError, match="not found"):
        trackio.use_artifact("ds:v1")
    trackio.finish()


def test_changing_reference_uri_or_digest_creates_new_version(temp_dir, monkeypatch):
    etag = {"value": "e1"}
    monkeypatch.setattr(
        references.httpx,
        "head",
        lambda *a, **k: _Resp({"content-length": "100", "etag": f'"{etag["value"]}"'}),
    )

    def _log(uri):
        trackio.init(project="ref-versions")
        art = trackio.Artifact(name="ds", type="dataset")
        art.add_reference(uri, name="data")
        logged = trackio.log_artifact(art)
        trackio.finish()
        return logged.version

    assert _log("https://example.com/k0") == "v0"
    assert _log("https://example.com/k1") == "v1"
    etag["value"] = "e2"
    assert _log("https://example.com/k1") == "v2"
    assert _log("https://example.com/k1") == "v2"


def test_alias_rotation_on_reference_only_artifact(temp_dir):
    for i in range(3):
        trackio.init(project="ref-alias", name=f"run-{i}")
        art = trackio.Artifact(name="ds", type="dataset")
        art.add_reference(f"https://example.com/k{i}", name="data", checksum=False)
        trackio.log_artifact(art, aliases=["best"] if i == 1 else None)
        trackio.finish()

    trackio.init(project="ref-alias", name="consumer")
    assert trackio.use_artifact("ds").version == "v2"
    assert trackio.use_artifact("ds:best").version == "v1"
    assert trackio.use_artifact("ds:v0").version == "v0"
    trackio.finish()


def test_reference_only_artifact_stages_no_blob(temp_dir, tmp_path):
    payload = b"reference-only-payload"
    src = tmp_path / "data.bin"
    src.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    trackio.init(project="ref-noblob")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(src.resolve().as_uri())
    logged = trackio.log_artifact(art)
    trackio.finish()

    assert logged.references[0]["digest"] == digest
    assert not cas.blob_path("ref-noblob", digest).is_file()
    assert SQLiteStorage.list_artifact_blobs_present("ref-noblob", [digest]) == set()


def test_reference_blobs_are_not_synced_to_bucket(temp_dir, monkeypatch):
    trackio.init(project="ref-sync")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("https://example.com/obj", checksum=False)
    trackio.log_artifact(art)
    trackio.finish()

    captured: dict = {}

    def _fake_batch(bucket_id, add=None, **kwargs):
        captured["add"] = list(add or [])

    monkeypatch.setattr(
        bucket_storage.huggingface_hub, "batch_bucket_files", _fake_batch
    )
    bucket_storage.upload_project_to_bucket("ref-sync", "user/bucket")

    remote_paths = {remote for _, remote in captured["add"]}
    assert any(p.endswith(".db") for p in remote_paths)
    assert not any("blobs/sha256" in p for p in remote_paths)


def test_blob_endpoint_404_for_reference_but_200_for_staged_file(temp_dir, tmp_path):
    weights = tmp_path / "w.bin"
    weights.write_bytes(b"present-bytes")
    external = tmp_path / "external.bin"
    external.write_bytes(b"reference-bytes")

    trackio.init(project="ref-endpoint")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(external.resolve().as_uri())
    art.add_file(weights)
    logged = trackio.log_artifact(art)
    trackio.finish()

    ref_digest = logged.references[0]["digest"]
    file_digest = next(e["digest"] for e in logged.manifest if "ref" not in e)
    assert ref_digest != file_digest
    app = create_trackio_starlette_app([], {})
    client = TestClient(app)
    headers = {"X-Trackio-Write-Token": trackio_server.write_token}
    missing = client.get(f"/artifact_blob/ref-endpoint/{ref_digest}", headers=headers)
    present = client.get(f"/artifact_blob/ref-endpoint/{file_digest}", headers=headers)
    assert missing.status_code == 404
    assert present.status_code == 200
    assert present.content == b"present-bytes"


def test_references_and_get_entry_uri_before_log(temp_dir):
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("https://example.com/obj", checksum=False)
    assert art.references == []
    assert art.get_entry_uri("obj") is None


def test_pre_change_file_manifest_parses_unchanged(temp_dir):
    manifest = [
        {"path": "weights.bin", "digest": "a" * 64, "size": 5},
        {"path": "config.json", "digest": "b" * 64, "size": 2},
    ]
    record = SQLiteStorage.commit_artifact_version(
        project="legacy",
        name="m",
        type="model",
        description=None,
        manifest=manifest,
        metadata=None,
        aliases=None,
        run_name="r",
        run_id=None,
    )
    fetched = SQLiteStorage.get_artifact_manifest("legacy", "m", "v0")
    assert fetched["manifest"] == sorted(manifest, key=lambda e: e["path"])
    assert all(not references.is_reference_entry(e) for e in fetched["manifest"])
    assert record["manifest_digest"] == fetched["manifest_digest"]


class _RaisingHfFs:
    def info(self, path):
        raise RuntimeError("RepositoryNotFoundError")


def test_relative_key_strips_prefix_directory_and_preserves_structure():
    rk = references._relative_key
    assert rk("train/data.csv", "") == "train/data.csv"
    assert rk("test/data.csv", "") == "test/data.csv"
    assert rk("logs.txt", "logs") == "logs.txt"
    assert rk("data/sub/b.csv", "data/") == "sub/b.csv"
    assert rk("prefix/a.bin", "prefix/") == "a.bin"
    assert rk("prefix/sub/b.bin", "prefix/") == "sub/b.bin"
    assert rk("a/b/c/d.bin", "a/b/") == "c/d.bin"
    assert rk("datasets/u/r/a.txt", "datasets/u/r/") == "a.txt"


def test_hf_info_failure_degrades(monkeypatch):
    monkeypatch.setattr(references.HfHandler, "_fs", lambda self: _RaisingHfFs())
    uri = "hf://datasets/private/repo/f.bin"
    resolved = references.resolve_reference(uri, "hf", True, 100)
    assert resolved == [references.ResolvedReference(None, uri)]


def test_file_handler_fetch_copies_bytes(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"copy-me")
    dest = tmp_path / "out" / "dest.bin"
    dest.parent.mkdir()
    references.fetch_reference(src.resolve().as_uri(), "file", dest)
    assert dest.read_bytes() == b"copy-me"


def test_copy_stream_helper_removed():
    assert not hasattr(references, "_copy_stream")


def test_file_handler_resolve_reports_size_and_digest(tmp_path):
    payload = b"0123456789abcdef"
    f = tmp_path / "data.bin"
    f.write_bytes(payload)
    resolved = references.resolve_reference(f.resolve().as_uri(), "file", True, 100)
    assert len(resolved) == 1
    assert resolved[0].size == len(payload)
    assert resolved[0].digest == hashlib.sha256(payload).hexdigest()


def test_download_reference_is_idempotent_and_skips_present(temp_dir, tmp_path):
    src = tmp_path / "data.bin"
    src.write_bytes(b"payload")
    trackio.init(project="ref-idem")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(src.resolve().as_uri())
    trackio.log_artifact(art)
    trackio.finish()

    trackio.init(project="ref-idem", name="consumer")
    fetched = trackio.use_artifact("ds:latest")
    root = tmp_path / "dl"
    out = Path(fetched.download(root))
    assert (out / "data.bin").read_bytes() == b"payload"

    src.unlink()
    again = Path(fetched.download(root))
    assert (again / "data.bin").read_bytes() == b"payload"
    trackio.finish()


def test_download_reference_failure_is_atomic_no_partial(
    temp_dir, tmp_path, monkeypatch
):
    src = tmp_path / "data.bin"
    src.write_bytes(b"payload")
    trackio.init(project="ref-atomic")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(src.resolve().as_uri())
    trackio.log_artifact(art)
    trackio.finish()

    trackio.init(project="ref-atomic", name="consumer")
    fetched = trackio.use_artifact("ds:latest")

    def _failing_fetch(uri, scheme, dest):
        Path(dest).write_bytes(b"half")
        raise RuntimeError("network drop")

    monkeypatch.setattr(references, "fetch_reference", _failing_fetch)
    root = tmp_path / "dl"
    with pytest.raises(RuntimeError, match="network drop"):
        fetched.download(root)
    assert not (root / "data.bin").exists()
    assert list(root.glob("*.partial.*")) == []
    trackio.finish()


class _FakeRemoteClient:
    def __init__(self, artifact_log):
        self._artifact_log = artifact_log

    def predict(self, *args, api_name=None, **kwargs):
        if api_name == "/check_artifact_blobs":
            return {"present": []}
        if api_name == "/artifact_log":
            return self._artifact_log()
        return None


def _remote_run(client):
    return Run(
        url="fake_url",
        project="ref-remote",
        client=client,
        name="producer",
        space_id="user/space",
    )


def test_reference_rejected_by_old_server_gives_upgrade_error(temp_dir):
    def _old_server():
        raise RuntimeError("Invalid sha256 digest: 's3etag'")

    run = _remote_run(_FakeRemoteClient(_old_server))
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("https://example.com/obj", checksum=False)
    with pytest.raises(RuntimeError, match="predates artifact references"):
        run.log_artifact(art)


def test_file_reference_missing_blob_on_old_server_gives_upgrade_error(
    temp_dir, tmp_path
):
    src = tmp_path / "data.bin"
    src.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()

    def _old_server():
        raise RuntimeError(f"Manifest references blobs not on server: ['{digest}']")

    run = _remote_run(_FakeRemoteClient(_old_server))
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(src.resolve().as_uri())
    with pytest.raises(RuntimeError, match="predates artifact references"):
        run.log_artifact(art)


def test_missing_file_blob_error_is_not_masked_as_old_server(temp_dir):
    def _old_server():
        raise RuntimeError(f"Manifest references blobs not on server: ['{'a' * 64}']")

    run = _remote_run(_FakeRemoteClient(_old_server))
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference("https://example.com/obj", checksum=False)
    with pytest.raises(RuntimeError, match="blobs not on server") as excinfo:
        run.log_artifact(art)
    assert "predates artifact references" not in str(excinfo.value)


def test_reference_entries_dropped_by_old_server_raise(temp_dir, tmp_path):
    src = tmp_path / "data.bin"
    src.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    record = {
        "version": 0,
        "aliases": ["latest"],
        "manifest": [{"path": "data.bin", "digest": digest, "size": 7}],
        "manifest_digest": "b" * 64,
        "size_bytes": 7,
    }
    run = _remote_run(_FakeRemoteClient(lambda: record))
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(src.resolve().as_uri())
    with pytest.raises(RuntimeError, match="plain file entries"):
        run.log_artifact(art)


def test_reference_preserved_by_current_server_round_trips(temp_dir, tmp_path):
    src = tmp_path / "data.bin"
    src.write_bytes(b"payload")
    uri = src.resolve().as_uri()
    digest = hashlib.sha256(b"payload").hexdigest()
    record = {
        "version": 0,
        "aliases": ["latest"],
        "manifest": [{"path": "data.bin", "ref": uri, "digest": digest, "size": 7}],
        "manifest_digest": "b" * 64,
        "size_bytes": 7,
    }
    run = _remote_run(_FakeRemoteClient(lambda: record))
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(uri)
    logged = run.log_artifact(art)
    assert logged.references[0]["ref"] == uri
    assert logged.version == "v0"


def test_download_reference_warns_and_proceeds_on_drift(temp_dir, tmp_path):
    src = tmp_path / "data.bin"
    src.write_bytes(b"original-content")
    trackio.init(project="ref-verify")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(src.resolve().as_uri())
    trackio.log_artifact(art)
    trackio.finish()

    src.write_bytes(b"tampered-content-different-length")

    trackio.init(project="ref-verify", name="consumer")
    fetched = trackio.use_artifact("ds:latest")
    with pytest.warns(UserWarning, match="may have changed since it was logged"):
        out = Path(fetched.download(tmp_path / "dl"))
    trackio.finish()
    assert (out / "data.bin").read_bytes() == b"tampered-content-different-length"


def test_download_unchanged_reference_does_not_warn(temp_dir, tmp_path, recwarn):
    src = tmp_path / "data.bin"
    src.write_bytes(b"stable-content")
    trackio.init(project="ref-nodrift")
    art = trackio.Artifact(name="ds", type="dataset")
    art.add_reference(src.resolve().as_uri())
    trackio.log_artifact(art)
    trackio.finish()

    trackio.init(project="ref-nodrift", name="consumer")
    fetched = trackio.use_artifact("ds:latest")
    out = Path(fetched.download(tmp_path / "dl"))
    trackio.finish()
    assert (out / "data.bin").read_bytes() == b"stable-content"
    assert [w for w in recwarn if "may have changed" in str(w.message)] == []
