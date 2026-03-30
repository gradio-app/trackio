"""E2E check that the Space README declares hf_mount for the bucket backend."""

from pathlib import Path

import huggingface_hub

from trackio import utils


def test_space_readme_mounts_hf_bucket_to_trackio_data(test_space_id):
    space_id, dataset_id, bucket_id = utils.preprocess_space_and_dataset_ids(
        test_space_id, None, None
    )
    assert dataset_id is None
    assert bucket_id == f"{space_id}-bucket"
    readme_path = huggingface_hub.hf_hub_download(
        repo_id=space_id,
        filename="README.md",
        repo_type="space",
    )
    readme = Path(readme_path).read_text(encoding="utf-8")
    assert "hf_mount" in readme
    assert f"hf://buckets/{bucket_id}" in readme
    assert "/data/trackio" in readme
    assert "buckets:" in readme
    assert f" - {bucket_id}" in readme
