from __future__ import annotations

import html
import io
import json
import mimetypes
import re
import shutil
import socketserver
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote

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
) -> dict[str, object]:
    root_path = Path(root)
    config = load_config(root_path)
    out_path = root_path / (output_dir or config.output_dir)
    pages = discover_pages(root_path, config)
    if not pages:
        raise ValueError(f"No Markdown pages found in {config.reports_dir}/")

    manifest = _build_manifest(pages, config)
    for page in pages:
        page.html = render_markdown(page.body, config)

    if out_path.exists():
        shutil.rmtree(out_path)
    out_path.mkdir(parents=True)
    (out_path / "report.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_path / "index.html").write_text(
        _render_site_html(pages, manifest),
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

    manifest = build_report(root_path, output_dir=output_dir)
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

## Commands

```sh
trackio report publish --page reports/experiments/run.md --title "Run summary" --body notes.md --artifact outputs/
trackio report validate
trackio report build
trackio report deploy
```

## Shortcodes

```md
{{ artifact path="reports/artifacts/run/chart.png" caption="Evaluation chart" }}
{{ file path="reports/artifacts/run/model.safetensors" caption="Model weights" }}
{{ trackio url="https://owner-space.hf.space/?project=my-project&sidebar=hidden" }}
```

Artifact paths are relative to the configured HF Bucket. Trackio dashboard embeds
must use public URLs when the report is deployed as a static Space.
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
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["path", "title", "url", "parent"],
                    "properties": {
                        "path": {"type": "string"},
                        "title": {"type": "string"},
                        "url": {"type": "string"},
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


def _build_manifest(pages: list[ReportPage], config: ReportConfig) -> dict[str, object]:
    page_items = []
    all_paths = {page.relative_path for page in pages}
    for page in pages:
        parent = _parent_page(page.relative_path, all_paths)
        page_items.append(
            {
                "path": page.relative_path,
                "title": page.title,
                "url": page.url,
                "parent": parent,
                "metadata": page.metadata,
            }
        )
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bucket_id": config.bucket_id,
        "pages": page_items,
    }


def _render_site_html(pages: list[ReportPage], manifest: dict[str, object]) -> str:
    nav = "\n".join(
        f'<a class="nav-link" href="#{html.escape(page.relative_path)}" data-page="{html.escape(page.relative_path)}">{html.escape(page.title)}</a>'
        for page in pages
    )
    page_sections = "\n".join(
        f'<article class="page" data-page="{html.escape(page.relative_path)}"><div class="page-kicker">{html.escape(page.relative_path)}</div>{page.html}</article>'
        for page in pages
    )
    payload = html.escape(json.dumps(manifest), quote=False)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trackio Report</title>
  <style>
    :root {{ color-scheme: light; --border: #d8dee8; --muted: #5f6b7a; --ink: #17202c; --bg: #f7f8fb; --panel: #ffffff; --accent: #2563eb; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); }}
    .app {{ display: grid; grid-template-columns: 280px minmax(0, 1fr); min-height: 100vh; }}
    aside {{ border-right: 1px solid var(--border); background: var(--panel); padding: 20px 16px; position: sticky; top: 0; height: 100vh; overflow: auto; }}
    .brand {{ font-size: 15px; font-weight: 700; margin: 0 0 16px; }}
    .nav-link {{ display: block; padding: 8px 10px; border-radius: 6px; color: var(--ink); text-decoration: none; font-size: 14px; margin: 2px 0; }}
    .nav-link:hover, .nav-link.active {{ background: #eaf1ff; color: #123f94; }}
    main {{ max-width: 980px; width: 100%; padding: 40px 48px 80px; }}
    .page {{ display: none; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 32px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }}
    .page.active {{ display: block; }}
    .page-kicker {{ color: var(--muted); font-size: 12px; margin-bottom: 12px; }}
    h1, h2, h3, h4 {{ margin: 24px 0 10px; line-height: 1.2; }}
    h1:first-child, h2:first-child {{ margin-top: 0; }}
    p, li {{ line-height: 1.65; }}
    code {{ background: #eef2f7; padding: 2px 5px; border-radius: 4px; }}
    img {{ max-width: 100%; border: 1px solid var(--border); border-radius: 6px; }}
    .artifact {{ margin: 18px 0; }}
    .artifact figcaption {{ color: var(--muted); font-size: 13px; margin-top: 6px; }}
    .file-link {{ display: inline-flex; align-items: center; padding: 9px 12px; border: 1px solid var(--border); border-radius: 6px; color: var(--accent); text-decoration: none; background: #fff; }}
    .trackio-embed {{ width: 100%; min-height: 520px; border: 1px solid var(--border); border-radius: 8px; margin: 18px 0; background: white; }}
    @media (max-width: 760px) {{ .app {{ grid-template-columns: 1fr; }} aside {{ height: auto; position: relative; }} main {{ padding: 20px; }} .page {{ padding: 20px; }} }}
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">Trackio Report</div>
      <nav>{nav}</nav>
    </aside>
    <main>{page_sections}</main>
  </div>
  <script type="application/json" id="report-manifest">{payload}</script>
  <script>
    const links = [...document.querySelectorAll(".nav-link")];
    const pages = [...document.querySelectorAll(".page")];
    function showPage(id) {{
      const target = id || (pages[0] && pages[0].dataset.page);
      pages.forEach(page => page.classList.toggle("active", page.dataset.page === target));
      links.forEach(link => link.classList.toggle("active", link.dataset.page === target));
      if (target && location.hash.slice(1) !== target) history.replaceState(null, "", "#" + target);
    }}
    window.addEventListener("hashchange", () => showPage(decodeURIComponent(location.hash.slice(1))));
    showPage(decodeURIComponent(location.hash.slice(1)));
  </script>
</body>
</html>
"""


def _render_shortcodes(markdown: str, config: ReportConfig) -> str:
    pattern = re.compile(r"\{\{\s*(artifact|file|trackio)\s+([^}]+)\}\}")

    def replace(match: re.Match[str]) -> str:
        kind = match.group(1)
        attrs = _parse_attrs(match.group(2))
        if kind == "trackio":
            url = attrs.get("url", "")
            return f'<iframe class="trackio-embed" src="{html.escape(url, quote=True)}" loading="lazy"></iframe>'
        path = attrs.get("path", "")
        caption = attrs.get("caption") or Path(path).name
        url = attrs.get("url") or _bucket_url(config.bucket_id, path)
        if kind == "artifact" and _is_image_path(path):
            return (
                f'<figure class="artifact"><img src="{html.escape(url, quote=True)}" '
                f'alt="{html.escape(caption, quote=True)}"><figcaption>{html.escape(caption)}</figcaption></figure>'
            )
        return f'<p><a class="file-link" href="{html.escape(url, quote=True)}">{html.escape(caption)}</a></p>'

    return pattern.sub(replace, markdown)


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
