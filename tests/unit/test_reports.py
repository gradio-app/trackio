import json

import pytest

from trackio import reports


def test_init_report_writes_agent_contract(tmp_path):
    reports.init_report(
        tmp_path,
        space_id="abidlabs/report",
        bucket_id="abidlabs/report-bucket",
    )

    assert (tmp_path / "REPORTS.md").exists()
    assert (tmp_path / ".trackio" / "reports.schema.json").exists()
    assert (tmp_path / "reports" / "index.md").exists()

    config = reports.load_config(tmp_path)
    assert config.space_id == "abidlabs/report"
    assert config.bucket_id == "abidlabs/report-bucket"


def test_build_report_renders_nested_pages_and_shortcodes(tmp_path):
    reports.init_report(tmp_path, bucket_id="abidlabs/report-bucket")
    nested_index = tmp_path / "reports" / "experiments" / "index.md"
    nested_index.parent.mkdir()
    nested_index.write_text(
        "---\ntitle: Experiments\n---\n\n# Experiments\n",
        encoding="utf-8",
    )
    page = tmp_path / "reports" / "experiments" / "mixtures.md"
    page.write_text(
        """---
title: Data mixtures
---

# Data mixtures

{{ artifact path="reports/artifacts/chart.png" data="reports/artifacts/chart.json" caption="Chart" }}

{{ file path="reports/artifacts/model.safetensors" caption="Weights" }}

{{ trackio url="https://abidlabs-demo.hf.space/?project=mixtures&sidebar=hidden" }}
""",
        encoding="utf-8",
    )

    manifest = reports.build_report(tmp_path)
    html = (tmp_path / "dist" / "index.html").read_text(encoding="utf-8")
    child_html = (tmp_path / "dist" / "experiments" / "mixtures.html").read_text(
        encoding="utf-8"
    )

    assert len(manifest["pages"]) == 3
    assert any(page["parent"] == "index.md" for page in manifest["pages"])
    assert all(page["path"] != page["parent"] for page in manifest["pages"])
    assert manifest["dashboards"][0]["project"] == "mixtures"
    assert manifest["dashboards"][0]["space_url"] == "https://abidlabs-demo.hf.space"
    assert manifest["dashboards"][0]["cli_commands"][0].startswith(
        'trackio list runs --project "mixtures"'
    )
    assert manifest["artifacts"][0]["kind"] == "image"
    assert manifest["artifacts"][0]["raw_data_path"] == "reports/artifacts/chart.json"
    assert "&sidebar=hidden" not in manifest["dashboards"][0]["cli_commands"][0]
    assert "https://huggingface.co/buckets/abidlabs/report-bucket/resolve/reports/artifacts/chart.png" in child_html
    assert '<iframe class="trackio-embed"' in child_html
    assert "When a human reads this report, they get an embedded Trackio dashboard" in child_html
    assert "When a human reads this report, they see an embedded image" in child_html
    assert '<aside>' not in html
    assert "background: var(--bg)" in html
    assert "#f2efe8" not in html
    assert 'class="linked-pages"' in html
    assert 'href="experiments/mixtures.html"' in html
    assert 'id="page-experiments-mixtures"' not in html
    assert 'class="breadcrumb"' in child_html
    assert 'href="../index.html"' in child_html
    assert "Agent data source:" in child_html
    assert 'data-trackio-project="mixtures"' in child_html
    assert "Data mixtures" in child_html
    assert (tmp_path / "dist" / "agent.md").exists()
    assert (tmp_path / "dist" / "llms.txt").exists()
    assert (tmp_path / "dist" / "_worker.js").exists()
    assert (tmp_path / "dist" / "_headers").exists()
    agent_md = (tmp_path / "dist" / "agent.md").read_text(encoding="utf-8")
    assert "Dashboard URL: https://abidlabs-demo.hf.space/?project=mixtures&sidebar=hidden" in agent_md
    assert "Raw data URL: https://huggingface.co/buckets/abidlabs/report-bucket/resolve/reports/artifacts/chart.json" in agent_md
    assert "trackio list runs --project" in agent_md


def test_render_markdown_treats_soft_line_breaks_as_spaces():
    html = reports.render_markdown(
        """# Summary

This sentence is wrapped
across source lines but should
render as one paragraph.
""",
        reports.ReportConfig(),
    )

    assert (
        "This sentence is wrapped across source lines but should render as one paragraph."
        in html
    )
    assert "<br>" not in html


def test_publish_appends_entry_and_uploads_artifacts(tmp_path, monkeypatch):
    reports.init_report(tmp_path, bucket_id="abidlabs/report-bucket")
    image = tmp_path / "chart.png"
    image.write_bytes(b"png")
    uploaded = []

    monkeypatch.setattr(reports, "create_bucket_if_not_exists", lambda *a, **k: None)
    monkeypatch.setattr(
        reports.huggingface_hub,
        "batch_bucket_files",
        lambda bucket_id, add: uploaded.append((bucket_id, add)),
    )

    result = reports.publish_report(
        tmp_path,
        page="reports/experiments/mixtures.md",
        title="Run 001",
        body="Balanced data improved instruction following.",
        artifacts=[image],
    )

    page_text = (tmp_path / "reports" / "experiments" / "mixtures.md").read_text(
        encoding="utf-8"
    )
    assert result["page"] == "reports/experiments/mixtures.md"
    assert "## Run 001" in page_text
    assert "Balanced data improved instruction following." in page_text
    assert '{{ artifact path="reports/artifacts/experiments/mixtures/' in page_text
    assert uploaded[0][0] == "abidlabs/report-bucket"
    assert uploaded[0][1][0][0] == str(image)


def test_publish_rejects_pages_outside_reports(tmp_path):
    reports.init_report(tmp_path)

    with pytest.raises(ValueError, match="inside 'reports/'"):
        reports.publish_report(
            tmp_path,
            page="notes.md",
            title="Invalid",
            body="Nope",
            upload=False,
        )


def test_deploy_report_uploads_static_space(tmp_path, monkeypatch):
    reports.init_report(
        tmp_path,
        space_id="abidlabs/report",
        bucket_id="abidlabs/report-bucket",
    )
    created = []

    class FakeApi:
        def __init__(self):
            self.files = []
            self.folders = []

        def upload_file(self, **kwargs):
            payload = kwargs["path_or_fileobj"].getvalue().decode("utf-8")
            self.files.append((kwargs["path_in_repo"], payload))

        def upload_folder(self, **kwargs):
            self.folders.append(kwargs)

    fake_api = FakeApi()
    monkeypatch.setattr(reports.huggingface_hub, "HfApi", lambda: fake_api)
    monkeypatch.setattr(
        reports.huggingface_hub,
        "create_repo",
        lambda *args, **kwargs: created.append((args, kwargs)),
    )
    monkeypatch.setattr(reports, "create_bucket_if_not_exists", lambda *a, **k: None)

    space_id = reports.deploy_report(tmp_path)

    assert space_id == "abidlabs/report"
    assert created[0][1]["space_sdk"] == "static"
    assert any(folder["folder_path"].endswith("dist") for folder in fake_api.folders)
    config = json.loads(
        next(payload for path, payload in fake_api.files if path == "config.json")
    )
    assert config["mode"] == "trackio-report"
    assert config["bucket_id"] == "abidlabs/report-bucket"


def test_deploy_report_can_upload_docker_space(tmp_path, monkeypatch):
    reports.init_report(
        tmp_path,
        space_id="abidlabs/report",
        bucket_id="abidlabs/report-bucket",
    )
    created = []

    class FakeApi:
        def __init__(self):
            self.files = []
            self.folders = []

        def upload_file(self, **kwargs):
            payload = kwargs["path_or_fileobj"].getvalue().decode("utf-8")
            self.files.append((kwargs["path_in_repo"], payload))

        def upload_folder(self, **kwargs):
            self.folders.append(kwargs)

    fake_api = FakeApi()
    monkeypatch.setattr(reports.huggingface_hub, "HfApi", lambda: fake_api)
    monkeypatch.setattr(
        reports.huggingface_hub,
        "create_repo",
        lambda *args, **kwargs: created.append((args, kwargs)),
    )
    monkeypatch.setattr(reports, "create_bucket_if_not_exists", lambda *a, **k: None)

    reports.deploy_report(tmp_path, sdk="docker")

    assert created[0][1]["space_sdk"] == "docker"
    assert (tmp_path / "dist" / "Dockerfile").exists()
    assert (tmp_path / "dist" / "server.py").exists()
    assert "Accept: text/markdown" in (tmp_path / "dist" / "agent.md").read_text(
        encoding="utf-8"
    )
    manifest = json.loads((tmp_path / "dist" / "report.json").read_text(encoding="utf-8"))
    assert manifest["space_url"] == "https://abidlabs-report.hf.space"
    config = json.loads(
        next(payload for path, payload in fake_api.files if path == "config.json")
    )
    assert config["sdk"] == "docker"
