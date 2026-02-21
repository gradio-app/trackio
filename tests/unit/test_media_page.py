"""Tests for table column detection and slider logic in media_page."""

import pandas as pd
import pytest

from trackio.table import Table


def make_table_dict(data=None):
    if data is None:
        data = [{"col": "val"}]
    return {"_type": Table.TYPE, "_value": data}


def is_table_entry(x):
    return isinstance(x, dict) and x.get("_type") == Table.TYPE


def filter_table_df(df, col):
    return df[df[col].apply(is_table_entry)]


def test_table_col_detection_with_mixed_types():
    df = pd.DataFrame(
        {
            "completions": [make_table_dict(), 0.95, make_table_dict()],
        }
    )

    object_cols = df.select_dtypes(include="object").columns
    table_cols = [
        c for c in object_cols if not (metric_df := filter_table_df(df, c)).empty
    ]

    assert "completions" in table_cols
    filtered = filter_table_df(df, "completions")
    assert len(filtered) == 2
    assert all(is_table_entry(v) for v in filtered["completions"])


def test_table_slider_no_type_error_with_mixed_column():
    rows = [make_table_dict([{"a": 1}]), 0.95, make_table_dict([{"a": 2}])]
    df = pd.DataFrame({"completions": rows})

    metric_df = filter_table_df(df, "completions")
    value = metric_df["completions"]

    assert len(value) == 2
    for idx in range(1, len(value) + 1):
        entry = value.iloc[idx - 1]
        assert isinstance(entry, dict), (
            f"Expected dict at index {idx}, got {type(entry)}"
        )
        assert "_value" in entry


def test_table_col_detection_float_first():
    df = pd.DataFrame(
        {
            "score": [0.5, make_table_dict(), make_table_dict()],
        }
    )

    object_cols = df.select_dtypes(include="object").columns
    table_cols = [
        c for c in object_cols if not (metric_df := filter_table_df(df, c)).empty
    ]

    assert "score" in table_cols


def test_multiple_table_cols_independent_data():
    df = pd.DataFrame(
        {
            "col_a": [make_table_dict([{"x": 1}]), make_table_dict([{"x": 2}])],
            "col_b": [make_table_dict([{"y": 10}]), make_table_dict([{"y": 20}])],
        }
    )

    def make_table_renderer(capture_df, capture_name):
        def get_table_at_index(index: int):
            value = capture_df[capture_name]
            return value.iloc[index - 1]["_value"]

        return get_table_at_index

    closures = {}
    for metric_name in ["col_a", "col_b"]:
        metric_df = filter_table_df(df, metric_name)
        closures[metric_name] = make_table_renderer(metric_df, metric_name)

    result_a = closures["col_a"](1)
    result_b = closures["col_b"](1)

    assert result_a == [{"x": 1}]
    assert result_b == [{"y": 10}]
    assert result_a != result_b
