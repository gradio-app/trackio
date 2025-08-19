import random

from trackio import utils


def test_generate_readable_names_are_unique_even_with_seed():
    names = []
    for _ in range(10):
        random.seed(42)
        names.append(utils.generate_readable_name(names))
    assert len(names) == len(set(names))
