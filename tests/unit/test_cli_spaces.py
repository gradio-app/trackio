import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from trackio import cli


def test_list_spaces_uses_authenticated_user_and_orgs(monkeypatch, capsys):
    import huggingface_hub

    calls = []
    spaces_by_author = {
        "alice": [
            SimpleNamespace(
                id="alice/old-dashboard",
                author="alice",
                private=False,
                sdk="gradio",
                host=None,
                subdomain="alice-old-dashboard",
                last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                tags=["trackio"],
            )
        ],
        "team": [
            SimpleNamespace(
                id="team/new-dashboard",
                author="team",
                private=True,
                sdk="gradio",
                host="https://team-new-dashboard.hf.space",
                subdomain=None,
                last_modified=datetime(2024, 2, 1, tzinfo=timezone.utc),
                created_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
                tags=["trackio"],
            )
        ],
    }

    class FakeHfApi:
        def __init__(self, token=None):
            self.token = token

        def whoami(self, token=None, cache=True):
            assert token == "cached-token"
            assert cache is True
            return {"name": "alice", "orgs": [{"name": "team"}]}

        def list_spaces(self, **kwargs):
            calls.append(kwargs)
            return spaces_by_author[kwargs["author"]]

    monkeypatch.setattr(huggingface_hub, "HfApi", FakeHfApi)
    monkeypatch.setattr(huggingface_hub.utils, "get_token", lambda: "cached-token")
    monkeypatch.setattr(
        sys, "argv", ["trackio", "list", "spaces", "--limit", "1", "--json"]
    )

    cli.main()

    result = json.loads(capsys.readouterr().out)
    assert [space["id"] for space in result["spaces"]] == ["team/new-dashboard"]
    assert result["spaces"][0]["private"] is True
    assert result["spaces"][0]["url"] == "https://team-new-dashboard.hf.space"
    assert calls == [
        {
            "author": "alice",
            "filter": "trackio",
            "full": True,
            "token": "cached-token",
        },
        {
            "author": "team",
            "filter": "trackio",
            "full": True,
            "token": "cached-token",
        },
    ]


def test_list_spaces_author_does_not_require_login(monkeypatch, capsys):
    import huggingface_hub

    class FakeHfApi:
        def __init__(self, token=None):
            self.token = token

        def list_spaces(self, **kwargs):
            assert kwargs["author"] == "trackio"
            assert kwargs["token"] is None
            return [
                SimpleNamespace(
                    id="trackio/demo",
                    author="trackio",
                    private=False,
                    sdk="gradio",
                    host=None,
                    subdomain="trackio-demo",
                    last_modified=None,
                    created_at=None,
                    tags=["trackio"],
                )
            ]

    monkeypatch.setattr(huggingface_hub, "HfApi", FakeHfApi)
    monkeypatch.setattr(huggingface_hub.utils, "get_token", lambda: None)
    monkeypatch.setattr(sys, "argv", ["trackio", "list", "spaces", "--author", "trackio"])

    cli.main()

    output = capsys.readouterr().out
    assert "Trackio Spaces:" in output
    assert "trackio/demo (public)" in output
    assert "https://trackio-demo.hf.space" in output


def test_list_spaces_requires_login_without_author(monkeypatch, capsys):
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub.utils, "get_token", lambda: None)
    monkeypatch.setattr(sys, "argv", ["trackio", "list", "spaces"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "huggingface-cli login" in capsys.readouterr().err
