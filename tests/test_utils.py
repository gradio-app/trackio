import random
from unittest.mock import patch

from trackio import utils


def test_generate_readable_names_are_unique_even_with_seed():
    names = []
    for _ in range(10):
        random.seed(42)
        names.append(utils.generate_readable_name(names))
    assert len(names) == len(set(names))


@patch("huggingface_hub.whoami")
@patch("time.time")
def test_generate_readable_name_with_space_id(mock_time, mock_whoami):
    # Mock the HF username and timestamp
    mock_whoami.return_value = {"name": "testuser"}
    mock_time.return_value = 1234567890

    # Test with space_id provided
    name = utils.generate_readable_name(
        ["existing_name"], space_id="testuser/test-space"
    )
    assert name == "testuser-1234567890"

    # Test that used_names parameter is ignored when space_id is provided
    name2 = utils.generate_readable_name(
        ["testuser-1234567890"], space_id="testuser/test-space"
    )
    assert name2 == "testuser-1234567890"  # Same name, no uniqueness check


def test_generate_readable_name_without_space_id():
    # Test that normal behavior still works when space_id is None
    name = utils.generate_readable_name([])
    assert "-" in name  # Should have adjective-noun-number format
    assert name.count("-") == 2  # Should have exactly 2 hyphens
