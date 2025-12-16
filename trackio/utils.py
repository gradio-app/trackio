import math
import os
import re
import secrets
import time
from datetime import datetime, timezone
from functools import lru_cache
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

TRACKIO_LOGO_DIR = Path(__file__).parent / "assets"


def get_logo_urls() -> dict[str, str]:
    """Get logo URLs from environment variables or use defaults."""
    light_url = os.environ.get(
        "TRACKIO_LOGO_LIGHT_URL",
        f"/gradio_api/file={TRACKIO_LOGO_DIR}/trackio_logo_type_light_transparent.png",
    )
    dark_url = os.environ.get(
        "TRACKIO_LOGO_DARK_URL",
        f"/gradio_api/file={TRACKIO_LOGO_DIR}/trackio_logo_type_dark_transparent.png",
    )
    return {"light": light_url, "dark": dark_url}


def order_metrics_by_plot_preference(metrics: list[str]) -> tuple[list[str], dict]:
    """
    Order metrics based on TRACKIO_PLOT_ORDER environment variable and group them.

    Args:
        metrics: List of metric names to order and group

    Returns:
        Tuple of (ordered_group_names, grouped_metrics_dict)
    """
    plot_order_env = os.environ.get("TRACKIO_PLOT_ORDER", "")
    if not plot_order_env.strip():
        plot_order = []
    else:
        plot_order = [
            item.strip() for item in plot_order_env.split(",") if item.strip()
        ]

    def get_metric_priority(metric: str) -> tuple[int, int, str]:
        if not plot_order:
            return (float("inf"), float("inf"), metric)

        group_prefix = metric.split("/")[0] if "/" in metric else "charts"
        no_match_priority = len(plot_order)

        group_priority = no_match_priority
        for i, pattern in enumerate(plot_order):
            pattern_group = pattern.split("/")[0] if "/" in pattern else "charts"
            if pattern_group == group_prefix:
                group_priority = i
                break

        within_group_priority = no_match_priority
        for i, pattern in enumerate(plot_order):
            if pattern == metric:
                within_group_priority = i
                break
            elif pattern.endswith("/*") and within_group_priority == no_match_priority:
                pattern_prefix = pattern[:-2]
                if metric.startswith(pattern_prefix + "/"):
                    within_group_priority = i + len(plot_order)

        return (group_priority, within_group_priority, metric)

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
        group_data["direct_metrics"].sort(key=get_metric_priority)
        for subgroup_name in group_data["subgroups"]:
            group_data["subgroups"][subgroup_name].sort(key=get_metric_priority)

    if "charts" in result and not result["charts"]["direct_metrics"]:
        del result["charts"]

    def get_group_priority(group_name: str) -> tuple[int, str]:
        if not plot_order:
            return (float("inf"), group_name)

        min_priority = len(plot_order)
        for i, pattern in enumerate(plot_order):
            pattern_group = pattern.split("/")[0] if "/" in pattern else "charts"
            if pattern_group == group_name:
                min_priority = min(min_priority, i)
        return (min_priority, group_name)

    ordered_groups = sorted(result.keys(), key=get_group_priority)

    return ordered_groups, result


def persistent_storage_enabled() -> bool:
    return (
        os.environ.get("PERSISTANT_STORAGE_ENABLED") == "true"
    )  # typo in the name of the environment variable


def _get_trackio_dir() -> Path:
    if persistent_storage_enabled():
        return Path("/data/trackio")
    elif os.environ.get("TRACKIO_DIR"):
        return Path(os.environ.get("TRACKIO_DIR"))
    return Path(HF_HOME) / "trackio"


TRACKIO_DIR = _get_trackio_dir()
MEDIA_DIR = TRACKIO_DIR / "media"
FILES_DIR = TRACKIO_DIR / "files"


def get_or_create_project_hash(project: str) -> str:
    hash_path = TRACKIO_DIR / f"{project}.hash"
    if hash_path.exists():
        return hash_path.read_text().strip()
    hash_value = secrets.token_urlsafe(8)
    TRACKIO_DIR.mkdir(parents=True, exist_ok=True)
    hash_path.write_text(hash_value)
    return hash_value


def generate_readable_name(used_names: list[str], space_id: str | None = None) -> str:
    """
    Generates a random, readable name like "dainty-sunset-0".
    If space_id is provided, generates username-timestamp format instead.
    """
    if space_id is not None:
        username = _get_default_namespace()
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


def is_in_notebook():
    """
    Detect if code is running in a notebook environment (Jupyter, Colab, etc.).
    """
    try:
        from IPython import get_ipython

        if get_ipython() is not None:
            return get_ipython().__class__.__name__ in [
                "ZMQInteractiveShell",  # Jupyter notebook/lab
                "Shell",  # IPython terminal
            ] or "google.colab" in str(get_ipython())
    except ImportError:
        pass
    return False


def block_main_thread_until_keyboard_interrupt():
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
    ORANGE = "\033[38;5;208m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    print("* View dashboard by running in your terminal:")
    print(f'{BOLD}{ORANGE}trackio show --project "{project}"{RESET}')
    print(f'* or by running in Python: trackio.show(project="{project}")')


def preprocess_space_and_dataset_ids(
    space_id: str | None, dataset_id: str | None
) -> tuple[str | None, str | None]:
    """
    Preprocesses the Space and Dataset names to ensure they are valid "username/space_id" or "username/dataset_id" format.
    """
    if space_id is not None and "/" not in space_id:
        username = _get_default_namespace()
        space_id = f"{username}/{space_id}"
    if dataset_id is not None and "/" not in dataset_id:
        username = _get_default_namespace()
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


def format_timestamp(timestamp_str):
    """Convert ISO timestamp to human-readable format like '3 minutes ago'."""
    if not timestamp_str or pd.isna(timestamp_str):
        return "Unknown"

    try:
        created_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        if created_time.tzinfo is None:
            created_time = created_time.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        diff = now - created_time

        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "Just now"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = seconds // 86400
            return f"{days} day{'s' if days != 1 else ''} ago"
    except Exception:
        return "Unknown"


DEFAULT_COLOR_PALETTE = [
    "#A8769B",
    "#E89957",
    "#3B82F6",
    "#10B981",
    "#EF4444",
    "#8B5CF6",
    "#14B8A6",
    "#F59E0B",
    "#EC4899",
    "#06B6D4",
]


def get_color_palette() -> list[str]:
    """Get the color palette from environment variable or use default."""
    env_palette = os.environ.get("TRACKIO_COLOR_PALETTE")
    if env_palette:
        return [color.strip() for color in env_palette.split(",")]
    return DEFAULT_COLOR_PALETTE


def get_color_mapping(
    runs: list[str], smoothing: bool, color_palette: list[str] | None = None
) -> dict[str, str]:
    """Generate color mapping for runs, with transparency for original data when smoothing is enabled."""
    if color_palette is None:
        color_palette = get_color_palette()

    color_map = {}

    for i, run in enumerate(runs):
        base_color = color_palette[i % len(color_palette)]

        if smoothing:
            color_map[run] = base_color + "4D"
            color_map[f"{run}_smoothed"] = base_color
        else:
            color_map[run] = base_color

    return color_map


def downsample(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str | None,
    x_lim: tuple[float | None, float | None] | None = None,
) -> tuple[pd.DataFrame, tuple[float, float] | None]:
    """
    Downsample the dataframe to reduce the number of points plotted.
    Also updates the x-axis limits to the data min/max if either of the x-axis limits are None.

    Args:
        df: The dataframe to downsample.
        x: The column name to use for the x-axis.
        y: The column name to use for the y-axis.
        color: The column name to use for the color.
        x_lim: The x-axis limits to use.

    Returns:
        A tuple containing the downsampled dataframe and the updated x-axis limits.
    """
    if df.empty:
        if x_lim is not None:
            x_lim = (x_lim[0] or 0, x_lim[1] or 0)
        return df, x_lim

    columns_to_keep = [x, y]
    if color is not None and color in df.columns:
        columns_to_keep.append(color)
    df = df[columns_to_keep].copy()

    data_x_min = df[x].min()
    data_x_max = df[x].max()

    if x_lim is not None:
        x_min, x_max = x_lim
        if x_min is None:
            x_min = data_x_min
        if x_max is None:
            x_max = data_x_max
        updated_x_lim = (x_min, x_max)
    else:
        updated_x_lim = None

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

        if updated_x_lim is not None:
            x_min, x_max = updated_x_lim
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

    if color is not None:
        downsampled_df = (
            downsampled_df.groupby(color, sort=False)[downsampled_df.columns]
            .apply(lambda group: group.sort_values(x))
            .reset_index(drop=True)
        )
    else:
        downsampled_df = downsampled_df.sort_values(x).reset_index(drop=True)

    downsampled_df = downsampled_df.drop(columns=["bin"], errors="ignore")

    return downsampled_df, updated_x_lim


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


def get_sync_status(scheduler: "CommitScheduler | DummyCommitScheduler") -> int | None:
    """Get the sync status from the CommitScheduler in an integer number of minutes, or None if not synced yet."""
    if getattr(
        scheduler, "last_push_time", None
    ):  # DummyCommitScheduler doesn't have last_push_time
        time_diff = time.time() - scheduler.last_push_time
        return int(time_diff / 60)
    else:
        return None


def generate_embed_code(project: str, metrics: str, selected_runs: list = None) -> str:
    """Generate the embed iframe code based on current settings."""
    space_host = os.environ.get("SPACE_HOST", "")
    if not space_host:
        return ""

    params = []

    if project:
        params.append(f"project={project}")

    if metrics and metrics.strip():
        params.append(f"metrics={metrics}")

    if selected_runs:
        runs_param = ",".join(selected_runs)
        params.append(f"runs={runs_param}")

    params.append("sidebar=hidden")
    params.append("navbar=hidden")

    query_string = "&".join(params)
    embed_url = f"https://{space_host}?{query_string}"

    return f'<iframe src="{embed_url}" style="width:1600px; height:500px; border:0;"></iframe>'


def serialize_values(metrics):
    """
    Serialize infinity and NaN values in metrics dict to make it JSON-compliant.
    Only handles top-level float values.

    Converts:
    - float('inf') -> "Infinity"
    - float('-inf') -> "-Infinity"
    - float('nan') -> "NaN"

    Example:
        {"loss": float('inf'), "accuracy": 0.95} -> {"loss": "Infinity", "accuracy": 0.95}
    """
    if not isinstance(metrics, dict):
        return metrics

    result = {}
    for key, value in metrics.items():
        if isinstance(value, float):
            if math.isinf(value):
                result[key] = "Infinity" if value > 0 else "-Infinity"
            elif math.isnan(value):
                result[key] = "NaN"
            else:
                result[key] = value
        elif isinstance(value, np.floating):
            float_val = float(value)
            if math.isinf(float_val):
                result[key] = "Infinity" if float_val > 0 else "-Infinity"
            elif math.isnan(float_val):
                result[key] = "NaN"
            else:
                result[key] = float_val
        else:
            result[key] = value
    return result


def deserialize_values(metrics):
    """
    Deserialize infinity and NaN string values back to their numeric forms.
    Only handles top-level string values.

    Converts:
    - "Infinity" -> float('inf')
    - "-Infinity" -> float('-inf')
    - "NaN" -> float('nan')

    Example:
        {"loss": "Infinity", "accuracy": 0.95} -> {"loss": float('inf'), "accuracy": 0.95}
    """
    if not isinstance(metrics, dict):
        return metrics

    result = {}
    for key, value in metrics.items():
        if value == "Infinity":
            result[key] = float("inf")
        elif value == "-Infinity":
            result[key] = float("-inf")
        elif value == "NaN":
            result[key] = float("nan")
        else:
            result[key] = value
    return result


def get_full_url(
    base_url: str, project: str | None, write_token: str, footer: bool = True
) -> str:
    params = []
    if project:
        params.append(f"project={project}")
    params.append(f"write_token={write_token}")
    if not footer:
        params.append("footer=false")
    return base_url + "?" + "&".join(params)


def embed_url_in_notebook(url: str) -> None:
    try:
        from IPython.display import HTML, display

        embed_code = HTML(
            f'<div><iframe src="{url}" width="100%" height="1000px" allow="autoplay; camera; microphone; clipboard-read; clipboard-write;" frameborder="0" allowfullscreen></iframe></div>'
        )
        display(embed_code)
    except ImportError:
        pass


def to_json_safe(obj):
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_json_safe(v) for v in obj]
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return to_json_safe(obj.to_dict())
    if hasattr(obj, "__dict__"):
        return {
            str(k): to_json_safe(v)
            for k, v in vars(obj).items()
            if not k.startswith("_")
        }
    return str(obj)


def get_space() -> str | None:
    """
    Get the space ID ("user/space") if Trackio is running in a Space, or None if not.
    """
    return os.environ.get("SPACE_ID")


def ordered_subset(items: list[str], subset: list[str] | None) -> list[str]:
    subset_set = set(subset or [])
    return [item for item in items if item in subset_set]


def _get_default_namespace() -> str:
    """Get the default namespace (username).

    This function uses caching to avoid repeated API calls to /whoami-v2.
    """
    token = huggingface_hub.get_token()
    return _cached_whoami(token)["name"]


@lru_cache(maxsize=32)
def _cached_whoami(token: str | None) -> dict:
    return huggingface_hub.whoami(token=token)
