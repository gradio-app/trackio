import re
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import huggingface_hub
import numpy as np
import pandas as pd
from huggingface_hub.constants import HF_HOME

if TYPE_CHECKING:
    from trackio.commit_scheduler import CommitScheduler
    from trackio.dummy_commit_scheduler import DummyCommitScheduler

RESERVED_KEYS = ["project", "run", "timestamp", "step", "time", "metrics"]
TRACKIO_DIR = Path(HF_HOME) / "trackio"

TRACKIO_LOGO_DIR = Path(__file__).parent / "assets"


def generate_readable_name(used_names: list[str], space_id: str | None = None) -> str:
    """
    Generates a random, readable name like "dainty-sunset-0".
    If space_id is provided, generates username-timestamp format instead.
    """
    if space_id is not None:
        username = huggingface_hub.whoami()["name"]
        timestamp = int(time.time())
        return f"{username}-{timestamp}"
    adjectives = [
        "dainty",
        "brave",
        "calm",
        "eager",
        "fancy",
        "gentle",
        "happy",
        "jolly",
        "kind",
        "lively",
        "merry",
        "nice",
        "proud",
        "quick",
        "hugging",
        "silly",
        "tidy",
        "witty",
        "zealous",
        "bright",
        "shy",
        "bold",
        "clever",
        "daring",
        "elegant",
        "faithful",
        "graceful",
        "honest",
        "inventive",
        "jovial",
        "keen",
        "lucky",
        "modest",
        "noble",
        "optimistic",
        "patient",
        "quirky",
        "resourceful",
        "sincere",
        "thoughtful",
        "upbeat",
        "valiant",
        "warm",
        "youthful",
        "zesty",
        "adventurous",
        "breezy",
        "cheerful",
        "delightful",
        "energetic",
        "fearless",
        "glad",
        "hopeful",
        "imaginative",
        "joyful",
        "kindly",
        "luminous",
        "mysterious",
        "neat",
        "outgoing",
        "playful",
        "radiant",
        "spirited",
        "tranquil",
        "unique",
        "vivid",
        "wise",
        "zany",
        "artful",
        "bubbly",
        "charming",
        "dazzling",
        "earnest",
        "festive",
        "gentlemanly",
        "hearty",
        "intrepid",
        "jubilant",
        "knightly",
        "lively",
        "magnetic",
        "nimble",
        "orderly",
        "peaceful",
        "quick-witted",
        "robust",
        "sturdy",
        "trusty",
        "upstanding",
        "vibrant",
        "whimsical",
    ]
    nouns = [
        "sunset",
        "forest",
        "river",
        "mountain",
        "breeze",
        "meadow",
        "ocean",
        "valley",
        "sky",
        "field",
        "cloud",
        "star",
        "rain",
        "leaf",
        "stone",
        "flower",
        "bird",
        "tree",
        "wave",
        "trail",
        "island",
        "desert",
        "hill",
        "lake",
        "pond",
        "grove",
        "canyon",
        "reef",
        "bay",
        "peak",
        "glade",
        "marsh",
        "cliff",
        "dune",
        "spring",
        "brook",
        "cave",
        "plain",
        "ridge",
        "wood",
        "blossom",
        "petal",
        "root",
        "branch",
        "seed",
        "acorn",
        "pine",
        "willow",
        "cedar",
        "elm",
        "falcon",
        "eagle",
        "sparrow",
        "robin",
        "owl",
        "finch",
        "heron",
        "crane",
        "duck",
        "swan",
        "fox",
        "wolf",
        "bear",
        "deer",
        "moose",
        "otter",
        "beaver",
        "lynx",
        "hare",
        "badger",
        "butterfly",
        "bee",
        "ant",
        "beetle",
        "dragonfly",
        "firefly",
        "ladybug",
        "moth",
        "spider",
        "worm",
        "coral",
        "kelp",
        "shell",
        "pebble",
        "face",
        "boulder",
        "cobble",
        "sand",
        "wavelet",
        "tide",
        "current",
        "mist",
    ]
    number = 0
    name = f"{adjectives[0]}-{nouns[0]}-{number}"
    while name in used_names:
        number += 1
        adjective = adjectives[number % len(adjectives)]
        noun = nouns[number % len(nouns)]
        name = f"{adjective}-{noun}-{number}"
    return name


def block_except_in_notebook():
    in_notebook = bool(getattr(sys, "ps1", sys.flags.interactive))
    if in_notebook:
        return
    try:
        while True:
            time.sleep(0.1)
    except (KeyboardInterrupt, OSError):
        print("Keyboard interruption in main thread... closing dashboard.")


def simplify_column_names(columns: list[str]) -> dict[str, str]:
    """
    Simplifies column names to first 10 alphanumeric or "/" characters with unique suffixes.

    Args:
        columns: List of original column names

    Returns:
        Dictionary mapping original column names to simplified names
    """
    simplified_names = {}
    used_names = set()

    for col in columns:
        alphanumeric = re.sub(r"[^a-zA-Z0-9/]", "", col)
        base_name = alphanumeric[:10] if alphanumeric else f"col_{len(used_names)}"

        final_name = base_name
        suffix = 1
        while final_name in used_names:
            final_name = f"{base_name}_{suffix}"
            suffix += 1

        simplified_names[col] = final_name
        used_names.add(final_name)

    return simplified_names


def print_dashboard_instructions(project: str) -> None:
    """
    Prints instructions for viewing the Trackio dashboard.

    Args:
        project: The name of the project to show dashboard for.
    """
    YELLOW = "\033[93m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    print("* View dashboard by running in your terminal:")
    print(f'{BOLD}{YELLOW}trackio show --project "{project}"{RESET}')
    print(f'* or by running in Python: trackio.show(project="{project}")')


def preprocess_space_and_dataset_ids(
    space_id: str | None, dataset_id: str | None
) -> tuple[str | None, str | None]:
    if space_id is not None and "/" not in space_id:
        username = huggingface_hub.whoami()["name"]
        space_id = f"{username}/{space_id}"
    if dataset_id is not None and "/" not in dataset_id:
        username = huggingface_hub.whoami()["name"]
        dataset_id = f"{username}/{dataset_id}"
    if space_id is not None and dataset_id is None:
        dataset_id = f"{space_id}-dataset"
    return space_id, dataset_id


def fibo():
    """Generator for Fibonacci backoff: 1, 1, 2, 3, 5, 8, ..."""
    a, b = 1, 1
    while True:
        yield a
        a, b = b, a + b


COLOR_PALETTE = [
    "#3B82F6",
    "#EF4444",
    "#10B981",
    "#F59E0B",
    "#8B5CF6",
    "#EC4899",
    "#06B6D4",
    "#84CC16",
    "#F97316",
    "#6366F1",
]


def get_color_mapping(runs: list[str], smoothing: bool) -> dict[str, str]:
    """Generate color mapping for runs, with transparency for original data when smoothing is enabled."""
    color_map = {}

    for i, run in enumerate(runs):
        base_color = COLOR_PALETTE[i % len(COLOR_PALETTE)]

        if smoothing:
            color_map[f"{run}_smoothed"] = base_color
            color_map[f"{run}_original"] = base_color + "4D"
        else:
            color_map[run] = base_color

    return color_map


def downsample(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str | None,
    x_lim: tuple[float, float] | None = None,
) -> pd.DataFrame:
    if df.empty:
        return df

    columns_to_keep = [x, y]
    if color is not None and color in df.columns:
        columns_to_keep.append(color)
    df = df[columns_to_keep].copy()

    n_bins = 100

    if color is not None and color in df.columns:
        groups = df.groupby(color)
    else:
        groups = [(None, df)]

    downsampled_indices = []

    for _, group_df in groups:
        if group_df.empty:
            continue

        group_df = group_df.sort_values(x)

        if x_lim is not None:
            x_min, x_max = x_lim
            before_point = group_df[group_df[x] < x_min].tail(1)
            after_point = group_df[group_df[x] > x_max].head(1)
            group_df = group_df[(group_df[x] >= x_min) & (group_df[x] <= x_max)]
        else:
            before_point = after_point = None
            x_min = group_df[x].min()
            x_max = group_df[x].max()

        if before_point is not None and not before_point.empty:
            downsampled_indices.extend(before_point.index.tolist())
        if after_point is not None and not after_point.empty:
            downsampled_indices.extend(after_point.index.tolist())

        if group_df.empty:
            continue

        if x_min == x_max:
            min_y_idx = group_df[y].idxmin()
            max_y_idx = group_df[y].idxmax()
            if min_y_idx != max_y_idx:
                downsampled_indices.extend([min_y_idx, max_y_idx])
            else:
                downsampled_indices.append(min_y_idx)
            continue

        if len(group_df) < 500:
            downsampled_indices.extend(group_df.index.tolist())
            continue

        bins = np.linspace(x_min, x_max, n_bins + 1)
        group_df["bin"] = pd.cut(
            group_df[x], bins=bins, labels=False, include_lowest=True
        )

        for bin_idx in group_df["bin"].dropna().unique():
            bin_data = group_df[group_df["bin"] == bin_idx]
            if bin_data.empty:
                continue

            min_y_idx = bin_data[y].idxmin()
            max_y_idx = bin_data[y].idxmax()

            downsampled_indices.append(min_y_idx)
            if min_y_idx != max_y_idx:
                downsampled_indices.append(max_y_idx)

    unique_indices = list(set(downsampled_indices))

    downsampled_df = df.loc[unique_indices].copy()
    downsampled_df = downsampled_df.sort_values(x).reset_index(drop=True)
    downsampled_df = downsampled_df.drop(columns=["bin"], errors="ignore")

    return downsampled_df


def sort_metrics_by_prefix(metrics: list[str]) -> list[str]:
    """
    Sort metrics by grouping prefixes together for dropdown/list display.
    Metrics without prefixes come first, then grouped by prefix.

    Args:
        metrics: List of metric names

    Returns:
        List of metric names sorted by prefix

    Example:
    Input: ["train/loss", "loss", "train/acc", "val/loss"]
    Output: ["loss", "train/acc", "train/loss", "val/loss"]
    """
    groups = group_metrics_by_prefix(metrics)
    result = []

    if "charts" in groups:
        result.extend(groups["charts"])

    for group_name in sorted(groups.keys()):
        if group_name != "charts":
            result.extend(groups[group_name])

    return result


def group_metrics_by_prefix(metrics: list[str]) -> dict[str, list[str]]:
    """
    Group metrics by their prefix. Metrics without prefix go to 'charts' group.

    Args:
        metrics: List of metric names

    Returns:
        Dictionary with prefix names as keys and lists of metrics as values

    Example:
        Input: ["loss", "accuracy", "train/loss", "train/acc", "val/loss"]
        Output: {
            "charts": ["loss", "accuracy"],
            "train": ["train/loss", "train/acc"],
            "val": ["val/loss"]
        }
    """
    no_prefix = []
    with_prefix = []

    for metric in metrics:
        if "/" in metric:
            with_prefix.append(metric)
        else:
            no_prefix.append(metric)

    no_prefix.sort()

    prefix_groups = {}
    for metric in with_prefix:
        prefix = metric.split("/")[0]
        if prefix not in prefix_groups:
            prefix_groups[prefix] = []
        prefix_groups[prefix].append(metric)

    for prefix in prefix_groups:
        prefix_groups[prefix].sort()

    groups = {}
    if no_prefix:
        groups["charts"] = no_prefix

    for prefix in sorted(prefix_groups.keys()):
        groups[prefix] = prefix_groups[prefix]

    return groups


def group_metrics_with_subprefixes(metrics: list[str]) -> dict:
    """
    Group metrics with simple 2-level nested structure detection.

    Returns a dictionary where each prefix group can have:
    - direct_metrics: list of metrics at this level (e.g., "train/acc")
    - subgroups: dict of subgroup name -> list of metrics (e.g., "loss" -> ["train/loss/norm", "train/loss/unnorm"])

    Example:
        Input: ["loss", "train/acc", "train/loss/normalized", "train/loss/unnormalized", "val/loss"]
        Output: {
            "charts": {
                "direct_metrics": ["loss"],
                "subgroups": {}
            },
            "train": {
                "direct_metrics": ["train/acc"],
                "subgroups": {
                    "loss": ["train/loss/normalized", "train/loss/unnormalized"]
                }
            },
            "val": {
                "direct_metrics": ["val/loss"],
                "subgroups": {}
            }
        }
    """
    result = {}

    for metric in metrics:
        if "/" not in metric:
            if "charts" not in result:
                result["charts"] = {"direct_metrics": [], "subgroups": {}}
            result["charts"]["direct_metrics"].append(metric)
        else:
            parts = metric.split("/")
            main_prefix = parts[0]

            if main_prefix not in result:
                result[main_prefix] = {"direct_metrics": [], "subgroups": {}}

            if len(parts) == 2:
                result[main_prefix]["direct_metrics"].append(metric)
            else:
                subprefix = parts[1]
                if subprefix not in result[main_prefix]["subgroups"]:
                    result[main_prefix]["subgroups"][subprefix] = []
                result[main_prefix]["subgroups"][subprefix].append(metric)

    for group_data in result.values():
        group_data["direct_metrics"].sort()
        for subgroup_metrics in group_data["subgroups"].values():
            subgroup_metrics.sort()

    if "charts" in result and not result["charts"]["direct_metrics"]:
        del result["charts"]

    return result


def get_sync_status(scheduler: "CommitScheduler | DummyCommitScheduler") -> int | None:
    """Get the sync status from the CommitScheduler in an integer number of minutes, or None if not synced yet."""
    if getattr(
        scheduler, "last_push_time", None
    ):  # DummyCommitScheduler doesn't have last_push_time
        time_diff = time.time() - scheduler.last_push_time
        return int(time_diff / 60)
    else:
        return None
