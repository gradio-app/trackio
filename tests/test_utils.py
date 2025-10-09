import random
import tempfile
from pathlib import Path

import pytest

from trackio import utils


def test_generate_readable_names_are_unique_even_with_seed():
    names = []
    for _ in range(10):
        random.seed(42)
        names.append(utils.generate_readable_name(names))
    assert len(names) == len(set(names))


def test_sort_metrics_by_prefix():
    metrics = ["train/loss", "loss", "train/acc", "val/loss", "accuracy"]
    result = utils.sort_metrics_by_prefix(metrics)
    expected = ["accuracy", "loss", "train/acc", "train/loss", "val/loss"]
    assert result == expected


def test_group_metrics_by_prefix():
    metrics = ["loss", "accuracy", "train/loss", "train/acc", "val/loss", "test/f1"]
    result = utils.group_metrics_by_prefix(metrics)
    expected = {
        "charts": ["accuracy", "loss"],
        "test": ["test/f1"],
        "train": ["train/acc", "train/loss"],
        "val": ["val/loss"],
    }
    assert result == expected


def test_group_metrics_with_subprefixes():
    metrics = [
        "loss",
        "train/acc",
        "train/loss/normalized",
        "train/loss/unnormalized",
        "val/loss",
        "test/f1/micro",
        "test/f1/macro",
    ]
    result = utils.group_metrics_with_subprefixes(metrics)
    expected = {
        "charts": {"direct_metrics": ["loss"], "subgroups": {}},
        "train": {
            "direct_metrics": ["train/acc"],
            "subgroups": {"loss": ["train/loss/normalized", "train/loss/unnormalized"]},
        },
        "val": {"direct_metrics": ["val/loss"], "subgroups": {}},
        "test": {
            "direct_metrics": [],
            "subgroups": {"f1": ["test/f1/macro", "test/f1/micro"]},
        },
    }
    assert result == expected


def test_format_timestamp():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    two_minutes_ago = (now - timedelta(minutes=2)).isoformat()
    assert utils.format_timestamp(two_minutes_ago) == "2 minutes ago"

    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    assert utils.format_timestamp(one_hour_ago) == "1 hour ago"

    two_days_ago = (now - timedelta(days=2)).isoformat()
    assert utils.format_timestamp(two_days_ago) == "2 days ago"

    thirty_seconds_ago = (now - timedelta(seconds=30)).isoformat()
    assert utils.format_timestamp(thirty_seconds_ago) == "Just now"

    assert utils.format_timestamp(None) == "Unknown"
    assert utils.format_timestamp("invalid") == "Unknown"


@pytest.mark.parametrize(
    "base_url, project, write_token, expected",
    [
        (
            "https://example.com",
            "my_project",
            "token123",
            "https://example.com?project=my_project&write_token=token123",
        ),
        ("https://api.test.io", None, "abc", "https://api.test.io?write_token=abc"),
        (
            "http://localhost:8000",
            "test",
            "secret",
            "http://localhost:8000?project=test&write_token=secret",
        ),
        ("https://app.com/api", "", "xyz789", "https://app.com/api?write_token=xyz789"),
        (
            "https://trackio.ai",
            "demo/project",
            "tok_en",
            "https://trackio.ai?project=demo/project&write_token=tok_en",
        ),
    ],
)
def test_get_full_url(base_url, project, write_token, expected):
    result = utils.get_full_url(base_url, project, write_token)
    assert result == expected


@pytest.mark.parametrize(
    "obj, expected",
    [
        ("hello", "hello"),
        ({"key": "value", "num": 123}, {"key": "value", "num": 123}),
        ([1, 2, "three"], [1, 2, "three"]),
        ((4, 5, 6), [4, 5, 6]),
        ({7, 8, 9}, {7, 8, 9}),
        ({"nested": {"dict": [1, 2]}}, {"nested": {"dict": [1, 2]}}),
    ],
)
def test_to_json_safe(obj, expected):
    result = utils.to_json_safe(obj)
    if isinstance(obj, set):
        assert set(result) == expected
    else:
        assert result == expected


def test_to_json_safe_with_object():
    class LoraConfig:
        def __init__(self):
            self.r = 8
            self.lora_alpha = 16
            self.target_modules = ["q_proj", "v_proj"]
            self.lora_dropout = 0.1
            self.bias = "none"
            self.task_type = "CAUSAL_LM"
            self._private_config = "hidden"

    lora_config = LoraConfig()
    assert utils.to_json_safe(lora_config) == {
        "r": 8,
        "lora_alpha": 16,
        "target_modules": ["q_proj", "v_proj"],
        "lora_dropout": 0.1,
        "bias": "none",
        "task_type": "CAUSAL_LM",
    }


def test_trackio_dir_env_var(monkeypatch):
    """Test that TRACKIO_DIR environment variable is respected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = str(tmpdir)

        monkeypatch.setenv("TRACKIO_DIR", test_path)
        monkeypatch.delenv("PERSISTANT_STORAGE_ENABLED", raising=False)
        result_dir = utils._get_trackio_dir()
        assert str(result_dir) == test_path

        monkeypatch.delenv("TRACKIO_DIR", raising=False)
        monkeypatch.delenv("PERSISTANT_STORAGE_ENABLED", raising=False)
        result_dir = utils._get_trackio_dir()
        assert "huggingface/trackio" in Path(result_dir).as_posix()

        monkeypatch.delenv("TRACKIO_DIR", raising=False)
        monkeypatch.setenv("PERSISTANT_STORAGE_ENABLED", "true")
        result_dir = utils._get_trackio_dir()
        assert Path(result_dir).as_posix() == "/data/trackio"

        monkeypatch.setenv("TRACKIO_DIR", test_path)
        monkeypatch.setenv("PERSISTANT_STORAGE_ENABLED", "true")
        result_dir = utils._get_trackio_dir()
        assert Path(result_dir).as_posix() == "/data/trackio"


def test_parse_plot_order():
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {}, clear=True):
        assert utils.parse_plot_order() == []

    with patch.dict(os.environ, {"TRACKIO_PLOT_ORDER": ""}, clear=True):
        assert utils.parse_plot_order() == []

    with patch.dict(os.environ, {"TRACKIO_PLOT_ORDER": "   "}, clear=True):
        assert utils.parse_plot_order() == []

    with patch.dict(
        os.environ, {"TRACKIO_PLOT_ORDER": "train/loss,val/loss,train/*"}, clear=True
    ):
        assert utils.parse_plot_order() == ["train/loss", "val/loss", "train/*"]

    with patch.dict(
        os.environ,
        {"TRACKIO_PLOT_ORDER": " train/loss , val/loss , train/* "},
        clear=True,
    ):
        assert utils.parse_plot_order() == ["train/loss", "val/loss", "train/*"]


def test_get_metric_sort_key():
    plot_order = ["train/loss", "val/loss", "train/*", "val/*"]

    assert utils.get_metric_sort_key("train/loss", plot_order) == (0, 0, "train/loss")
    assert utils.get_metric_sort_key("val/loss", plot_order) == (1, 1, "val/loss")

    assert utils.get_metric_sort_key("train/accuracy", plot_order) == (
        0,
        6,
        "train/accuracy",
    )
    assert utils.get_metric_sort_key("val/accuracy", plot_order) == (
        1,
        7,
        "val/accuracy",
    )

    assert utils.get_metric_sort_key("test/loss", plot_order) == (4, 4, "test/loss")

    assert utils.get_metric_sort_key("train/loss", []) == (
        float("inf"),
        float("inf"),
        "train/loss",
    )


def test_sort_metric_groups():
    groups = {
        "train": {"direct_metrics": ["train/loss"], "subgroups": {}},
        "val": {"direct_metrics": ["val/loss"], "subgroups": {}},
        "test": {"direct_metrics": ["test/loss"], "subgroups": {}},
        "charts": {"direct_metrics": ["loss"], "subgroups": {}},
    }

    result = utils.sort_metric_groups(groups, [])
    assert result == ["charts", "test", "train", "val"]

    plot_order = ["train/loss", "val/loss", "test/loss"]
    result = utils.sort_metric_groups(groups, plot_order)
    assert result == ["train", "val", "test", "charts"]

    plot_order = ["val/loss"]
    result = utils.sort_metric_groups(groups, plot_order)
    assert result == ["val", "charts", "test", "train"]


def test_sort_metrics_within_group():
    metrics = ["train/accuracy", "train/loss", "train/f1", "train/precision"]

    result = utils.sort_metrics_within_group(metrics, [])
    assert result == ["train/accuracy", "train/f1", "train/loss", "train/precision"]

    plot_order = ["train/loss", "train/f1", "train/*"]
    result = utils.sort_metrics_within_group(metrics, plot_order)
    assert result == ["train/loss", "train/f1", "train/accuracy", "train/precision"]

    plot_order = ["train/*", "train/loss"]
    result = utils.sort_metrics_within_group(metrics, plot_order)
    assert result == ["train/loss", "train/accuracy", "train/f1", "train/precision"]


def test_group_metrics_with_subprefixes_with_plot_order():
    """Test that group_metrics_with_subprefixes uses plot ordering internally."""
    import os
    from unittest.mock import patch

    metrics = [
        "train/accuracy",
        "train/loss",
        "val/loss",
        "val/accuracy",
        "charts_metric",
        "test/f1/macro",
        "test/f1/micro",
    ]

    with patch.dict(
        os.environ,
        {"TRACKIO_PLOT_ORDER": "train/loss,val/loss,train/*,val/*"},
        clear=True,
    ):
        result = utils.group_metrics_with_subprefixes(metrics)

        assert result["train"]["direct_metrics"] == ["train/loss", "train/accuracy"]
        assert result["val"]["direct_metrics"] == ["val/loss", "val/accuracy"]
