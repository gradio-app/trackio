from importlib.metadata import version

import trackio


def test_carbonteq_distribution_and_import_versions_match() -> None:
    assert version("carbonteq-trackio") == trackio.__version__
