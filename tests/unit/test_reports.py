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

{{ artifact path="reports/artifacts/chart.png" caption="Chart" }}

{{ file path="reports/artifacts/model.safetensors" caption="Weights" }}

{{ trackio url="https://abidlabs-demo.hf.space/?project=mixtures&sidebar=hidden" }}
""",
        encoding="utf-8",
    )

    manifest = reports.build_report(tmp_path)
    html = (tmp_path / "dist" / "index.html").read_text(encoding="utf-8")

    assert len(manifest["pages"]) == 3
    assert any(page["parent"] == "index.md" for page in manifest["pages"])
    assert all(page["path"] != page["parent"] for page in manifest["pages"])
    assert "https://huggingface.co/buckets/abidlabs/report-bucket/resolve/reports/artifacts/chart.png" in html
    assert '<iframe class="trackio-embed"' in html
    assert "Data mixtures" in html


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
