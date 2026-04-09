from types import SimpleNamespace
from unittest.mock import patch

from huggingface_hub import Volume

from trackio import deploy
from trackio.bucket_storage import (
    _list_bucket_file_paths,
    export_from_bucket_for_static,
)


@patch("trackio.deploy.huggingface_hub.HfApi")
def test_get_source_bucket_falls_back_to_space_info_runtime(mock_hf_api):
    api = mock_hf_api.return_value
    api.get_space_runtime.return_value = SimpleNamespace(volumes=None)
    api.space_info.return_value = SimpleNamespace(
        runtime=SimpleNamespace(
            volumes=[
                Volume(
                    type="bucket",
                    source="abidlabs/example-bucket",
                    mount_path="/data",
                )
            ]
        )
    )

    bucket_id = deploy._get_source_bucket("abidlabs/example-space")

    assert bucket_id == "abidlabs/example-bucket"


@patch("trackio.bucket_storage.huggingface_hub.list_bucket_tree")
def test_list_bucket_file_paths_uses_list_bucket_tree(mock_list_bucket_tree):
    mock_list_bucket_tree.return_value = [
        SimpleNamespace(type="folder", path="trackio/media/proj"),
        SimpleNamespace(type="file", path="trackio/media/proj/image.png"),
    ]

    paths = _list_bucket_file_paths(
        "abidlabs/example-bucket", prefix="trackio/media/proj/"
    )

    assert paths == ["trackio/media/proj/image.png"]
    mock_list_bucket_tree.assert_called_once_with(
        "abidlabs/example-bucket",
        prefix="trackio/media/proj/",
        recursive=True,
    )


@patch("trackio.bucket_storage.huggingface_hub.download_bucket_files")
@patch("trackio.bucket_storage.copy_files")
@patch("trackio.bucket_storage._export_and_upload_static")
@patch("trackio.bucket_storage._list_bucket_file_paths")
@patch("trackio.bucket_storage._download_db_from_bucket")
def test_export_from_bucket_for_static_copies_media_server_side(
    mock_download_db,
    mock_list_bucket_file_paths,
    mock_export_and_upload_static,
    mock_copy_files,
    mock_download_bucket_files,
):
    mock_download_db.return_value = True
    mock_list_bucket_file_paths.return_value = ["trackio/media/proj/image.png"]

    export_from_bucket_for_static(
        "abidlabs/source-bucket", "abidlabs/dest-bucket", "proj"
    )

    mock_export_and_upload_static.assert_called_once()
    mock_copy_files.assert_called_once_with(
        "hf://buckets/abidlabs/source-bucket/trackio/media/proj/",
        "hf://buckets/abidlabs/dest-bucket/media/",
    )
    mock_download_bucket_files.assert_not_called()
