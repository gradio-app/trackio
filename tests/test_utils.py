import random

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
