from unittest.mock import MagicMock, patch

import pytest

from trackio.space_volumes import (
    SpaceBucketConflictError,
    attach_bucket_volume,
    create_bucket,
    resolve_bucket_id_for_deploy,
    set_space_volumes,
)


def test_resolve_bucket_id_explicit():
    assert (
        resolve_bucket_id_for_deploy(
            "org/space",
            bucket_id="org/my-bucket",
            create_bucket_if_missing=False,
            bucket_short_name=None,
        )
        == "org/my-bucket"
    )


def test_resolve_bucket_id_auto():
    assert (
        resolve_bucket_id_for_deploy(
            "org/space",
            bucket_id=None,
            create_bucket_if_missing=True,
            bucket_short_name=None,
        )
        == "org/space-storage"
    )


def test_resolve_bucket_id_short_override():
    assert (
        resolve_bucket_id_for_deploy(
            "org/space",
            bucket_id=None,
            create_bucket_if_missing=True,
            bucket_short_name="custom",
        )
        == "org/custom"
    )


def test_resolve_none():
    assert (
        resolve_bucket_id_for_deploy(
            "org/space",
            bucket_id=None,
            create_bucket_if_missing=False,
            bucket_short_name=None,
        )
        is None
    )


def test_attach_adds_volume_when_empty():
    with (
        patch("trackio.space_volumes.get_space_volumes", return_value=[]),
        patch("trackio.space_volumes.set_space_volumes") as mock_put,
    ):
        out = attach_bucket_volume(
            "u/s",
            "u/bucket",
            mount_path="/data",
            read_only=False,
            token="t",
        )
    assert out is True
    mock_put.assert_called_once()
    args, _kwargs = mock_put.call_args
    assert args[0] == "u/s"
    vols = args[1]
    assert len(vols) == 1
    assert vols[0]["type"] == "bucket"
    assert vols[0]["source"] == "u/bucket"
    assert vols[0]["mountPath"] == "/data"
    assert vols[0]["readOnly"] is False


def test_attach_noop_same_mount():
    existing = [
        {
            "type": "bucket",
            "source": "u/bucket",
            "mountPath": "/data",
            "readOnly": False,
        }
    ]
    with (
        patch("trackio.space_volumes.get_space_volumes", return_value=existing),
        patch("trackio.space_volumes.set_space_volumes") as mock_put,
    ):
        out = attach_bucket_volume(
            "u/s",
            "u/bucket",
            mount_path="/data",
            read_only=False,
            token="t",
        )
    assert out is False
    mock_put.assert_not_called()


def test_attach_conflict_other_bucket_mounted():
    existing = [
        {
            "type": "bucket",
            "source": "u/other",
            "mountPath": "/data",
            "readOnly": False,
        }
    ]
    with patch("trackio.space_volumes.get_space_volumes", return_value=existing):
        with pytest.raises(SpaceBucketConflictError):
            attach_bucket_volume(
                "u/s",
                "u/bucket",
                mount_path="/data",
                read_only=False,
                token="t",
            )


def test_attach_conflict_same_bucket_different_mount():
    existing = [
        {
            "type": "bucket",
            "source": "u/bucket",
            "mountPath": "/mnt",
            "readOnly": False,
        }
    ]
    with patch("trackio.space_volumes.get_space_volumes", return_value=existing):
        with pytest.raises(SpaceBucketConflictError):
            attach_bucket_volume(
                "u/s",
                "u/bucket",
                mount_path="/data",
                read_only=False,
                token="t",
            )


def test_create_bucket_409_no_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    with patch("trackio.space_volumes.get_session") as gs:
        gs.return_value.post.return_value = mock_resp
        create_bucket("u", "b", private=True, token="t")


def test_set_space_volumes_put():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("trackio.space_volumes.get_session") as gs:
        gs.return_value.put.return_value = mock_resp
        with patch("trackio.space_volumes.hf_raise_for_status"):
            set_space_volumes(
                "ns/repo",
                [{"type": "bucket", "source": "ns/b", "mountPath": "/data"}],
                token="tok",
            )
    call = gs.return_value.put.call_args
    assert "/api/spaces/ns/repo/volumes" in call[0][0]
    assert call[1]["json"] == {
        "volumes": [{"type": "bucket", "source": "ns/b", "mountPath": "/data"}]
    }
