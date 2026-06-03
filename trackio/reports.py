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
    (out_path / "_worker.js").write_text(_render_agent_worker(), encoding="utf-8")
    (out_path / "_headers").write_text(_render_headers(), encoding="utf-8")
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
    sdk: str = "static",
) -> str:
    root_path = Path(root)
    config = load_config(root_path)
    target_space = space_id or config.space_id
    target_bucket = bucket_id or config.bucket_id
    if not target_space:
        raise ValueError("A Space ID is required. Pass --space-id or configure one.")
    if sdk not in {"static", "docker"}:
        raise ValueError("Report deployment sdk must be 'static' or 'docker'.")

    report_url = (
        _static_space_host(target_space)
        if sdk == "static"
        else _dynamic_space_host(target_space)
    )
    manifest = build_report(root_path, output_dir=output_dir, space_url=report_url)
    out_path = root_path / (output_dir or config.output_dir)
    if sdk == "docker":
        _write_dynamic_space_files(out_path)

    if target_bucket:
        create_bucket_if_not_exists(target_bucket, private=False)

    hf_api = huggingface_hub.HfApi()
    _retry_hf_write(
        "Report Space creation",
        lambda: huggingface_hub.create_repo(
            target_space,
            private=False,
            space_sdk=sdk,
            repo_type="space",
            exist_ok=True,
        ),
    )
    readme = _space_readme(target_space, target_bucket, sdk=sdk)
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
        "sdk": sdk,
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
                    rendered.append(f"<p>{_inline_markdown(rest).replace(chr(10), '<br>')}</p>")
                continue
        if block.lstrip().startswith("<"):
            rendered.append(block)
        else:
            rendered.append(f"<p>{_inline_markdown(block).replace(chr(10), '<br>')}</p>")

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
  coding agents. When the static host supports edge workers, requests with
  `Accept: text/markdown` or a known coding-agent User-Agent are served
  `agent.md` instead of browser HTML.

## Commands

```sh
trackio report publish --page reports/experiments/run.md --title "Run summary" --body notes.md --artifact outputs/
trackio report validate
trackio report build
trackio report deploy
```

Use `trackio report deploy --sdk docker` when the deployed URL must return
`agent.md` directly for `Accept: text/markdown` or coding-agent User-Agent
requests. Static deployment remains the default and exposes `/agent.md`
explicitly.

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
  <script>{_agent_redirect_script()}</script>
</head>
<body{current_attr}>
  <main class="article-shell">
    <article class="article-paper">
      <header class="article-header">
        <div class="eyebrow">{html.escape(eyebrow)}</div>
        <h1 class="article-title">{escaped_title}</h1>
        <div class="article-meta">{meta_html}</div>
      </header>
      {body_html}
    </article>
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
    .article-shell { max-width: 1080px; margin: 0 auto; padding: 34px 28px 88px; }
    .article-paper { background: var(--paper); padding: 16px min(6vw, 72px); }
    .article-header { padding-bottom: 18px; margin-bottom: 28px; }
    .eyebrow { color: var(--accent); font: 700 12px/1.3 ui-sans-serif, system-ui, sans-serif; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 16px; }
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
    table { width: 100%; border-collapse: collapse; margin: 24px 0; font: 14px/1.45 ui-sans-serif, system-ui, sans-serif; }
    th, td { border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left; vertical-align: top; }
    th { background: var(--soft); }
    @media (max-width: 760px) { .article-shell { padding: 18px 10px 56px; } .article-paper { padding: 18px 10px; } .article-title { font-size: 30px; } p, li { font-size: 16px; } .trackio-embed { min-height: 460px; } }
    """


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
                    "dashboard. When an agent is supplied this report, they see "
                    "the dashboard URL, which they can query programmatically to "
                    "get the full data."
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
                "The same URL and CLI hints are available in <code>agent.md</code>, "
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
                    "but agents get raw data so that they can easily parse raw "
                    f'results and update them. Raw data: <a href="{html.escape(raw_data_url, quote=True)}">'
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
        "This is the agent-facing representation of the Trackio Report. It is",
        "served instead of the browser HTML when the host supports markdown",
        "content negotiation for `Accept: text/markdown` or known coding-agent",
        "User-Agent headers.",
        "",
        "For browser rendering, request the same URL with `Accept: text/html`.",
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


def _render_agent_worker() -> str:
    return """const LLM_UA_PATTERNS = [
  /\\bgptbot\\b/i,
  /\\bchatgpt-user\\b/i,
  /\\bclaudebot\\b/i,
  /\\bclaude-web\\b/i,
  /\\bclaude-user\\b/i,
  /\\banthropic\\b/i,
  /\\bperplexitybot\\b/i,
  /\\bmeta-external(?:fetcher|agent)\\b/i,
  /\\bfacebookbot\\b/i,
  /\\bamazonbot\\b/i,
  /\\bapplebot\\b/i,
  /\\bbytespider\\b/i,
  /\\bccbot\\b/i,
  /\\bcohere\\b/i,
  /\\bgoogle-extended\\b/i,
  /\\bcodex\\b/i,
  /\\bcursor\\b/i
];

function isAgentRequest(request) {
  const accept = request.headers.get("accept") || "";
  if (accept.includes("text/markdown")) return true;
  const ua = request.headers.get("user-agent") || "";
  return LLM_UA_PATTERNS.some((pattern) => pattern.test(ua));
}

function isHtmlRoute(pathname) {
  return pathname === "/" || pathname.endsWith(".html");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (isAgentRequest(request) && isHtmlRoute(url.pathname)) {
      const agentUrl = new URL("/agent.md", request.url);
      const response = await env.ASSETS.fetch(agentUrl.toString());
      return new Response(response.body, {
        status: response.status,
        headers: {
          "content-type": "text/markdown; charset=utf-8",
          "cache-control": "public, max-age=60"
        }
      });
    }
    return env.ASSETS.fetch(request);
  }
};
"""


def _render_headers() -> str:
    return """/agent.md
  Content-Type: text/markdown; charset=utf-8

/llms.txt
  Content-Type: text/plain; charset=utf-8
"""


def _write_dynamic_space_files(out_path: Path) -> None:
    (out_path / "Dockerfile").write_text(_render_dockerfile(), encoding="utf-8")
    (out_path / "requirements.txt").write_text(
        "fastapi\nuvicorn[standard]\n",
        encoding="utf-8",
    )
    (out_path / "server.py").write_text(_render_dynamic_server(), encoding="utf-8")


def _render_dockerfile() -> str:
    return """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
"""


def _render_dynamic_server() -> str:
    return '''from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse


ROOT = Path(__file__).parent
LLM_UA_PATTERNS = [
    re.compile(r"\\bgptbot\\b", re.IGNORECASE),
    re.compile(r"\\bchatgpt-user\\b", re.IGNORECASE),
    re.compile(r"\\bclaudebot\\b", re.IGNORECASE),
    re.compile(r"\\bclaude-web\\b", re.IGNORECASE),
    re.compile(r"\\bclaude-user\\b", re.IGNORECASE),
    re.compile(r"\\banthropic\\b", re.IGNORECASE),
    re.compile(r"\\bperplexitybot\\b", re.IGNORECASE),
    re.compile(r"\\bmeta-external(?:fetcher|agent)\\b", re.IGNORECASE),
    re.compile(r"\\bfacebookbot\\b", re.IGNORECASE),
    re.compile(r"\\bamazonbot\\b", re.IGNORECASE),
    re.compile(r"\\bapplebot\\b", re.IGNORECASE),
    re.compile(r"\\bbytespider\\b", re.IGNORECASE),
    re.compile(r"\\bccbot\\b", re.IGNORECASE),
    re.compile(r"\\bcohere\\b", re.IGNORECASE),
    re.compile(r"\\bgoogle-extended\\b", re.IGNORECASE),
    re.compile(r"\\bcodex\\b", re.IGNORECASE),
    re.compile(r"\\bcursor\\b", re.IGNORECASE),
]


def is_agent_request(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    if "text/markdown" in accept:
        return True
    user_agent = request.headers.get("user-agent", "")
    return any(pattern.search(user_agent) for pattern in LLM_UA_PATTERNS)


def is_html_route(path: str) -> bool:
    return path in {"", "index.html"} or path.endswith(".html")


app = FastAPI()


@app.get("/")
async def root(request: Request):
    return await serve_path(request, "index.html")


@app.get("/{path:path}")
async def serve_path(request: Request, path: str):
    if is_agent_request(request) and is_html_route(path):
        return FileResponse(ROOT / "agent.md", media_type="text/markdown")

    target = (ROOT / path).resolve()
    if not str(target).startswith(str(ROOT.resolve())):
        raise HTTPException(status_code=404)
    if target.is_dir():
        target = target / "index.html"
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(target)
'''


def _agent_redirect_script() -> str:
    return """(() => {
  const ua = navigator.userAgent || "";
  const patterns = [
    /\\bgptbot\\b/i,
    /\\bchatgpt-user\\b/i,
    /\\bclaudebot\\b/i,
    /\\bclaude-web\\b/i,
    /\\bclaude-user\\b/i,
    /\\banthropic\\b/i,
    /\\bperplexitybot\\b/i,
    /\\bcodex\\b/i,
    /\\bcursor\\b/i
  ];
  if (!patterns.some((pattern) => pattern.test(ua))) return;
  const explicitHtml = new URLSearchParams(location.search).get("format") === "html";
  if (explicitHtml) return;
  const link = document.querySelector('link[rel="alternate"][type="text/markdown"]');
  if (link && link.href) location.replace(link.href);
})();"""


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


def _dynamic_space_host(space_id: str) -> str:
    return f"https://{space_id.replace('/', '-')}.hf.space"


def _space_readme(space_id: str, bucket_id: str | None, *, sdk: str = "static") -> str:
    bucket_line = "\nmodels: []\n" if bucket_id else ""
    return f"""---
emoji: 📊
sdk: {sdk}
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
