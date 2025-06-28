import importlib

import pandas as pd

import trackio.utils as utils

importlib.reload(utils)

downsample_df = utils.downsample_df
simplify_column_names = utils.simplify_column_names


def test_downsample_df_reduce():
    df = pd.DataFrame({"x": range(100)})
    reduced = downsample_df(df, 10)
    assert len(reduced) == 10
    assert reduced.iloc[0]["x"] == 0
    assert reduced.iloc[-1]["x"] == 99


def test_downsample_df_no_change():
    df = pd.DataFrame({"x": range(5)})
    reduced = downsample_df(df, 10)
    assert len(reduced) == 5


def test_simplify_column_names_unique():
    cols = ["metric/long_name", "non alpha*"]
    simplified = simplify_column_names(cols)
    assert simplified[cols[0]] == "metric/lon"
    assert simplified[cols[1]] == "nonalpha"
