"""CLI safety tests for abandoned artifact-upload cleanup."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

from trackio import cli, utils
from trackio.resumable_uploads import create_or_resume_session


def test_cleanup_uploads_defaults_to_dry_run_and_requires_apply(
    temp_dir,
    monkeypatch,
    capsys,
):
    project = "cleanup-cli"
    session = create_or_resume_session(
        project=project,
        digest="a" * 64,
        size_bytes=10,
        idempotency_key="cleanup-client-key-0001",
    )
    metadata = (
        utils.project_artifacts_dir(project)
        / "uploads"
        / session["upload_id"]
        / "session.json"
    )
    payload = json.loads(metadata.read_text())
    payload["updated_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    metadata.write_text(json.dumps(payload))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trackio",
            "cleanup-uploads",
            "--project",
            project,
            "--older-than-hours",
            "24",
            "--json",
        ],
    )
    cli.main()
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["dry_run"] is True
    assert dry_run["session_count"] == 1
    assert metadata.exists()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trackio",
            "cleanup-uploads",
            "--project",
            project,
            "--older-than-hours",
            "24",
            "--apply",
            "--json",
        ],
    )
    cli.main()
    applied = json.loads(capsys.readouterr().out)
    assert applied["dry_run"] is False
    assert applied["session_count"] == 1
    assert not metadata.exists()
