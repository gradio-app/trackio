import os
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import huggingface_hub
import numpy as np
import pandas as pd
from huggingface_hub.constants import HF_HOME

_WHOAMI_CACHE: str | None = None

RESERVED_KEYS = ["project", "run", "timestamp", "step", "time"]
TRACKIO_DIR = os.path.join(HF_HOME, "trackio")
PROJECTS_INDEX_PATH = os.path.join(TRACKIO_DIR, "projects_index.json")

TRACKIO_LOGO_PATH = str(Path(__file__).parent.joinpath("trackio_logo.png"))

# Word lists used for generating readable run names. Stored as tuples to
# avoid accidental modification and reduce per-process memory overhead.
ADJECTIVES = (
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
)

NOUNS = (
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
    "boulder",
    "cobble",
    "sand",
    "wavelet",
    "tide",
    "current",
)

# Precompiled regex for column simplification
SIMPLIFY_REGEX = re.compile(r"[^a-zA-Z0-9/]")


# Keep track of generated names to avoid duplicates in constant time.
_NAME_COUNTER: defaultdict[str, int] = defaultdict(int)


def generate_readable_name() -> str:
    """Generate a random, human readable name like ``dainty-sunset-1``."""
    base = f"{random.choice(ADJECTIVES)}-{random.choice(NOUNS)}"
    number = _NAME_COUNTER[base]
    _NAME_COUNTER[base] += 1
    return f"{base}-{number}"


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
    """Vectorized simplification of column names."""
    if not columns:
        return {}

    s = pd.Series(columns)
    cleaned = s.str.replace(SIMPLIFY_REGEX, "", regex=True).str.slice(0, 10)
    cleaned = cleaned.fillna("col")

    result = []
    counter: defaultdict[str, int] = defaultdict(int)
    for base in cleaned:
        suffix = counter[base]
        result.append(base if suffix == 0 else f"{base}_{suffix}")
        counter[base] += 1

    return dict(zip(columns, result))


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


def downsample_df(df: "pd.DataFrame", max_points: int) -> "pd.DataFrame":
    """Return a subset of ``df`` limited to ``max_points`` rows."""
    if len(df) <= max_points:
        return df

    indices = np.linspace(0, len(df) - 1, num=max_points, dtype=int)
    return df.iloc[indices].reset_index(drop=True)


def preprocess_space_and_dataset_ids(
    space_id: str | None, dataset_id: str | None
) -> tuple[str | None, str | None]:
    username = None
    if (space_id and "/" not in space_id) or (dataset_id and "/" not in dataset_id):
        global _WHOAMI_CACHE
        if _WHOAMI_CACHE is None:
            try:
                _WHOAMI_CACHE = huggingface_hub.whoami(token=False)["name"]
            except Exception:
                _WHOAMI_CACHE = "user"
        username = _WHOAMI_CACHE

    if space_id is not None and "/" not in space_id and username is not None:
        space_id = f"{username}/{space_id}"
    if dataset_id is not None and "/" not in dataset_id and username is not None:
        dataset_id = f"{username}/{dataset_id}"
    if space_id is not None and dataset_id is None:
        dataset_id = f"{space_id}_dataset"
    return space_id, dataset_id


def fibo():
    """Generator for Fibonacci backoff: 1, 1, 2, 3, 5, 8, ..."""
    a, b = 1, 1
    while True:
        yield a
        a, b = b, a + b
