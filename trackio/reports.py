from __future__ import annotations

import html
import io
import json
import mimetypes
import posixpath
import re
import shutil
import socketserver
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import huggingface_hub
from huggingface_hub.errors import HfHubHTTPError

if hasattr(huggingface_hub, "create_bucket"):
    _create_bucket = huggingface_hub.create_bucket
else:
    _create_bucket = None


REPORTS_DIR = "reports"
CONFIG_DIR = ".trackio"
CONFIG_FILE = "config.toml"
SCHEMA_FILE = "reports.schema.json"
DEFAULT_BUILD_DIR = "dist"
REPORT_LOGO_ASSET = "assets/trackio_logo_dark.png"


@dataclass
class ReportConfig:
    space_id: str | None = None
    bucket_id: str | None = None
    reports_dir: str = REPORTS_DIR
    output_dir: str = DEFAULT_BUILD_DIR


@dataclass
class ReportPage:
    source_path: Path
    relative_path: str
    title: str
    body: str
    metadata: dict[str, object]
    url: str
    html: str = ""


def init_report(
    root: str | Path = ".",
    *,
    space_id: str | None = None,
    bucket_id: str | None = None,
    force: bool = False,
) -> None:
    root_path = Path(root)
    reports_dir = root_path / REPORTS_DIR
    trackio_dir = root_path / CONFIG_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    trackio_dir.mkdir(parents=True, exist_ok=True)

    config_path = trackio_dir / CONFIG_FILE
    if force or not config_path.exists():
        config_path.write_text(
            _render_config(space_id=space_id, bucket_id=bucket_id),
            encoding="utf-8",
        )

    schema_path = trackio_dir / SCHEMA_FILE
    if force or not schema_path.exists():
        schema_path.write_text(
            json.dumps(_schema(), indent=2) + "\n",
            encoding="utf-8",
        )

    reports_md_path = root_path / "REPORTS.md"
    if force or not reports_md_path.exists():
        reports_md_path.write_text(_reports_instructions(), encoding="utf-8")

    index_path = reports_dir / "index.md"
    if force or not index_path.exists():
        index_path.write_text(
            """---
title: Experiment Report
---

# Experiment Report

Use this page as the root of the report. Add nested pages by creating Markdown
files and folders inside `reports/`.
""",
            encoding="utf-8",
        )


def load_config(root: str | Path = ".") -> ReportConfig:
    root_path = Path(root)
    config_path = root_path / CONFIG_DIR / CONFIG_FILE
    config = ReportConfig()
    if not config_path.exists():
        return config

    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if key == "space_id":
            config.space_id = value or None
        elif key == "bucket_id":
            config.bucket_id = value or None
        elif key == "reports_dir":
            config.reports_dir = value or REPORTS_DIR
        elif key == "output_dir":
            config.output_dir = value or DEFAULT_BUILD_DIR
    return config


def publish_report(
    root: str | Path = ".",
    *,
    page: str,
    title: str,
    body: str | None = None,
    body_file: str | Path | None = None,
    artifacts: list[str | Path] | None = None,
    bucket_id: str | None = None,
    upload: bool = True,
) -> dict[str, object]:
    root_path = Path(root)
    config = load_config(root_path)
    target_bucket = bucket_id or config.bucket_id
    page_path = root_path / page
    if not _is_relative_to(page_path.resolve(), (root_path / config.reports_dir).resolve()):
        raise ValueError(f"Report page must be inside '{config.reports_dir}/'.")

    page_path.parent.mkdir(parents=True, exist_ok=True)
    if not page_path.exists():
        page_path.write_text(
            f"---\ntitle: {_title_from_path(page_path)}\n---\n\n# {_title_from_path(page_path)}\n",
            encoding="utf-8",
        )

    body_text = body or ""
    if body_file is not None:
        body_text = Path(body_file).read_text(encoding="utf-8")

    artifact_entries: list[dict[str, str]] = []
    if artifacts:
        if upload and not target_bucket:
            raise ValueError(
                "Cannot upload artifacts without a bucket_id. Run `trackio report init "
                "--bucket-id owner/name` or pass `--bucket-id`."
            )
        artifact_entries = _collect_artifacts(
            root_path=root_path,
            page_path=page_path,
            artifact_paths=[Path(p) for p in artifacts],
            bucket_id=target_bucket,
            upload=upload,
        )

    timestamp = datetime.now(timezone.utc).isoformat()
    section = [f"\n\n## {title}\n", f"\n_Published {timestamp}_\n"]
    if body_text.strip():
        section.append("\n" + body_text.strip() + "\n")
    if artifact_entries:
        section.append("\n### Artifacts\n")
        for artifact in artifact_entries:
            shortcode = "artifact" if _is_image_path(artifact["path"]) else "file"
            caption = artifact["name"]
            section.append(
                f'\n{{{{ {shortcode} path="{artifact["path"]}" caption="{caption}" }}}}\n'
            )

    with page_path.open("a", encoding="utf-8") as f:
        f.write("".join(section))

    return {
        "page": str(page_path.relative_to(root_path)),
        "artifacts": artifact_entries,
        "timestamp": timestamp,
    }


def validate_report(root: str | Path = ".") -> list[str]:
    errors: list[str] = []
    root_path = Path(root)
    config = load_config(root_path)
    reports_path = root_path / config.reports_dir
    if not reports_path.exists():
        errors.append(f"Missing reports directory: {config.reports_dir}")
        return errors

    pages = discover_pages(root_path, config)
    if not pages:
        errors.append(f"No Markdown pages found in {config.reports_dir}/")
    index = reports_path / "index.md"
    if not index.exists():
        errors.append(f"Missing root page: {config.reports_dir}/index.md")
    for page in pages:
        if not page.title:
            errors.append(f"Missing title: {page.relative_path}")
    return errors


def build_report(
    root: str | Path = ".",
    *,
    output_dir: str | Path | None = None,
    space_url: str | None = None,
) -> dict[str, object]:
    root_path = Path(root)
    config = load_config(root_path)
    out_path = root_path / (output_dir or config.output_dir)
    pages = discover_pages(root_path, config)
    if not pages:
        raise ValueError(f"No Markdown pages found in {config.reports_dir}/")

    manifest = _build_manifest(pages, config, space_url=space_url)
    for page in pages:
        page.html = render_markdown(page.body, config)

    if out_path.exists():
        shutil.rmtree(out_path)
    out_path.mkdir(parents=True)
    (out_path / "report.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    agent_markdown = _render_agent_markdown(pages, manifest)
    (out_path / "agent.md").write_text(agent_markdown, encoding="utf-8")
    (out_path / "llms.txt").write_text(agent_markdown, encoding="utf-8")
    logo_out = out_path / REPORT_LOGO_ASSET
    logo_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        Path(__file__).resolve().parent / "assets" / "trackio_logo_dark.png",
        logo_out,
    )
    (out_path / "index.html").write_text(
        _render_root_html(pages, manifest),
        encoding="utf-8",
    )
    for page in pages:
        if page.relative_path == "index.md":
            continue
        page_out = out_path / page.url
        page_out.parent.mkdir(parents=True, exist_ok=True)
        page_out.write_text(
            _render_page_html(page, pages, manifest),
            encoding="utf-8",
        )
    return manifest


def deploy_report(
    root: str | Path = ".",
    *,
    space_id: str | None = None,
    bucket_id: str | None = None,
    output_dir: str | Path | None = None,
) -> str:
    root_path = Path(root)
    config = load_config(root_path)
    target_space = space_id or config.space_id
    target_bucket = bucket_id or config.bucket_id
    if not target_space:
        raise ValueError("A Space ID is required. Pass --space-id or configure one.")

    report_url = _static_space_host(target_space)
    manifest = build_report(root_path, output_dir=output_dir, space_url=report_url)
    out_path = root_path / (output_dir or config.output_dir)

    if target_bucket:
        create_bucket_if_not_exists(target_bucket, private=False)

    hf_api = huggingface_hub.HfApi()
    _retry_hf_write(
        "Report Space creation",
        lambda: huggingface_hub.create_repo(
            target_space,
            private=False,
            space_sdk="static",
            repo_type="space",
            exist_ok=True,
        ),
    )
    readme = _space_readme(target_space, target_bucket)
    _retry_hf_write(
        "Report Space README upload",
        lambda: hf_api.upload_file(
            path_or_fileobj=io.BytesIO(readme.encode("utf-8")),
            path_in_repo="README.md",
            repo_id=target_space,
            repo_type="space",
        ),
    )
    _retry_hf_write(
        "Report Space upload",
        lambda: hf_api.upload_folder(
            repo_id=target_space,
            repo_type="space",
            folder_path=str(out_path),
        ),
    )
    config_payload = {
        "mode": "trackio-report",
        "bucket_id": target_bucket,
        "manifest": "report.json",
        "pages": len(manifest["pages"]),
    }
    _retry_hf_write(
        "Report Space config upload",
        lambda: hf_api.upload_file(
            path_or_fileobj=io.BytesIO(json.dumps(config_payload).encode("utf-8")),
            path_in_repo="config.json",
            repo_id=target_space,
            repo_type="space",
        ),
    )
    return target_space


def preview_report(
    root: str | Path = ".",
    *,
    output_dir: str | Path | None = None,
    port: int = 7860,
) -> None:
    root_path = Path(root)
    config = load_config(root_path)
    build_report(root_path, output_dir=output_dir)
    out_path = root_path / (output_dir or config.output_dir)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(out_path), **kwargs)

    with socketserver.TCPServer(("", port), Handler) as httpd:
        url = f"http://127.0.0.1:{port}"
        print(f"Serving Trackio report at {url}")
        webbrowser.open(url)
        httpd.serve_forever()


def discover_pages(root: Path, config: ReportConfig) -> list[ReportPage]:
    reports_path = root / config.reports_dir
    pages: list[ReportPage] = []
    for path in sorted(reports_path.rglob("*.md")):
        metadata, body = _split_frontmatter(path.read_text(encoding="utf-8"))
        rel = path.relative_to(reports_path).as_posix()
        title = str(metadata.get("title") or _extract_heading(body) or _title_from_path(path))
        url = "index.html" if rel == "index.md" else quote(rel.removesuffix(".md") + ".html")
        pages.append(
            ReportPage(
                source_path=path,
                relative_path=rel,
                title=title,
                body=body,
                metadata=metadata,
                url=url,
            )
        )
    return pages


def render_markdown(markdown: str, config: ReportConfig) -> str:
    markdown = _render_shortcodes(markdown, config)
    blocks = re.split(r"\n{2,}", markdown.strip())
    rendered: list[str] = []
    in_list = False
    for block in blocks:
        lines = block.splitlines()
        if all(line.startswith(("- ", "* ")) for line in lines if line.strip()):
            if not in_list:
                rendered.append("<ul>")
                in_list = True
            for line in lines:
                rendered.append(f"<li>{_inline_markdown(line[2:].strip())}</li>")
            continue
        if in_list:
            rendered.append("</ul>")
            in_list = False

        first = lines[0] if lines else ""
        if first.startswith("#"):
            hashes = len(first) - len(first.lstrip("#"))
            if 1 <= hashes <= 6 and first[hashes : hashes + 1] == " ":
                level = min(hashes, 4)
                text = first[hashes:].strip()
                rendered.append(f"<h{level}>{_inline_markdown(text)}</h{level}>")
                rest = "\n".join(lines[1:]).strip()
                if rest:
                    rendered.append(f"<p>{_inline_markdown(_paragraph_text(rest))}</p>")
                continue
        if block.lstrip().startswith("<"):
            rendered.append(block)
        else:
            rendered.append(f"<p>{_inline_markdown(_paragraph_text(block))}</p>")

    if in_list:
        rendered.append("</ul>")
    return "\n".join(rendered)


def create_bucket_if_not_exists(bucket_id: str, private: bool | None = None) -> None:
    if _create_bucket is None:
        raise RuntimeError("This huggingface_hub version does not support HF Buckets.")
    _create_bucket(bucket_id, private=private, exist_ok=True)


def _render_config(*, space_id: str | None, bucket_id: str | None) -> str:
    return (
        f'space_id = "{space_id or ""}"\n'
        f'bucket_id = "{bucket_id or ""}"\n'
        f'reports_dir = "{REPORTS_DIR}"\n'
        f'output_dir = "{DEFAULT_BUILD_DIR}"\n'
    )


def _reports_instructions() -> str:
    return """# Trackio Reports

This repository is a Trackio Report. Agents should use the commands below instead
of editing generated files directly.

## Structure

- `reports/index.md` is the root page.
- Nested report pages are Markdown files inside `reports/`.
- Folder structure defines page nesting.
- `.trackio/config.toml` stores the default Space, Bucket, and build output.
- `.trackio/reports.schema.json` documents the generated manifest shape.
- `dist/` is generated by `trackio report build` and should not be hand-edited.
- The generated report has a main article page plus separate static pages for
  nested Markdown files. Linked page cards navigate between pages, and nested
  pages include breadcrumbs back to the main report.
- Trackio embeds expose `data-trackio-url`, `data-trackio-project`, and
  `data-trackio-metrics` attributes in HTML, plus dashboard metadata and CLI
  commands in `dist/report.json`.
- `dist/agent.md` and `dist/llms.txt` are compact machine-readable summaries for
  coding agents. Agents should fetch these files, or `dist/report.json`, instead
  of spending tokens on browser HTML.

## Commands

```sh
trackio report publish --page reports/experiments/run.md --title "Run summary" --body notes.md --artifact outputs/
trackio report validate
trackio report build
trackio report deploy
```

## Shortcodes

```md
{{ artifact path="reports/artifacts/run/chart.png" data="reports/artifacts/run/chart.json" caption="Evaluation chart" }}
{{ file path="reports/artifacts/run/model.safetensors" caption="Model weights" }}
{{ trackio url="https://owner-space.static.hf.space/?project=my-project&sidebar=hidden" }}
```

Artifact paths are relative to the configured HF Bucket. Trackio dashboard embeds
must use public URLs when the report is deployed as a static Space.

Agents should read `dist/report.json` to discover source pages, artifact bucket
paths, embedded dashboard URLs, Trackio project names, metric filters, and
suggested `trackio` CLI commands.
"""


def _schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Trackio Report Manifest",
        "type": "object",
        "required": ["version", "pages"],
        "properties": {
            "version": {"type": "integer"},
            "generated_at": {"type": "string"},
            "bucket_id": {"type": ["string", "null"]},
            "dashboards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["url", "project", "cli_commands"],
                    "properties": {
                        "url": {"type": "string"},
                        "space_url": {"type": "string"},
                        "project": {"type": ["string", "null"]},
                        "metrics": {"type": "array", "items": {"type": "string"}},
                        "cli_commands": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            "artifacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["path", "url", "page", "kind"],
                    "properties": {
                        "path": {"type": "string"},
                        "url": {"type": "string"},
                        "page": {"type": "string"},
                        "kind": {"type": "string"},
                        "caption": {"type": "string"},
                        "raw_data_path": {"type": "string"},
                        "raw_data_url": {"type": "string"},
                    },
                },
            },
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["path", "title", "url", "parent"],
                    "properties": {
                        "path": {"type": "string"},
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "anchor": {"type": "string"},
                        "parent": {"type": ["string", "null"]},
                    },
                },
            },
        },
    }


def _collect_artifacts(
    *,
    root_path: Path,
    page_path: Path,
    artifact_paths: list[Path],
    bucket_id: str | None,
    upload: bool,
) -> list[dict[str, str]]:
    files: list[Path] = []
    for artifact_path in artifact_paths:
        if artifact_path.is_dir():
            files.extend([p for p in sorted(artifact_path.rglob("*")) if p.is_file()])
        elif artifact_path.is_file():
            files.append(artifact_path)
        else:
            raise FileNotFoundError(f"Artifact not found: {artifact_path}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    page_stem = page_path.relative_to(root_path / REPORTS_DIR).with_suffix("").as_posix()
    prefix = f"reports/artifacts/{page_stem}/{timestamp}"
    uploads: list[tuple[str, str]] = []
    entries: list[dict[str, str]] = []
    for file_path in files:
        remote_path = f"{prefix}/{file_path.name}"
        entries.append(
            {
                "name": file_path.name,
                "path": remote_path,
                "url": _bucket_url(bucket_id, remote_path) if bucket_id else remote_path,
            }
        )
        uploads.append((str(file_path), remote_path))

    if upload and bucket_id and uploads:
        create_bucket_if_not_exists(bucket_id, private=False)
        huggingface_hub.batch_bucket_files(bucket_id, add=uploads)
    return entries


def _build_manifest(
    pages: list[ReportPage], config: ReportConfig, *, space_url: str | None = None
) -> dict[str, object]:
    page_items = []
    all_paths = {page.relative_path for page in pages}
    for page in pages:
        parent = _parent_page(page.relative_path, all_paths)
        page_items.append(
            {
                "path": page.relative_path,
                "title": page.title,
                "url": page.url,
                "anchor": _page_anchor(page.relative_path),
                "parent": parent,
                "metadata": page.metadata,
            }
        )
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "space_id": config.space_id,
        "space_url": space_url
        or (_static_space_host(config.space_id) if config.space_id else None),
        "bucket_id": config.bucket_id,
        "pages": page_items,
        "dashboards": _extract_dashboards(pages),
        "artifacts": _extract_artifacts(pages, config),
    }


def _render_root_html(pages: list[ReportPage], manifest: dict[str, object]) -> str:
    ordered_pages = sorted(
        pages, key=lambda p: (p.relative_path != "index.md", p.relative_path)
    )
    root_page = next(
        (page for page in ordered_pages if page.relative_path == "index.md"),
        ordered_pages[0],
    )
    child_pages = [
        page for page in ordered_pages if page.relative_path != root_page.relative_path
    ]
    return _render_document_html(
        title=root_page.title,
        body_html=(
            f'<div class="root-content" data-report-page="{html.escape(root_page.relative_path)}">'
            f"{root_page.html}</div>{_render_linked_pages(child_pages, from_url=root_page.url)}"
        ),
        manifest=manifest,
        eyebrow="Trackio Report",
        metadata=[
            f"Generated {manifest.get('generated_at', '')}",
            f"{len(ordered_pages)} source page(s)",
            f"{len(manifest.get('dashboards', []))} Trackio dashboard embed(s)",
        ],
    )


def _render_page_html(
    page: ReportPage, pages: list[ReportPage], manifest: dict[str, object]
) -> str:
    child_pages = _direct_child_pages(page, pages)
    body = (
        _render_breadcrumb(page, pages)
        + f'<div class="page-content" data-report-page="{html.escape(page.relative_path)}">{page.html}</div>'
        + _render_linked_pages(child_pages, from_url=page.url)
    )
    return _render_document_html(
        title=page.title,
        body_html=body,
        manifest=manifest,
        eyebrow="Trackio Report Page",
        metadata=[page.relative_path],
        current_page=page.relative_path,
    )


def _render_document_html(
    *,
    title: str,
    body_html: str,
    manifest: dict[str, object],
    eyebrow: str,
    metadata: list[str],
    current_page: str | None = None,
) -> str:
    escaped_title = html.escape(title)
    payload = json.dumps(manifest).replace("</", "<\\/")
    meta_html = "".join(f"<span>{html.escape(str(item))}</span>" for item in metadata)
    logo_src = _relative_url(REPORT_LOGO_ASSET, current_page or "index.html")
    report_url = str(manifest.get("space_url") or "./")
    report_url_html = html.escape(report_url)
    report_url_attr = html.escape(report_url, quote=True)
    current_attr = (
        f' data-current-report-page="{html.escape(current_page)}"'
        if current_page
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <link rel="alternate" type="text/markdown" href="{_relative_url("agent.md", current_page or "index.html")}">
  <style>{_article_css()}</style>
  <script>{_report_interaction_script()}</script>
</head>
<body{current_attr}>
  <main class="article-shell">
    <article class="article-paper">
      <header class="article-header">
        <div class="header-kicker">
          <div class="eyebrow"><img class="eyebrow-logo" src="{html.escape(logo_src, quote=True)}" alt="Trackio"><span>{html.escape(eyebrow.removeprefix("Trackio ").strip())}</span></div>
          <div class="header-actions">
            <button class="hf-login-button" type="button" data-hf-login>
              <span class="hf-mark">hf</span>
              <span class="hf-login-label">Login with HF</span>
            </button>
            <div class="report-url-control" data-report-url="{report_url_attr}">
              <a class="report-url" href="{report_url_attr}">{report_url_html}</a>
              <button class="copy-url-button" type="button" data-copy-url="{report_url_attr}" aria-label="Copy report URL" title="Copy report URL">
                <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              </button>
            </div>
          </div>
        </div>
        <h1 class="article-title">{escaped_title}</h1>
        <div class="article-meta">{meta_html}</div>
      </header>
      <div data-report-article>
        {body_html}
      </div>
      <section class="mock-mlintern-pages" data-mlintern-pages hidden>
        <h2>Agent Generated Pages</h2>
        <div class="page-link-grid" data-mlintern-links></div>
      </section>
      <section class="mock-subpage" data-mock-subpage hidden>
        <nav class="breadcrumb" aria-label="Breadcrumb"><a href="#" data-close-mock-page>{escaped_title}</a><span class="breadcrumb-separator">/</span><span data-mock-page-title>Mock Follow-up</span></nav>
        <h1 data-mock-page-heading>Mock Follow-up</h1>
        <p data-mock-page-summary></p>
        <table>
          <thead><tr><th>Mixture</th><th>MT-Bench</th><th>GSM8K</th><th>HumanEval</th><th>Toxicity</th></tr></thead>
          <tbody>
            <tr><td>code-20-followup</td><td>7.2</td><td>66.4</td><td>40.1</td><td>1.9</td></tr>
            <tr><td>balanced-baseline</td><td>7.4</td><td>64.0</td><td>38.2</td><td>1.8</td></tr>
          </tbody>
        </table>
        <p>The mocked follow-up suggests that reducing code to 20% recovers some math transfer while keeping HumanEval above the balanced baseline. In a real report, this page would be committed by the agent along with Trackio run metadata, raw artifacts, and dashboard links.</p>
        <p><a href="#" data-close-mock-page>Back to report</a></p>
      </section>
    </article>
    <aside class="comment-rail" data-comment-rail aria-label="Report comments">
      <div class="comment-rail-header">
        <strong>Comments</strong>
        <span data-comment-count>0</span>
      </div>
      <div class="comment-empty" data-comment-empty>Select report text to comment.</div>
      <div class="comment-composer" data-comment-composer hidden>
        <div class="selection-label">Comment on</div>
        <blockquote data-selected-text></blockquote>
        <div class="comment-editor" contenteditable="true" role="textbox" aria-label="Write a comment" data-comment-editor></div>
        <div class="comment-preview" data-comment-preview hidden></div>
        <div class="comment-actions">
          <button type="button" class="secondary-button" data-cancel-comment>Cancel</button>
          <button type="button" class="primary-button" data-submit-comment>Comment</button>
        </div>
      </div>
      <div class="comment-thread-list" data-thread-list></div>
    </aside>
  </main>
  <script type="application/json" id="report-manifest">{payload}</script>
</body>
</html>
"""


def _article_css() -> str:
    return """
    :root { color-scheme: light; --paper: #ffffff; --bg: #ffffff; --ink: #111827; --muted: #667085; --line: #e5e7eb; --soft: #f8fafc; --accent: #2563eb; --accent-soft: #eff6ff; --code: #f3f4f6; }
    * { box-sizing: border-box; }
    body { margin: 0; color: var(--ink); background: var(--bg); font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif; }
    a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 3px; }
    .article-shell { max-width: 1380px; margin: 0 auto; padding: 34px 28px 88px; display: grid; grid-template-columns: minmax(0, 1080px) 300px; gap: 28px; align-items: start; }
    .article-paper { background: var(--paper); padding: 16px min(6vw, 72px); }
    .article-header { padding-bottom: 18px; margin-bottom: 28px; }
    .header-kicker { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 16px; }
    .eyebrow { color: var(--accent); font: 700 12px/1.3 ui-sans-serif, system-ui, sans-serif; letter-spacing: 0.08em; text-transform: uppercase; display: inline-flex; align-items: center; gap: 7px; }
    .eyebrow-logo { height: 1em; width: auto; border: 0; background: transparent; display: block; }
    .header-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; min-width: 0; flex: 1; }
    .hf-login-button { min-height: 30px; display: inline-flex; align-items: center; gap: 7px; border: 1px solid var(--line); background: #fff; color: #344054; padding: 4px 10px; cursor: pointer; font: 700 12px/1.3 ui-sans-serif, system-ui, sans-serif; white-space: nowrap; }
    .hf-login-button:hover { border-color: #bfdbfe; background: var(--accent-soft); color: var(--accent); }
    .hf-login-button.signed-in { border-color: #d1d5db; background: #f9fafb; color: #111827; }
    .hf-mark { width: 20px; height: 20px; display: inline-flex; align-items: center; justify-content: center; border-radius: 999px; background: #ffd21e; color: #111827; font: 800 10px/1 ui-sans-serif, system-ui, sans-serif; text-transform: lowercase; letter-spacing: 0; }
    .hf-avatar { width: 22px; height: 22px; border-radius: 999px; border: 1px solid var(--line); display: block; }
    .report-url-control { display: flex; align-items: center; justify-content: flex-end; gap: 8px; min-width: 0; max-width: min(460px, 52%); color: var(--muted); font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .report-url { color: var(--muted); text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .report-url:hover { color: var(--accent); text-decoration: underline; }
    .copy-url-button { width: 28px; height: 28px; flex: 0 0 28px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--line); background: #fff; color: var(--muted); padding: 0; cursor: pointer; }
    .copy-url-button:hover { color: var(--accent); border-color: #bfdbfe; background: var(--accent-soft); }
    .copy-url-button.copied { color: #047857; border-color: #a7f3d0; background: #ecfdf5; }
    .copy-url-button svg { width: 15px; height: 15px; stroke: currentColor; stroke-width: 2; fill: none; stroke-linecap: round; stroke-linejoin: round; }
    .article-title { position: relative; font-size: clamp(30px, 4.8vw, 44px); line-height: 1.1; margin: 0 0 16px; font-weight: 650; letter-spacing: 0; padding-left: 24px; }
    .article-title::before { content: ""; position: absolute; left: 0; top: 0.45em; width: 0; height: 0; border-left: 7px solid #9ca3af; border-top: 5px solid transparent; border-bottom: 5px solid transparent; transform: rotate(90deg); }
    .article-meta { color: var(--muted); font: 14px/1.6 ui-sans-serif, system-ui, sans-serif; display: flex; flex-wrap: wrap; gap: 10px 18px; }
    .root-content > h1:first-child, .page-content > h1:first-child { display: none; }
    .breadcrumb { margin: -8px 0 28px; color: var(--muted); font: 14px/1.5 ui-sans-serif, system-ui, sans-serif; }
    .breadcrumb a { color: var(--muted); text-decoration: none; }
    .breadcrumb a:hover { color: var(--accent); text-decoration: underline; }
    .breadcrumb-separator { padding: 0 8px; color: #98a2b3; }
    h1, h2, h3, h4 { line-height: 1.15; margin: 32px 0 12px; letter-spacing: 0; }
    h1 { font-size: 38px; }
    h2 { font-size: 28px; border-top: 1px solid var(--line); padding-top: 24px; }
    h3 { font-size: 20px; }
    p, li { font-size: 18px; line-height: 1.72; }
    ul { padding-left: 24px; }
    code { background: var(--code); padding: 2px 5px; border-radius: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.9em; }
    .linked-pages { margin: 34px 0 42px; padding: 0; background: white; }
    .linked-pages h2 { border: 0; padding: 0; margin-top: 0; font-size: 22px; }
    .page-link-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
    .page-link { display: block; min-height: 82px; padding: 14px 16px; background: #ffffff; border: 1px solid var(--line); color: var(--ink); text-decoration: none; }
    .page-link:hover { border-color: #c7d2fe; background: var(--accent-soft); }
    .page-link-title { display: block; font: 700 15px/1.35 ui-sans-serif, system-ui, sans-serif; }
    .page-link-path { display: block; color: var(--muted); font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; margin-top: 8px; overflow-wrap: anywhere; }
    .artifact { margin: 28px 0; }
    img { max-width: 100%; border: 1px solid var(--line); background: white; }
    figcaption, .trackio-caption { color: var(--muted); font: 13px/1.55 ui-sans-serif, system-ui, sans-serif; margin-top: 8px; }
    .file-link { display: inline-flex; align-items: center; padding: 9px 12px; border: 1px solid var(--line); color: var(--accent); text-decoration: none; background: #fff; font-family: ui-sans-serif, system-ui, sans-serif; }
    .trackio-dashboard { margin: 32px 0; }
    .trackio-embed { width: 100%; min-height: 560px; border: 1px solid var(--line); background: white; }
    .agent-note { margin-top: 8px; padding: 12px 14px; background: #f8fafc; border-left: 3px solid var(--accent); color: #344054; font: 13px/1.55 ui-sans-serif, system-ui, sans-serif; }
    .agent-note code { background: rgba(255,255,255,0.8); font-size: 12px; }
    .comment-rail { position: sticky; top: 18px; max-height: calc(100vh - 36px); overflow: auto; border-left: 1px solid var(--line); padding-left: 18px; font-family: ui-sans-serif, system-ui, sans-serif; }
    .comment-rail-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; color: #111827; font-size: 14px; }
    .comment-rail-header span { min-width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; border-radius: 999px; background: var(--soft); color: var(--muted); font-size: 12px; }
    .comment-empty { color: var(--muted); border: 1px dashed var(--line); padding: 14px; font-size: 13px; line-height: 1.5; }
    .comment-composer, .comment-thread { border: 1px solid var(--line); background: #fff; padding: 12px; margin-bottom: 12px; box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06); }
    .selection-label { color: var(--muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 5px; }
    .comment-composer blockquote, .comment-selection { margin: 0 0 10px; padding-left: 10px; border-left: 3px solid #facc15; color: #344054; font-size: 12px; line-height: 1.45; }
    .comment-editor { min-height: 78px; outline: none; border: 1px solid var(--line); padding: 9px; color: #111827; font-size: 13px; line-height: 1.45; }
    .comment-editor:empty::before { content: "Write a comment. Try @lewis or @mlintern."; color: #98a2b3; }
    .comment-preview { margin-top: 8px; color: #344054; font-size: 12px; line-height: 1.45; }
    .hf-tag { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 999px; padding: 0 5px; font-weight: 700; white-space: nowrap; }
    .comment-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
    .primary-button, .secondary-button { min-height: 30px; border: 1px solid var(--line); padding: 5px 10px; cursor: pointer; font: 700 12px/1 ui-sans-serif, system-ui, sans-serif; }
    .primary-button { background: var(--accent); border-color: var(--accent); color: #fff; }
    .secondary-button { background: #fff; color: var(--muted); }
    .comment-author { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; margin-bottom: 6px; }
    .comment-avatar { width: 24px; height: 24px; border-radius: 999px; border: 1px solid var(--line); flex: 0 0 24px; }
    .comment-body { color: #344054; font-size: 13px; line-height: 1.5; }
    .comment-reply { border-top: 1px solid var(--line); padding-top: 10px; margin-top: 10px; }
    .mlintern-status { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; margin-top: 8px; }
    .mlintern-spinner { width: 12px; height: 12px; border: 2px solid #dbeafe; border-top-color: var(--accent); border-radius: 999px; animation: spin 0.85s linear infinite; }
    .comment-result-link { display: inline-block; margin-top: 8px; font-weight: 700; }
    .mock-mlintern-pages[hidden], .mock-subpage[hidden], [hidden] { display: none !important; }
    .mock-subpage { border-top: 1px solid var(--line); margin-top: 34px; padding-top: 22px; }
    mark.report-selection { background: #fef3c7; color: inherit; padding: 0 2px; }
    @keyframes spin { to { transform: rotate(360deg); } }
    table { width: 100%; border-collapse: collapse; margin: 24px 0; font: 14px/1.45 ui-sans-serif, system-ui, sans-serif; }
    th, td { border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left; vertical-align: top; }
    th { background: var(--soft); }
    @media (max-width: 1040px) { .article-shell { grid-template-columns: 1fr; } .comment-rail { position: static; max-height: none; border-left: 0; border-top: 1px solid var(--line); padding: 18px 0 0; } }
    @media (max-width: 760px) { .article-shell { padding: 18px 10px 56px; } .article-paper { padding: 18px 10px; } .header-kicker { align-items: flex-start; flex-direction: column; gap: 8px; } .header-actions { width: 100%; justify-content: flex-start; flex-wrap: wrap; } .report-url-control { width: 100%; max-width: 100%; justify-content: flex-start; } .article-title { font-size: 30px; } p, li { font-size: 16px; } .trackio-embed { min-height: 460px; } }
    """


def _report_interaction_script() -> str:
    return """const TRACKIO_MOCK_USER = {
  username: "abidlabs",
  avatar: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='32' fill='%232563eb'/%3E%3Ctext x='32' y='39' text-anchor='middle' font-family='Arial, sans-serif' font-size='24' font-weight='700' fill='white'%3EA%3C/text%3E%3C/svg%3E"
};
const TRACKIO_MOCK_AGENT = {
  username: "mlintern",
  avatar: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='32' fill='%23111827'/%3E%3Ctext x='32' y='39' text-anchor='middle' font-family='Arial, sans-serif' font-size='20' font-weight='700' fill='%23ffd21e'%3EML%3C/text%3E%3C/svg%3E"
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function renderTaggedText(value) {
  return escapeHtml(value).replace(/(^|\\s)(@[a-zA-Z0-9_-]+)/g, '$1<span class="hf-tag">$2</span>');
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy-url]");
  if (!button) return;
  const url = button.getAttribute("data-copy-url");
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
  } catch {
    const input = document.createElement("input");
    input.value = url;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
  button.classList.add("copied");
  window.setTimeout(() => button.classList.remove("copied"), 1200);
});

document.addEventListener("DOMContentLoaded", () => {
  const article = document.querySelector("[data-report-article]");
  const loginButton = document.querySelector("[data-hf-login]");
  const composer = document.querySelector("[data-comment-composer]");
  const selectedTextEl = document.querySelector("[data-selected-text]");
  const editor = document.querySelector("[data-comment-editor]");
  const preview = document.querySelector("[data-comment-preview]");
  const cancelButton = document.querySelector("[data-cancel-comment]");
  const submitButton = document.querySelector("[data-submit-comment]");
  const threadList = document.querySelector("[data-thread-list]");
  const emptyState = document.querySelector("[data-comment-empty]");
  const countEl = document.querySelector("[data-comment-count]");
  const mainArticle = document.querySelector(".article-paper");
  const mockPages = document.querySelector("[data-mlintern-pages]");
  const mockLinks = document.querySelector("[data-mlintern-links]");
  const mockSubpage = document.querySelector("[data-mock-subpage]");
  const mockTitle = document.querySelector("[data-mock-page-title]");
  const mockHeading = document.querySelector("[data-mock-page-heading]");
  const mockSummary = document.querySelector("[data-mock-page-summary]");
  const threads = [];
  const storageKey = `trackio-report-comments:${window.location.pathname}`;
  let activeSelection = "";
  let activeRange = null;
  let generatedPage = null;

  function signIn() {
    if (!loginButton) return;
    loginButton.classList.add("signed-in");
    loginButton.innerHTML = `<img class="hf-avatar" src="${TRACKIO_MOCK_USER.avatar}" alt=""><span>@${TRACKIO_MOCK_USER.username}</span>`;
  }

  function updatePreview() {
    if (!editor || !preview) return;
    const text = editor.innerText.trim();
    if (!text) {
      preview.hidden = true;
      preview.innerHTML = "";
      return;
    }
    preview.hidden = false;
    preview.innerHTML = renderTaggedText(text);
  }

  function resetComposer() {
    activeSelection = "";
    activeRange = null;
    if (composer) composer.hidden = true;
    if (selectedTextEl) selectedTextEl.textContent = "";
    if (editor) editor.innerHTML = "";
    if (preview) {
      preview.hidden = true;
      preview.innerHTML = "";
    }
  }

  function showComposer(text, range) {
    activeSelection = text;
    activeRange = range;
    if (selectedTextEl) selectedTextEl.textContent = text.length > 180 ? `${text.slice(0, 177)}...` : text;
    if (composer) composer.hidden = false;
    if (emptyState) emptyState.hidden = true;
    if (editor) {
      editor.innerHTML = "";
      editor.focus();
    }
    updatePreview();
  }

  function updateCount() {
    const total = threads.reduce((sum, thread) => sum + thread.comments.length, 0);
    if (countEl) countEl.textContent = String(total);
    if (emptyState) emptyState.hidden = threads.length > 0 || (composer && !composer.hidden);
  }

  function saveState() {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify({ threads, generatedPage }));
    } catch {
      // Ignore storage failures in the static demo.
    }
  }

  function loadState() {
    try {
      const stored = JSON.parse(window.localStorage.getItem(storageKey) || "{}");
      if (Array.isArray(stored.threads)) {
        threads.splice(0, threads.length, ...stored.threads);
      }
      if (stored.generatedPage) {
        generatedPage = stored.generatedPage;
        appendGeneratedPageLink(generatedPage);
      }
    } catch {
      // Ignore malformed demo state.
    }
  }

  function renderThreads() {
    if (!threadList) return;
    threadList.innerHTML = threads.map((thread) => {
      const comments = thread.comments.map((comment, index) => `
        <div class="comment-body${index ? " comment-reply" : ""}">
          <div class="comment-author"><img class="comment-avatar" src="${comment.avatar}" alt=""><span>@${comment.author}</span></div>
          <div>${renderTaggedText(comment.text)}</div>
          ${comment.status ? `<div class="mlintern-status"><span class="mlintern-spinner"></span>${escapeHtml(comment.status)}</div>` : ""}
          ${comment.result ? `<a class="comment-result-link" href="#${comment.result.id}" data-open-mock-page="${comment.result.id}">${escapeHtml(comment.result.title)}</a>` : ""}
        </div>
      `).join("");
      return `<section class="comment-thread" data-thread-id="${thread.id}">
        <blockquote class="comment-selection">${escapeHtml(thread.selection)}</blockquote>
        ${comments}
        <div class="comment-actions"><button type="button" class="secondary-button" data-reply-thread="${thread.id}">Reply</button></div>
      </section>`;
    }).join("");
    updateCount();
    saveState();
  }

  function addThread(text) {
    const thread = {
      id: `thread-${Date.now()}-${threads.length}`,
      selection: activeSelection,
      comments: [{ author: TRACKIO_MOCK_USER.username, avatar: TRACKIO_MOCK_USER.avatar, text }],
    };
    threads.unshift(thread);
    renderThreads();
    if (/@(mlintern|mlitern)\\b/i.test(text)) {
      runMockExperiment(thread, text);
    }
  }

  function addReply(threadId, text) {
    const thread = threads.find((item) => item.id === threadId);
    if (!thread) return;
    thread.comments.push({ author: TRACKIO_MOCK_USER.username, avatar: TRACKIO_MOCK_USER.avatar, text });
    renderThreads();
    if (/@(mlintern|mlitern)\\b/i.test(text)) {
      runMockExperiment(thread, text);
    }
  }

  function runMockExperiment(thread, prompt) {
    const agentComment = {
      author: TRACKIO_MOCK_AGENT.username,
      avatar: TRACKIO_MOCK_AGENT.avatar,
      text: "I picked up this request and am running a mocked follow-up experiment.",
      status: "Running local training and evaluation...",
    };
    thread.comments.push(agentComment);
    renderThreads();
    window.setTimeout(() => {
      const result = {
        id: `mlintern-result-${Date.now()}`,
        title: "20% Code Follow-up",
        prompt,
      };
      generatedPage = result;
      agentComment.status = "";
      agentComment.text = "Finished the mocked follow-up. I added a linked report page with the result summary and mock eval table.";
      agentComment.result = result;
      appendGeneratedPageLink(result);
      renderThreads();
    }, 3000);
  }

  function appendGeneratedPageLink(result) {
    if (!mockPages || !mockLinks) return;
    mockPages.hidden = false;
    mockLinks.innerHTML = `<a class="page-link" href="#${result.id}" data-open-mock-page="${result.id}">
      <span class="page-link-title">${escapeHtml(result.title)}</span>
      <span class="page-link-path">experiments/generated/code-20-followup.md</span>
    </a>`;
  }

  function openMockPage() {
    if (!generatedPage || !article || !mockSubpage) return;
    article.hidden = true;
    if (mockPages) mockPages.hidden = true;
    mockSubpage.hidden = false;
    if (mockTitle) mockTitle.textContent = generatedPage.title;
    if (mockHeading) mockHeading.textContent = generatedPage.title;
    if (mockSummary) {
      mockSummary.textContent = `Mocked request: ${generatedPage.prompt}`;
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function closeMockPage() {
    if (!article || !mockSubpage) return;
    article.hidden = false;
    if (mockPages && generatedPage) mockPages.hidden = false;
    mockSubpage.hidden = true;
  }

  loginButton?.addEventListener("click", signIn);
  editor?.addEventListener("input", updatePreview);
  cancelButton?.addEventListener("click", resetComposer);
  submitButton?.addEventListener("click", () => {
    const text = editor?.innerText.trim() || "";
    if (!text || !activeSelection) return;
    signIn();
    addThread(text);
    resetComposer();
  });

  document.addEventListener("mouseup", () => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !article) return;
    const text = selection.toString().trim().replace(/\\s+/g, " ");
    if (!text) return;
    const range = selection.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
    const anchor = selection.anchorNode;
    if (!anchor || !article.contains(anchor.nodeType === Node.TEXT_NODE ? anchor.parentElement : anchor)) return;
    showComposer(text, range);
  });

  threadList?.addEventListener("click", (event) => {
    const replyButton = event.target.closest("[data-reply-thread]");
    if (replyButton) {
      const text = window.prompt("Reply to this thread");
      if (text && text.trim()) {
        signIn();
        addReply(replyButton.getAttribute("data-reply-thread"), text.trim());
      }
      return;
    }
    const resultLink = event.target.closest("[data-open-mock-page]");
    if (resultLink) {
      event.preventDefault();
      openMockPage();
    }
  });

  mainArticle?.addEventListener("click", (event) => {
    const openLink = event.target.closest("[data-open-mock-page]");
    if (openLink) {
      event.preventDefault();
      openMockPage();
      return;
    }
    const closeLink = event.target.closest("[data-close-mock-page]");
    if (closeLink) {
      event.preventDefault();
      closeMockPage();
    }
  });

  loadState();
  renderThreads();

  if (window.location.hash.startsWith("#mlintern-result")) {
    openMockPage();
  }
});"""


def _render_shortcodes(markdown: str, config: ReportConfig) -> str:
    pattern = re.compile(r"\{\{\s*(artifact|file|trackio)\s+([^}]+)\}\}")

    def replace(match: re.Match[str]) -> str:
        kind = match.group(1)
        attrs = _parse_attrs(match.group(2))
        if kind == "trackio":
            url = attrs.get("url", "")
            dashboard = _dashboard_metadata(url)
            project_attr = html.escape(dashboard.get("project") or "", quote=True)
            metrics_attr = html.escape(",".join(dashboard["metrics"]), quote=True)
            command = html.escape(dashboard["cli_commands"][0])
            caption = html.escape(
                attrs.get("caption")
                or (
                    "When a human reads this report, they get an embedded Trackio "
                    "dashboard. Agents can read the hidden dashboard metadata in "
                    "the static HTML or report manifest, then query the dashboard "
                    "programmatically to get the full data."
                )
            )
            return (
                '<figure class="trackio-dashboard" '
                f'data-trackio-url="{html.escape(url, quote=True)}" '
                f'data-trackio-project="{project_attr}" '
                f'data-trackio-metrics="{metrics_attr}">'
                f'<iframe class="trackio-embed" src="{html.escape(url, quote=True)}" '
                'loading="lazy"></iframe>'
                f'<figcaption class="trackio-caption">{caption}</figcaption>'
                '<div class="agent-note">'
                f'Agent data source: <a href="{html.escape(url, quote=True)}">'
                f"{html.escape(url)}</a>. Query it with <code>{command}</code>. "
                "The dashboard URL and CLI hints are available in <code>agent.md</code>, "
                "<code>report.json</code>, and the embedded <code>#report-manifest</code> JSON."
                "</div>"
                "</figure>"
            )
        path = attrs.get("path", "")
        caption = attrs.get("caption") or Path(path).name
        url = attrs.get("url") or _bucket_url(config.bucket_id, path)
        raw_data_path = attrs.get("data") or attrs.get("raw_data")
        raw_data_url = (
            attrs.get("data_url")
            or (_bucket_url(config.bucket_id, raw_data_path) if raw_data_path else "")
        )
        if kind == "artifact" and _is_image_path(path):
            data_attrs = (
                f' data-raw-url="{html.escape(raw_data_url, quote=True)}"'
                f' data-raw-path="{html.escape(raw_data_path or "", quote=True)}"'
                if raw_data_path
                else ""
            )
            note = ""
            if raw_data_path:
                note = (
                    '<div class="agent-note">'
                    "When a human reads this report, they see an embedded image, "
                    "but agents can read hidden metadata that points to raw data "
                    "so they can parse results and update them. Raw data: "
                    f'<a href="{html.escape(raw_data_url, quote=True)}">'
                    f"{html.escape(raw_data_path)}</a>."
                    "</div>"
                )
            return (
                f'<figure class="artifact"{data_attrs}><img src="{html.escape(url, quote=True)}" '
                f'alt="{html.escape(caption, quote=True)}">'
                f"<figcaption>{html.escape(caption)}</figcaption>{note}</figure>"
            )
        return f'<p><a class="file-link" href="{html.escape(url, quote=True)}">{html.escape(caption)}</a></p>'

    return pattern.sub(replace, markdown)


def _render_linked_pages(pages: list[ReportPage], *, from_url: str) -> str:
    if not pages:
        return ""
    links = "\n".join(
        f"""<a class="page-link" href="{html.escape(_relative_url(page.url, from_url), quote=True)}">
  <span class="page-link-title">{html.escape(page.title)}</span>
  <span class="page-link-path">{html.escape(page.relative_path)}</span>
</a>"""
        for page in pages
    )
    return f"""<section class="linked-pages" aria-label="Linked report pages">
  <h2>Linked Pages</h2>
  <div class="page-link-grid">{links}</div>
</section>"""


def _render_breadcrumb(page: ReportPage, pages: list[ReportPage]) -> str:
    by_path = {p.relative_path: p for p in pages}
    crumbs = [
        (
            "LLM Data Mixture Report"
            if by_path.get("index.md") is None
            else by_path["index.md"].title,
            _relative_url("index.html", page.url),
        )
    ]
    parent_path = _parent_page(page.relative_path, {p.relative_path for p in pages})
    chain: list[ReportPage] = []
    while parent_path and parent_path != "index.md":
        parent = by_path.get(parent_path)
        if parent is None:
            break
        chain.append(parent)
        parent_path = _parent_page(parent.relative_path, {p.relative_path for p in pages})
    for parent in reversed(chain):
        crumbs.append((parent.title, _relative_url(parent.url, page.url)))

    links = []
    for title, href in crumbs:
        links.append(f'<a href="{html.escape(href, quote=True)}">{html.escape(title)}</a>')
    links.append(f"<span>{html.escape(page.title)}</span>")
    return (
        '<nav class="breadcrumb" aria-label="Breadcrumb">'
        + '<span class="breadcrumb-separator">/</span>'.join(links)
        + "</nav>"
    )


def _direct_child_pages(page: ReportPage, pages: list[ReportPage]) -> list[ReportPage]:
    all_paths = {p.relative_path for p in pages}
    return [
        candidate
        for candidate in sorted(pages, key=lambda p: p.relative_path)
        if _parent_page(candidate.relative_path, all_paths) == page.relative_path
    ]


def _relative_url(target_url: str, from_url: str) -> str:
    from_dir = posixpath.dirname(from_url)
    start = from_dir if from_dir else "."
    rel = posixpath.relpath(target_url, start=start)
    return rel if rel != "." else posixpath.basename(target_url)


def _render_agent_markdown(
    pages: list[ReportPage], manifest: dict[str, object]
) -> str:
    title = next((page.title for page in pages if page.relative_path == "index.md"), "Trackio Report")
    lines = [
        f"# {title}",
        "",
        "This is the agent-facing representation of the Trackio Report. The",
        "report itself is a static Hugging Face Space, so the browser page stays",
        "HTML. Agents should fetch this file, `llms.txt`, or `report.json` to",
        "avoid parsing layout markup.",
        "",
        "The HTML pages also include hidden metadata in element `data-*`",
        "attributes and embedded `#report-manifest` JSON.",
        "",
    ]
    if manifest.get("space_url"):
        lines.extend(["## Report URL", "", str(manifest["space_url"]), ""])
    if manifest.get("bucket_id"):
        lines.extend(["## Artifact Bucket", "", str(manifest["bucket_id"]), ""])

    lines.extend(["## Pages", ""])
    for page in manifest.get("pages", []):
        if not isinstance(page, dict):
            continue
        lines.append(
            f"- `{page.get('path')}`: {page.get('title')} "
            f"({page.get('url')})"
        )
    lines.append("")

    dashboards = manifest.get("dashboards", [])
    lines.extend(["## Trackio Dashboards", ""])
    if dashboards:
        for dashboard in dashboards:
            if not isinstance(dashboard, dict):
                continue
            lines.append(f"### {dashboard.get('project') or dashboard.get('space_url')}")
            lines.append("")
            lines.append(f"- Page: `{dashboard.get('page')}`")
            lines.append(f"- Dashboard URL: {dashboard.get('url')}")
            if dashboard.get("metrics"):
                lines.append(f"- Metrics: `{', '.join(dashboard['metrics'])}`")
            lines.append("- CLI:")
            for command in dashboard.get("cli_commands", []):
                lines.append(f"  - `{command}`")
            lines.append("")
    else:
        lines.extend(["No Trackio dashboard embeds were found.", ""])

    artifacts = manifest.get("artifacts", [])
    lines.extend(["## Artifacts And Raw Data", ""])
    if artifacts:
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            lines.append(f"### {artifact.get('caption') or artifact.get('path')}")
            lines.append("")
            lines.append(f"- Page: `{artifact.get('page')}`")
            lines.append(f"- Kind: `{artifact.get('kind')}`")
            lines.append(f"- Artifact URL: {artifact.get('url')}")
            if artifact.get("raw_data_url"):
                lines.append(f"- Raw data URL: {artifact.get('raw_data_url')}")
                lines.append(f"- Raw data path: `{artifact.get('raw_data_path')}`")
            lines.append("")
    else:
        lines.extend(["No artifacts were found.", ""])

    lines.extend(
        [
            "## Update Workflow",
            "",
            "Use the Trackio CLI from the report checkout:",
            "",
            "```sh",
            "trackio report publish --page reports/experiments/run.md --title \"Run summary\" --body notes.md --artifact outputs/",
            "trackio report build",
            "trackio report deploy",
            "```",
            "",
            "The browser HTML embeds `report.json` in `#report-manifest`, but agents",
            "should prefer this markdown document or `report.json` to avoid spending",
            "tokens on layout markup.",
            "",
        ]
    )
    return "\n".join(lines)


def _extract_artifacts(
    pages: list[ReportPage], config: ReportConfig
) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    pattern = re.compile(r"\{\{\s*(artifact|file)\s+([^}]+)\}\}")
    for page in pages:
        for match in pattern.finditer(page.body):
            kind = match.group(1)
            attrs = _parse_attrs(match.group(2))
            path = attrs.get("path")
            if not path:
                continue
            raw_data_path = attrs.get("data") or attrs.get("raw_data")
            entry = {
                "path": path,
                "url": attrs.get("url") or _bucket_url(config.bucket_id, path),
                "page": page.relative_path,
                "kind": "image" if kind == "artifact" and _is_image_path(path) else kind,
                "caption": attrs.get("caption") or Path(path).name,
            }
            if raw_data_path:
                entry["raw_data_path"] = raw_data_path
                entry["raw_data_url"] = attrs.get("data_url") or _bucket_url(
                    config.bucket_id, raw_data_path
                )
            artifacts.append(entry)
    return artifacts


def _extract_dashboards(pages: list[ReportPage]) -> list[dict[str, object]]:
    dashboards: list[dict[str, object]] = []
    seen: set[str] = set()
    pattern = re.compile(r"\{\{\s*trackio\s+([^}]+)\}\}")
    for page in pages:
        for match in pattern.finditer(page.body):
            attrs = _parse_attrs(match.group(1))
            url = attrs.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            dashboard = _dashboard_metadata(url)
            dashboard["page"] = page.relative_path
            dashboards.append(dashboard)
    return dashboards


def _dashboard_metadata(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    space_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    project = _first_query_value(params, "project")
    metrics_value = _first_query_value(params, "metrics")
    metrics = [m.strip() for m in (metrics_value or "").split(",") if m.strip()]
    commands = []
    if project:
        commands.append(
            f'trackio list runs --project "{project}" --space "{space_url}" --json'
        )
        if metrics:
            commands.append(
                f'trackio list metrics --project "{project}" --run RUN_NAME '
                f'--space "{space_url}" --json'
            )
            commands.append(
                f'trackio get metric --project "{project}" --run RUN_NAME '
                f'--metric "{metrics[0]}" --space "{space_url}" --json'
            )
        else:
            commands.append(
                f'trackio list reports --project "{project}" --space "{space_url}" --json'
            )
    else:
        commands.append(f'trackio list projects --space "{space_url}" --json')
    return {
        "url": url,
        "space_url": space_url,
        "project": project,
        "metrics": metrics,
        "cli_commands": commands,
    }


def _first_query_value(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    return values[0]


def _page_anchor(path: str) -> str:
    stem = path.removesuffix(".md")
    slug = re.sub(r"[^a-zA-Z0-9/_-]+", "-", stem).strip("-").lower()
    return "page-" + slug.replace("/", "-")


def _parse_attrs(raw: str) -> dict[str, str]:
    attrs = {}
    for key, value in re.findall(r'([a-zA-Z_][\w-]*)="([^"]*)"', raw):
        attrs[key] = value
    return attrs


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    metadata: dict[str, object] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata, body


def _inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def _paragraph_text(text: str) -> str:
    return re.sub(r"\s*\n\s*", " ", text.strip())


def _extract_heading(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _title_from_path(path: Path) -> str:
    stem = "index" if path.stem == "README" else path.stem
    return stem.replace("-", " ").replace("_", " ").title()


def _parent_page(path: str, all_paths: set[str]) -> str | None:
    if path == "index.md":
        return None
    parts = Path(path).parts
    if parts[-1] == "index.md":
        if len(parts) > 2:
            for i in range(len(parts) - 2, 0, -1):
                candidate = Path(*parts[:i], "index.md").as_posix()
                if candidate in all_paths:
                    return candidate
        return "index.md" if "index.md" in all_paths else None
    for i in range(len(parts) - 1, 0, -1):
        candidate = Path(*parts[:i], "index.md").as_posix()
        if candidate in all_paths:
            return candidate
    return "index.md" if "index.md" in all_paths else None


def _is_image_path(path: str) -> bool:
    mime, _ = mimetypes.guess_type(path)
    return bool(mime and mime.startswith("image/"))


def _bucket_url(bucket_id: str | None, path: str) -> str:
    if not bucket_id:
        return path
    return f"https://huggingface.co/buckets/{bucket_id}/resolve/{quote(path)}"


def _static_space_host(space_id: str) -> str:
    return f"https://{space_id.replace('/', '-')}.static.hf.space"


def _space_readme(space_id: str, bucket_id: str | None) -> str:
    bucket_line = "\nmodels: []\n" if bucket_id else ""
    return f"""---
emoji: 📊
sdk: static
pinned: false
tags:
 - trackio
 - trackio-reports
{bucket_line}---

# Trackio Report

Static Trackio Report deployed to `{space_id}`.
"""


def _retry_hf_write(op_name: str, fn, retries: int = 4, initial_delay: float = 1.5):
    delay = initial_delay
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except HfHubHTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status is None or status < 500 or attempt == retries:
                raise
            print(
                f"* {op_name} failed with HTTP {status} "
                f"(attempt {attempt}/{retries}). Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
            delay = min(delay * 2, 12)


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False
