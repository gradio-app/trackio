import random
import re
import sys
import time
from pathlib import Path

import huggingface_hub
from huggingface_hub.constants import HF_HOME

RESERVED_KEYS = ["project", "run", "timestamp", "step", "time"]
TRACKIO_DIR = Path(HF_HOME) / "trackio"

TRACKIO_LOGO_PATH = str(Path(__file__).parent.joinpath("trackio_logo.png"))


def generate_readable_name():
    """
    Generates a random, readable name like "dainty-sunset-1"
    """
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
        "boulder",
        "cobble",
        "sand",
        "wavelet",
        "tide",
        "current",
    ]
    adjective = random.choice(adjectives)
    noun = random.choice(nouns)
    number = random.randint(1, 99)
    return f"{adjective}-{noun}-{number}"


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
        dataset_id = f"{space_id}_dataset"
    return space_id, dataset_id


def fibo():
    """Generator for Fibonacci backoff: 1, 1, 2, 3, 5, 8, ..."""
    a, b = 1, 1
    while True:
        yield a
        a, b = b, a + b
