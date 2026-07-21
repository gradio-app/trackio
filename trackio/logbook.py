from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR_NAME = ".trackio"
LOGBOOK_SUBDIR = "logbook"
METADATA_FILE = "metadata.json"
SCHEMA_VERSION = 2
ROOT_SLUG = "index"
VIEWER_DIR = Path(__file__).parent / "frontend_templates" / "logbook"
VIEWER_FILES = [
    "index.html",
    "logbook.css",
    "logbook.js",
    "trackio-logo.png",
    "trackio-logo-light.png",
    "trackio-wordmark-dark.png",
    "bucket-icon.svg",
]
PRIVATE_STATE_IGNORE_PATTERNS = (
    "/trace_sources.json",
    "/traces/",
    "/workspace_baselines/",
    "/workspace_bucket_state.json",
    "/trace_dataset/",
    "/imported_workspace.json",
    "/logbook/traces/",
    "/logbook/workspace.json",
)

TOC_HEADING = "## Pages"
TOC_HEADER = "| Page |"
TOC_SEP = "| --- |"
TOC_PLACEHOLDER_TOKENS = ("logbook note", "logbook cell markdown", "logbook page")
STATUS_COL_RE = re.compile(r"\b(status|state)\b", re.I)
LINK_COL_RE = re.compile(r"\b(page|experiment|name|title)\b", re.I)
CELL_TYPES = {"markdown", "code", "figure", "artifact", "dashboard"}
ARTIFACT_URI_PREFIX = "trackio-artifact://"
PATH_ARTIFACT_URI_PREFIX = "trackio-local-path://"
LOCAL_DASHBOARD_PREFIX = "trackio-local-dashboard://"
SPACE_URL_RE = re.compile(r"https://huggingface\.co/spaces/[^\s<>)\"'`]+")
BUCKET_URL_RE = re.compile(r"https://huggingface\.co/buckets/[^\s<>)\"'`]+")
DEFAULT_HEAD = 3
DEFAULT_TAIL = 3
DEFAULT_RAW_LIMIT = 500
FENCE_RE = re.compile(r"(`{3,4}|~{3,4})([^\n]*)\n([\s\S]*?)\n\1")
RUN_OUTPUT_LIMIT = 20_000
RUN_OUTPUT_HEAD = 2_000
RUN_OUTPUT_TAIL = RUN_OUTPUT_LIMIT - RUN_OUTPUT_HEAD
TRY_NUM_PORTS = int(os.getenv("GRADIO_NUM_PORTS", "100"))
CELL_RE = re.compile(
    r"(^|\n)---\n<!-- trackio-cell\n([\s\S]*?)\n-->\n([\s\S]*?)(?=\n---\n<!-- trackio-cell\n|\s*$)"
)


class LogbookError(Exception):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _short_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return dt.strftime("%Y-%m-%d %H:%M")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "page"


# ---- locating the project ----


def find_project_dir(start: str | Path | None = None) -> Path | None:
    start = Path(start or Path.cwd()).resolve()
    for d in (start, *start.parents):
        candidate = d / PROJECT_DIR_NAME
        if (candidate / LOGBOOK_SUBDIR / "pages" / "index.md").is_file():
            return candidate
    return None


def require_project_dir(start: str | Path | None = None) -> Path:
    proj = find_project_dir(start)
    if proj is None:
        raise LogbookError(
            "No logbook in this directory (or any parent). "
            'Start one with: trackio logbook open --title "..."'
        )
    return proj


def logbook_root(proj: Path) -> Path:
    return proj / LOGBOOK_SUBDIR


def _project_from_space(space_id: str) -> Path:
    import tempfile  # noqa: PLC0415

    import huggingface_hub  # noqa: PLC0415
    from huggingface_hub.utils import (  # noqa: PLC0415
        HfHubHTTPError,
        RepositoryNotFoundError,
    )

    try:
        huggingface_hub.utils.disable_progress_bars()
        try:
            snap = Path(huggingface_hub.snapshot_download(space_id, repo_type="space"))
        finally:
            huggingface_hub.utils.enable_progress_bars()
    except (RepositoryNotFoundError, HfHubHTTPError) as e:
        raise LogbookError(f"Could not download Space '{space_id}': {e}") from e
    if not (snap / "pages" / "index.md").is_file():
        raise LogbookError(f"Space '{space_id}' does not contain a Trackio logbook.")
    proj = Path(tempfile.mkdtemp(prefix="trackio-logbook-")) / PROJECT_DIR_NAME
    proj.mkdir(parents=True)
    link = proj / LOGBOOK_SUBDIR
    try:
        link.symlink_to(snap)
    except OSError:
        shutil.copytree(snap, link)
    return proj


def _project_from_url(url: str) -> Path:
    import tempfile  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    base = url.rstrip("/")

    def fetch(path: str) -> str:
        with urllib.request.urlopen(f"{base}/{path}", timeout=15) as response:
            return response.read().decode("utf-8")

    try:
        manifest = json.loads(fetch("logbook.json"))
    except Exception as e:
        raise LogbookError(f"Could not read a logbook at {url}: {e}") from e
    proj = Path(tempfile.mkdtemp(prefix="trackio-logbook-")) / PROJECT_DIR_NAME
    root = logbook_root(proj)
    root_resolved = root.resolve()

    def fetch_to_project(file: str) -> bool:
        dest = (root / file).resolve()
        if not dest.is_relative_to(root_resolved):
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_text(fetch(file), encoding="utf-8")
        except Exception:
            return False
        return True

    files = {
        node.get("file")
        for node in _walk(manifest.get("root") or {})
        if node.get("file")
    }
    workspace_file = (manifest.get("workspace") or {}).get("file")
    if workspace_file:
        files.add(workspace_file)
    trace_sessions = manifest.get("traces") or []
    for session in trace_sessions:
        index_file = session.get("index_file")
        if not index_file or not fetch_to_project(index_file):
            continue
        trace_index = _read_json_file(root / index_file)
        files.update(
            chunk.get("file")
            for chunk in trace_index.get("chunks") or []
            if chunk.get("file")
        )
    for file in sorted(files):
        if not (root / file).is_file():
            fetch_to_project(file)
    root.mkdir(parents=True, exist_ok=True)
    (root / "logbook.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if not (root / "pages" / "index.md").is_file():
        raise LogbookError(f"No logbook pages found at {url}")
    return proj


def resolve_read_source(source: str | None = None) -> Path:
    if source is None:
        return require_project_dir()
    local = Path(source).expanduser()
    if local.exists():
        return require_project_dir(local)
    if re.match(r"^https?://", source):
        space = re.match(r"^https?://huggingface\.co/spaces/([^/?#]+/[^/?#]+)", source)
        if space:
            return _project_from_space(space.group(1))
        return _project_from_url(source)
    if re.match(r"^[\w.-]+/[\w.-]+$", source):
        return _project_from_space(source)
    raise LogbookError(
        f"'{source}' is not a local logbook path, HF Space id, or logbook URL."
    )


def _pages_dir(proj: Path) -> Path:
    return logbook_root(proj) / "pages"


def _metadata_path(proj: Path) -> Path:
    return proj / METADATA_FILE


def _manifest_path(proj: Path) -> Path:
    return logbook_root(proj) / "logbook.json"


def read_metadata(proj: Path) -> dict:
    path = _metadata_path(proj)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_metadata(proj: Path, metadata: dict) -> None:
    _metadata_path(proj).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _workspace_bucket(metadata: dict) -> str | None:
    if metadata.get("workspace_publication") not in {"public", "private"}:
        return None
    return metadata.get("workspace_bucket")


def _remember_page(proj: Path, slug: str) -> None:
    if slug == ROOT_SLUG or _page_file_for_slug(proj, slug) is None:
        return
    metadata = read_metadata(proj)
    metadata["last_page"] = slug
    write_metadata(proj, metadata)


# ---- manifest generated by scanning pages/ ----


def _title_of(md_path: Path, fallback: str) -> str:
    try:
        for line in md_path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"#\s+(.+)", line.strip())
            if m:
                return m.group(1).strip()
    except OSError:
        pass
    return fallback


def _link_order(md_path: Path) -> list[str]:
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return []
    seen = []
    for slug in re.findall(r"\(#/([A-Za-z0-9._-]+)\)", text):
        if slug not in seen:
            seen.append(slug)
    return seen


def _scan_children(dir_path: Path, rel_prefix: str, parent_md: Path) -> list[dict]:
    subs = [d for d in dir_path.iterdir() if d.is_dir() and (d / "page.md").is_file()]
    order = _link_order(parent_md)

    def sort_key(d):
        idx = order.index(d.name) if d.name in order else len(order)
        return (idx, (d / "page.md").stat().st_ctime)

    subs.sort(key=sort_key)
    children = []
    for d in subs:
        md = d / "page.md"
        children.append(
            {
                "slug": d.name,
                "title": _title_of(md, d.name),
                "file": f"{rel_prefix}/{d.name}/page.md",
                "children": [],
            }
        )
    return children


def build_manifest(proj: Path) -> dict:
    pages = _pages_dir(proj)
    metadata = read_metadata(proj)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "title": _title_of(pages / "index.md", "Logbook"),
        "emoji": metadata.get("emoji", "🎯"),
        "space_id": metadata.get("space_id"),
        "paper": metadata.get("paper"),
        "tags": metadata.get("tags") or [],
        "updated_at": _now_iso(),
        "root": {
            "slug": ROOT_SLUG,
            "title": _title_of(pages / "index.md", "Logbook"),
            "file": "pages/index.md",
            "children": _scan_children(pages, "pages", pages / "index.md"),
        },
    }
    try:
        from trackio import logbook_trace  # noqa: PLC0415

        generated = logbook_trace.read_generated(proj)
        sessions = generated.get("traces", {}).get("sessions") or []
        workspace = generated.get("workspace") or {}
        manifest["traces"] = sessions
        manifest["workspace"] = {
            "file": "workspace.json",
            "file_count": workspace.get("file_count", 0),
            "total_size": workspace.get("total_size", 0),
            "bucket_id": workspace.get("bucket_id"),
        }
    except Exception:
        manifest["traces"] = []
        manifest["workspace"] = {
            "file": "workspace.json",
            "file_count": 0,
            "total_size": 0,
            "bucket_id": None,
        }
    return manifest


def _walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from _walk(child)


AGENT_VIEW_NOTE = (
    "> Agent view: markdown bodies are inline; code cells show the command, a "
    "code head, and an output tail; figures inline small raw data. Fetch full "
    "payloads with `trackio logbook read cell <id> [--full|--raw|--html]`."
)


def _index_prose(text: str) -> str:
    return CELL_RE.sub("", text).strip()


def read_logbook(
    proj: Path,
    manifest: dict | None = None,
    head: int = DEFAULT_HEAD,
    tail: int = DEFAULT_TAIL,
    raw_limit: int = DEFAULT_RAW_LIMIT,
) -> str:
    manifest = manifest or build_manifest(proj)
    root = logbook_root(proj)
    index_node = manifest["root"]
    index_text = (root / index_node["file"]).read_text(encoding="utf-8")
    out = [_index_prose(index_text), ""]
    index_cells = _parse_cells_from_text(
        index_text, index_node["slug"], index_node["title"]
    )
    for cell in index_cells:
        out += _cell_agent_lines(cell, head, tail, raw_limit)
    out += [AGENT_VIEW_NOTE, ""]
    for node in _walk(manifest["root"]):
        if node["slug"] == index_node["slug"]:
            continue
        text = (root / node["file"]).read_text(encoding="utf-8")
        out.append(_page_outline_markdown(node, text, head, tail, raw_limit).strip())
        out.append("")
    return "\n".join(out)


READ_VIEWS = ("code", "trace", "workspace")


def split_read_view(source: str | None) -> tuple[str | None, str]:
    if not source:
        return source, "code"
    base, _, fragment = source.partition("#")
    view = "code"
    match = re.match(r"/?view/(trace|traces|workspace|tree)", fragment)
    if match:
        view = "trace" if match.group(1).startswith("trace") else "workspace"
    return (base or None), view


def _read_json_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _format_ms(ms: int | None) -> str:
    if not ms:
        return "0s"
    seconds = int(ms // 1000)
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds}s"


def _trace_event_line(event: dict) -> str:
    kind = event.get("kind") or "event"
    if kind == "reasoning":
        label = "thought"
    elif kind == "tool_call":
        label = f"tool {event.get('tool_name') or event.get('title') or ''}".strip()
    elif kind == "tool_result":
        label = "output"
    elif kind == "message":
        label = event.get("role") or "message"
    else:
        label = event.get("title") or kind
    text = (
        event.get("text")
        or event.get("output")
        or event.get("command")
        or event.get("input")
        or ""
    )
    text = " ".join(str(text).split())
    if len(text) > 240:
        text = text[:239] + "…"
    seq = event.get("sequence")
    prefix = f"[{seq}] " if seq else ""
    return f"- {prefix}{label}: {text}" if text else f"- {prefix}{label}"


def read_traces(proj: Path, manifest: dict | None = None) -> str:
    manifest = manifest or build_manifest(proj)
    sessions = manifest.get("traces") or []
    if not sessions:
        return "No agent session traces attached.\n"
    root = logbook_root(proj)
    out = ["# Agent session traces", ""]
    for session in sessions:
        index_file = session.get("index_file")
        index = _read_json_file(root / index_file) if index_file else {}
        title = index.get("title") or session.get("title") or session.get("id", "")
        out.append(f"## {title} · `{session.get('id', '')}`")
        bits = []
        if index.get("model"):
            bits.append(f"model {index['model']}")
        if index.get("started_at"):
            bits.append(f"started {_short_time(index['started_at'])}")
        bits.append(f"duration {_format_ms(index.get('duration_ms'))}")
        bits.append(f"{index.get('event_count', 0)} events")
        out += [" · ".join(bits), ""]
        events = []
        for chunk in index.get("chunks", []):
            chunk_file = chunk.get("file")
            if not chunk_file:
                continue
            events += _read_json_file(root / chunk_file).get("events", [])
        out += [_trace_event_line(event) for event in events]
        out.append("")
    return "\n".join(out).strip() + "\n"


def read_workspace_tree(proj: Path, manifest: dict | None = None) -> str:
    manifest = manifest or build_manifest(proj)
    root = logbook_root(proj)
    workspace_file = (manifest.get("workspace") or {}).get("file") or "workspace.json"
    files = _read_json_file(root / workspace_file).get("files") or []
    if not files:
        return "No workspace files captured.\n"
    out = [f"# Workspace files ({len(files)})", ""]
    for item in sorted(files, key=lambda entry: entry.get("path", "")):
        size = _format_size(item.get("size")).replace(" · ", "", 1).strip()
        line = item.get("path", "")
        out.append(f"{line} · {size}" if size else line)
    return "\n".join(out).strip() + "\n"


def _cell_agent_lines(cell: dict, head: int, tail: int, raw_limit: int) -> list[str]:
    summary = _cell_public_summary(cell, head=head, tail=tail, raw_limit=raw_limit)
    heading = f"### {cell['title']} · {cell['type']} · `{cell['id']}`"
    created = cell.get("created_at")
    if created:
        heading += f" · {_short_time(created)}"
    lines = [heading, ""]
    preview = summary.get("preview") or ""
    if preview:
        lines += [preview, ""]
    return lines


def _page_outline_markdown(
    node: dict,
    text: str,
    head: int = DEFAULT_HEAD,
    tail: int = DEFAULT_TAIL,
    raw_limit: int = DEFAULT_RAW_LIMIT,
) -> str:
    cells = _parse_cells_from_text(text, node["slug"], node["title"])
    lines = [f"## {node['title']} · `{node['slug']}`", ""]
    if not cells:
        lines.append("No cells.")
        return "\n".join(lines)
    for cell in cells:
        lines += _cell_agent_lines(cell, head, tail, raw_limit)
    return "\n".join(lines)


def read_logbook_data(
    proj: Path,
    head: int = DEFAULT_HEAD,
    tail: int = DEFAULT_TAIL,
    raw_limit: int = DEFAULT_RAW_LIMIT,
) -> dict:
    manifest = build_manifest(proj)
    root = logbook_root(proj)
    pages = []
    for node in _walk(manifest["root"]):
        text = (root / node["file"]).read_text(encoding="utf-8")
        cells = _parse_cells_from_text(text, node["slug"], node["title"])
        entry = {
            "slug": node["slug"],
            "title": node["title"],
            "file": node["file"],
            "cells": [
                _cell_public_summary(cell, head=head, tail=tail, raw_limit=raw_limit)
                for cell in cells
            ],
        }
        if node["slug"] == ROOT_SLUG:
            entry["markdown"] = _index_prose(text)
        pages.append(entry)
    return {
        "title": manifest["title"],
        "space_id": manifest.get("space_id"),
        "updated_at": manifest.get("updated_at"),
        "pages": pages,
    }


def _ensure_viewer_files(proj: Path) -> None:
    root = logbook_root(proj)
    for fname in VIEWER_FILES:
        dest = root / fname
        src = VIEWER_DIR / fname
        if not src.is_file():
            continue
        if not dest.exists() or dest.read_bytes() != src.read_bytes():
            shutil.copy2(src, dest)


def _ensure_project_gitignore(proj: Path) -> None:
    path = proj / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = existing.splitlines()
    known = {line.strip() for line in lines}
    missing = [item for item in PRIVATE_STATE_IGNORE_PATTERNS if item not in known]
    if not missing:
        return
    if lines and lines[-1].strip():
        lines.append("")
    header = "# Agent traces and Workspace state may contain sensitive data."
    if header not in known:
        lines.append(header)
    lines.extend(missing)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 3.3))


def _site_revision(proj: Path, manifest: dict) -> str:
    """Return a stable revision for content visible in the local viewer."""
    digest = hashlib.sha256()
    stable_manifest = {
        key: value
        for key, value in manifest.items()
        if key not in {"revision", "updated_at"}
    }
    digest.update(
        json.dumps(stable_manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    root = logbook_root(proj)
    paths = list((root / "pages").rglob("*.md"))
    paths += list((root / "traces").rglob("*.json"))
    workspace = root / "workspace.json"
    if workspace.is_file():
        paths.append(workspace)
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        stat = path.stat()
        digest.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode("ascii"))
    return digest.hexdigest()[:20]


def write_site_files(proj: Path) -> dict:
    _ensure_project_gitignore(proj)
    _ensure_viewer_files(proj)
    from trackio import logbook_trace  # noqa: PLC0415

    try:
        logbook_trace.refresh_all(
            proj, bucket_id=_workspace_bucket(read_metadata(proj))
        )
    except logbook_trace.TraceCaptureError as e:
        print(f"Warning: could not refresh attached trace: {e}", file=sys.stderr)
    manifest = build_manifest(proj)
    manifest["agent_view_tokens"] = _estimate_tokens(read_logbook(proj, manifest))
    manifest["trace_view_tokens"] = _estimate_tokens(read_traces(proj, manifest))
    manifest["workspace_view_tokens"] = _estimate_tokens(
        read_workspace_tree(proj, manifest)
    )
    root = logbook_root(proj)
    previous = _read_json_file(root / "logbook.json")
    manifest["revision"] = _site_revision(proj, manifest)
    manifest["updated_at"] = (
        previous.get("updated_at")
        if previous.get("revision") == manifest["revision"]
        else _now_iso()
    )
    index_html = root / "index.html"
    if index_html.is_file():
        text = index_html.read_text(encoding="utf-8")
        updated = re.sub(
            r"<title>.*?</title>",
            f"<title>{html.escape(manifest['title'])}</title>",
            text,
            count=1,
            flags=re.S,
        )
        if updated != text:
            index_html.write_text(updated, encoding="utf-8")
    (root / "logbook.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    stale_agent_view = root / "logbook.md"
    if stale_agent_view.exists():
        stale_agent_view.unlink()
    return manifest


def attach_trace(proj: Path, source_path: str | Path, title: str | None = None) -> dict:
    from trackio import logbook_trace  # noqa: PLC0415

    try:
        result = logbook_trace.attach_trace(proj, source_path, title=title)
    except logbook_trace.TraceCaptureError as e:
        raise LogbookError(str(e)) from e
    write_site_files(proj)
    return result


def remove_trace(proj: Path, session_id: str) -> None:
    from trackio import logbook_trace  # noqa: PLC0415

    try:
        logbook_trace.remove_trace(proj, session_id)
        logbook_trace.refresh_all(
            proj, bucket_id=_workspace_bucket(read_metadata(proj))
        )
    except logbook_trace.TraceCaptureError as e:
        raise LogbookError(str(e)) from e
    write_site_files(proj)


def publication_inventory(proj: Path) -> dict:
    from trackio import logbook_trace  # noqa: PLC0415

    generated = logbook_trace.refresh_all(
        proj, bucket_id=_workspace_bucket(read_metadata(proj))
    )
    return {
        "trace_count": len(generated.get("traces", {}).get("sessions") or []),
        "workspace_file_count": generated.get("workspace", {}).get("file_count", 0),
    }


# ---- creation ----


def create_logbook(
    title: str | None = None, space_id: str | None = None, emoji: str = "🎯"
) -> Path:
    proj = find_project_dir() or (Path.cwd() / PROJECT_DIR_NAME)
    title = title or proj.parent.name or "Experiment"
    root = logbook_root(proj)
    if (root / "pages" / "index.md").exists():
        raise LogbookError(
            f"A logbook already exists at {root}. Attach with `trackio logbook open`."
        )
    (root / "pages").mkdir(parents=True, exist_ok=True)
    (root / "pages" / "index.md").write_text(
        f"# {title}\n\n"
        f"{TOC_HEADING}\n\n"
        f"{TOC_HEADER}\n{TOC_SEP}\n"
        '| Add a page with `trackio logbook page "..."` |\n',
        encoding="utf-8",
    )
    write_metadata(
        proj, {"space_id": space_id, "emoji": emoji, "created_at": _now_iso()}
    )
    write_site_files(proj)
    return proj


def clone_logbook(space_id: str) -> Path | None:
    import huggingface_hub  # noqa: PLC0415
    from huggingface_hub.utils import (  # noqa: PLC0415
        HfHubHTTPError,
        RepositoryNotFoundError,
    )

    try:
        snap = Path(huggingface_hub.snapshot_download(space_id, repo_type="space"))
    except (RepositoryNotFoundError, HfHubHTTPError):
        return None
    if not (snap / "pages" / "index.md").is_file():
        return None
    proj = find_project_dir() or (Path.cwd() / PROJECT_DIR_NAME)
    root = logbook_root(proj)
    if _manifest_path(proj).exists() or (root / "pages" / "index.md").exists():
        raise LogbookError(
            f"A logbook already exists at {root}; remove it before cloning."
        )
    shutil.copytree(snap / "pages", root / "pages")
    for fname in VIEWER_FILES:
        if (snap / fname).is_file():
            shutil.copy2(snap / fname, root / fname)
    for dirname in ("media", "traces"):
        if (snap / dirname).is_dir():
            shutil.copytree(snap / dirname, root / dirname)
    if (snap / "workspace.json").is_file():
        shutil.copy2(snap / "workspace.json", root / "workspace.json")
    write_metadata(proj, {"space_id": space_id, "created_at": _now_iso()})
    from trackio import logbook_trace  # noqa: PLC0415

    logbook_trace.adopt_published_state(proj)
    write_site_files(proj)
    return proj


# ---- safe append/create helpers ----


def _all_slugs(proj: Path) -> set[str]:
    slugs = {ROOT_SLUG}
    for d in _pages_dir(proj).iterdir():
        if d.is_dir() and (d / "page.md").is_file():
            slugs.add(d.name)
    return slugs


def _page_dir_for_slug(proj: Path, slug: str) -> Path | None:
    if slug == ROOT_SLUG:
        return _pages_dir(proj)
    for d in _pages_dir(proj).iterdir():
        if d.is_dir() and d.name == slug and (d / "page.md").is_file():
            return d
    return None


def _page_file_for_slug(proj: Path, slug: str) -> Path | None:
    if slug == ROOT_SLUG:
        return _pages_dir(proj) / "index.md"
    d = _page_dir_for_slug(proj, slug)
    return (d / "page.md") if d else None


def add_page(proj: Path, title: str) -> str:
    existing = _all_slugs(proj)
    base = _slugify(title)
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}-{n}"
        n += 1
    page_dir = _pages_dir(proj) / slug
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "page.md").write_text(f"# {title}\n", encoding="utf-8")
    write_site_files(proj)
    return slug


def _parse_table_cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _toc_row(header_cells: list[str], name: str, slug: str, status: str | None) -> str:
    link = f"[{name}](#/{slug})"
    cells = []
    link_at = None
    for i, header in enumerate(header_cells):
        if STATUS_COL_RE.search(header):
            cells.append(status or "planned")
        elif link_at is None and LINK_COL_RE.search(header):
            cells.append(link)
            link_at = i
        else:
            cells.append("")
    if link_at is None:
        link_at = next(
            (i for i, h in enumerate(header_cells) if not STATUS_COL_RE.search(h)),
            0,
        )
        cells[link_at] = link
    return "| " + " | ".join(cells) + " |"


def _insert_toc_row(text: str, name: str, slug: str, status: str | None) -> str:
    lines = [
        ln
        for ln in text.split("\n")
        if not (
            ln.strip().startswith("|")
            and any(token in ln for token in TOC_PLACEHOLDER_TOKENS)
        )
    ]
    idx = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.strip().lower() in ("## pages", "## experiments")
        ),
        None,
    )
    if idx is not None:
        table_at = None
        j = idx + 1
        while j < len(lines):
            stripped = lines[j].strip()
            if stripped.startswith("|"):
                table_at = j
                break
            if stripped.startswith("#"):
                break
            j += 1
        if table_at is not None:
            row = _toc_row(_parse_table_cells(lines[table_at]), name, slug, status)
            k = table_at
            while k < len(lines) and lines[k].strip().startswith("|"):
                k += 1
            lines.insert(k, row)
            return "\n".join(lines)
        row = _toc_row(["Page"], name, slug, status)
        lines[idx + 1 : idx + 1] = ["", TOC_HEADER, TOC_SEP, row, ""]
        return "\n".join(lines)
    row = _toc_row(["Page"], name, slug, status)
    block = ["", TOC_HEADING, "", TOC_HEADER, TOC_SEP, row, ""]
    h1 = next((i for i, ln in enumerate(lines) if ln.strip().startswith("# ")), None)
    at = (h1 + 1) if h1 is not None else len(lines)
    lines[at:at] = block
    return "\n".join(lines)


def set_page_status(proj: Path, slug: str, status: str) -> None:
    index = _pages_dir(proj) / "index.md"
    lines = index.read_text(encoding="utf-8").split("\n")
    row_at = next(
        (
            i
            for i, ln in enumerate(lines)
            if f"(#/{slug})" in ln and ln.strip().startswith("|")
        ),
        None,
    )
    if row_at is None:
        return
    head_at = row_at
    while head_at > 0 and lines[head_at - 1].strip().startswith("|"):
        head_at -= 1
    col = next(
        (
            c
            for c, header in enumerate(_parse_table_cells(lines[head_at]))
            if STATUS_COL_RE.search(header)
        ),
        None,
    )
    if col is None:
        return
    cells = _parse_table_cells(lines[row_at])
    if col >= len(cells):
        return
    cells[col] = status
    lines[row_at] = "| " + " | ".join(cells) + " |"
    index.write_text("\n".join(lines), encoding="utf-8")


def sync_todos_from_stdin() -> None:
    import sys  # noqa: PLC0415

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    todos = (payload.get("tool_input") or {}).get("todos") or []
    proj = find_project_dir(payload.get("cwd"))
    if proj is None or not todos:
        return
    status_map = {
        "pending": "planned",
        "in_progress": "in-progress",
        "completed": "done",
    }
    changed = False
    for todo in todos:
        name = (todo.get("content") or todo.get("activeForm") or "").strip()
        if not name:
            continue
        try:
            ensure_page(
                proj, name, status=status_map.get(todo.get("status"), "planned")
            )
            changed = True
        except Exception:
            continue
    if changed:
        write_site_files(proj)


def ensure_page(
    proj: Path,
    title_or_slug: str,
    status: str | None = None,
) -> str:
    name = title_or_slug.strip()
    if not name:
        raise LogbookError("Page title cannot be empty.")
    if name == ROOT_SLUG:
        raise LogbookError("Cannot target the logbook index page.")
    if _page_file_for_slug(proj, name) is not None:
        _remember_page(proj, name)
        return name
    slug = _slugify(name)
    if slug in _all_slugs(proj):
        if status:
            set_page_status(proj, slug, status)
        _remember_page(proj, slug)
        return slug
    slug = add_page(proj, name)
    index = _pages_dir(proj) / "index.md"
    index.write_text(
        _insert_toc_row(index.read_text(encoding="utf-8"), name, slug, status),
        encoding="utf-8",
    )
    _remember_page(proj, slug)
    return slug


def resolve_page(proj: Path, page: str | None = None) -> str:
    if page:
        return ensure_page(proj, page)
    slug = read_metadata(proj).get("last_page")
    if slug and _page_file_for_slug(proj, slug) is not None:
        _remember_page(proj, slug)
        return slug
    raise LogbookError("No --page given and no recently-updated page found")


def _resolve_existing_page(proj: Path, page: str | None = None) -> str:
    if not page:
        slug = read_metadata(proj).get("last_page") or ROOT_SLUG
        if _page_file_for_slug(proj, slug) is not None:
            return slug
        return ROOT_SLUG
    if page == ROOT_SLUG and _page_file_for_slug(proj, page) is not None:
        return page
    if _page_file_for_slug(proj, page) is not None:
        return page
    slug = _slugify(page)
    if _page_file_for_slug(proj, slug) is not None:
        return slug
    manifest = build_manifest(proj)
    needle = page.strip().lower()
    for node in _walk(manifest["root"]):
        if node["title"].strip().lower() == needle:
            return node["slug"]
    raise LogbookError(f"No page with title or slug '{page}' in this logbook.")


def _node_for_slug(manifest: dict, slug: str) -> dict | None:
    for node in _walk(manifest["root"]):
        if node["slug"] == slug:
            return node
    return None


def list_pages(proj: Path) -> list[dict]:
    manifest = build_manifest(proj)
    root = logbook_root(proj)
    pages = []
    for node in _walk(manifest["root"]):
        text = (root / node["file"]).read_text(encoding="utf-8")
        cells = _parse_cells_from_text(text, node["slug"], node["title"])
        pages.append(
            {
                "slug": node["slug"],
                "title": node["title"],
                "file": node["file"],
                "cell_count": len(cells),
            }
        )
    return pages


def _figure_parts(body: str) -> dict:
    parts = {"html": "", "raw": ""}
    for match in FENCE_RE.finditer(body):
        lang = (match.group(2).strip().split() or [""])[0].lower()
        if lang in parts and not parts[lang]:
            parts[lang] = match.group(3)
    return parts


def _parse_fences(body: str) -> list[dict]:
    fences = []
    for match in FENCE_RE.finditer(body):
        info = match.group(2).strip()
        lang = (info.split() or [""])[0].lower()
        title = re.search(r"title=(\S+)", info)
        fences.append(
            {
                "lang": lang,
                "title": title.group(1) if title else None,
                "text": match.group(3),
            }
        )
    return fences


def _n_lines(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


def _human_chars(n: int) -> str:
    if n < 1000:
        return f"{n} chars"
    return f"{n / 1000:.1f}k chars"


def _code_summary(cell: dict, head: int, tail: int) -> dict:
    meta = cell["metadata"]
    fences = _parse_fences(cell["body"])
    output = ""
    code_fence = None
    attached = []
    for fence in fences:
        if fence["lang"] in ("output", "result") and not output:
            output = fence["text"]
        elif fence["title"]:
            attached.append((fence["title"], len(fence["text"].split("\n"))))
        elif code_fence is None:
            code_fence = fence

    command = meta.get("command")
    preview_lines: list[str] = []
    if command:
        try:
            command_line = shlex.join(command)
        except TypeError:
            command_line = " ".join(str(token) for token in command)
        line = f"$ {command_line}"
        if meta.get("exit_code") is not None:
            line += f" → exit {meta['exit_code']}"
        if meta.get("duration_s") is not None:
            line += f" ({meta['duration_s']}s)"
        preview_lines.append(line)
        if (
            code_fence
            and code_fence["lang"] == "bash"
            and code_fence["text"].lstrip().startswith("$")
        ):
            code_fence = None
    if attached:
        preview_lines.append(
            "Attached: " + ", ".join(f"{name} ({_n_lines(n)})" for name, n in attached)
        )

    code_head: list[str] = []
    code_lines = 0
    if code_fence:
        source_lines = code_fence["text"].rstrip("\n").split("\n")
        code_lines = len(source_lines)
        if head > 0:
            code_head = source_lines[:head]
            label = f"Code ({code_fence['lang'] or 'text'}, {_n_lines(code_lines)}"
            label += f"; first {head}):" if code_lines > head else "):"
            preview_lines += [label, "````", *code_head, "````"]

    output_tail: list[str] = []
    output_lines = 0
    if output:
        all_lines = output.rstrip("\n").split("\n")
        output_lines = len(all_lines)
        if tail > 0:
            output_tail = all_lines[-tail:]
            label = f"Output ({_n_lines(output_lines)}"
            label += f"; last {tail}):" if output_lines > tail else "):"
            preview_lines += [label, "````", *output_tail, "````"]

    return {
        "command": command,
        "exit_code": meta.get("exit_code"),
        "duration_s": meta.get("duration_s"),
        "language": meta.get("language"),
        "attached": [name for name, _ in attached],
        "code_lines": code_lines,
        "code_head": "\n".join(code_head),
        "output_lines": output_lines,
        "output_tail": "\n".join(output_tail),
        "preview": "\n".join(preview_lines),
    }


def _figure_summary(cell: dict, raw_limit: int) -> dict:
    parts = _figure_parts(cell["body"])
    raw, html = parts["raw"], parts["html"]
    summary = {
        "has_raw": bool(raw),
        "has_html": bool(html),
        "raw_chars": len(raw),
        "html_chars": len(html),
    }
    preview_lines: list[str] = []
    if raw:
        if raw_limit and len(raw) <= raw_limit:
            summary["raw"] = raw
            preview_lines += [
                f"Raw data ({_human_chars(len(raw))}):",
                "````",
                *raw.rstrip("\n").split("\n"),
                "````",
            ]
        else:
            preview_lines.append(f"Raw data: {_human_chars(len(raw))} (--raw).")
    if html:
        preview_lines.append(f"HTML figure: {_human_chars(len(html))} (--html).")
    if not preview_lines:
        preview_lines.append("No figure payloads.")
    summary["preview"] = "\n".join(preview_lines)
    return summary


def _artifact_summary(cell: dict) -> dict:
    lines = [ln.strip() for ln in cell["body"].split("\n") if ln.strip()]
    first = lines[0].replace("**📦 Artifact**", "📦").strip() if lines else "📦"
    bucket_match = BUCKET_URL_RE.search(cell["body"])
    link = bucket_match.group(0) if bucket_match else None
    local = link is None
    path = cell["metadata"].get("path")
    if link:
        preview = f"{first} · {link}"
    elif path:
        preview = f"{first} · local file (pushed to a Bucket on publish)"
    elif local:
        preview = f"{first} · local (pushed to a Bucket on publish)"
    else:
        preview = first
    summary = {
        "artifact": cell["metadata"].get("artifact"),
        "artifact_type": cell["metadata"].get("artifact_type"),
        "local": local,
        "link": link,
        "preview": preview,
    }
    if path:
        summary["path"] = path
    return summary


def _dashboard_summary(cell: dict) -> dict:
    project = cell["metadata"].get("dashboard_project")
    match = SPACE_URL_RE.search(cell["body"])
    link = match.group(0) if match else None
    if link:
        preview = f"🎯 Dashboard `{project}` · {link}"
    else:
        preview = (
            f"🎯 Dashboard `{project}` · local "
            "(live in preview; promoted to a Space on publish)"
        )
    return {
        "project": project,
        "local": link is None,
        "link": link,
        "preview": preview,
    }


def _strip_duplicate_heading(body: str, title: str) -> str:
    match = re.match(r"\s*#{1,6}\s+([^\n]+)\n?", body)
    if not match:
        return body

    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[*_`#]", "", text)).strip().lower()

    if norm(match.group(1)) == norm(title):
        return body[match.end() :].lstrip("\n")
    return body


def _cell_public_summary(
    cell: dict,
    head: int = DEFAULT_HEAD,
    tail: int = DEFAULT_TAIL,
    raw_limit: int = DEFAULT_RAW_LIMIT,
) -> dict:
    summary = {
        "id": cell["id"],
        "type": cell["type"],
        "title": cell["title"],
        "created_at": cell.get("created_at"),
    }
    if cell["type"] == "markdown":
        summary["body"] = cell["body"]
        summary["preview"] = _strip_duplicate_heading(cell["body"], cell["title"])
    elif cell["type"] == "artifact":
        summary["body"] = cell["body"]
        summary.update(_artifact_summary(cell))
    elif cell["type"] == "dashboard":
        summary["body"] = cell["body"]
        summary.update(_dashboard_summary(cell))
    elif cell["type"] == "code":
        summary.update(_code_summary(cell, head, tail))
    elif cell["type"] == "figure":
        summary.update(_figure_summary(cell, raw_limit))
    return summary


def read_page_outline(
    proj: Path,
    page: str | None = None,
    head: int = DEFAULT_HEAD,
    tail: int = DEFAULT_TAIL,
    raw_limit: int = DEFAULT_RAW_LIMIT,
) -> dict:
    slug = _resolve_existing_page(proj, page)
    manifest = build_manifest(proj)
    node = _node_for_slug(manifest, slug)
    if node is None:
        raise LogbookError(f"No page with slug '{slug}' in this logbook.")
    text = (logbook_root(proj) / node["file"]).read_text(encoding="utf-8")
    cells = _parse_cells_from_text(text, node["slug"], node["title"])
    return {
        "slug": node["slug"],
        "title": node["title"],
        "file": node["file"],
        "cells": [
            _cell_public_summary(cell, head=head, tail=tail, raw_limit=raw_limit)
            for cell in cells
        ],
    }


def read_cell(
    proj: Path,
    cell_id: str,
    *,
    include_full: bool = False,
    include_raw: bool = False,
    include_html: bool = False,
) -> dict:
    manifest = build_manifest(proj)
    root = logbook_root(proj)
    for node in _walk(manifest["root"]):
        text = (root / node["file"]).read_text(encoding="utf-8")
        for cell in _parse_cells_from_text(text, node["slug"], node["title"]):
            if cell["id"] == cell_id:
                result = {
                    "id": cell["id"],
                    "type": cell["type"],
                    "title": cell["title"],
                    "created_at": cell.get("created_at"),
                    "page": cell["page"],
                    "page_title": cell["page_title"],
                    "file": node["file"],
                    "metadata": cell["metadata"],
                }
                if cell["type"] in ("markdown", "artifact", "dashboard"):
                    result["body"] = cell["body"]
                elif cell["type"] == "code":
                    if include_full:
                        result["body"] = cell["body"]
                elif cell["type"] == "figure":
                    parts = _figure_parts(cell["body"])
                    result["has_html"] = bool(parts["html"])
                    result["has_raw"] = bool(parts["raw"])
                    if include_full or include_html:
                        result["html"] = parts["html"]
                    if include_full or include_raw:
                        result["raw"] = parts["raw"]
                return result
    raise LogbookError(f"No cell with id '{cell_id}' in this logbook.")


def _resolve_slug(proj: Path, page: str) -> str:
    """Resolve a page slug or title to its slug."""
    want = _slugify(page)
    for node in _walk(build_manifest(proj)["root"]):
        if page in (node["slug"], node["title"]) or node["slug"] == want:
            return node["slug"]
    raise LogbookError(f"No page matching '{page}' in this logbook.")


def last_cell_id(proj: Path, page: str | None = None) -> str | None:
    """Id of the most recent cell on `page` (or the current default page)."""
    slug = _resolve_slug(proj, page) if page else read_metadata(proj).get("last_page")
    if not slug:
        return None
    path = _page_file_for_slug(proj, slug)
    if path is None or not path.exists():
        return None
    cells = _parse_cells_from_text(path.read_text(encoding="utf-8"), slug, "")
    return cells[-1]["id"] if cells else None


def set_cell_pinned(
    proj: Path, cell_id: str, *, pinned: bool = True, page: str | None = None
) -> dict:
    """Pin or unpin a cell by id.

    Pinned cells surface in a deck on the logbook intro (the frontend reads the
    `pinned` flag from each cell's metadata). Rewrites the owning page in place.
    """
    root = logbook_root(proj)
    scope = _resolve_slug(proj, page) if page else None
    for node in _walk(build_manifest(proj)["root"]):
        if scope and node["slug"] != scope:
            continue
        path = root / node["file"]
        text = path.read_text(encoding="utf-8")
        state = {"hit": False, "title": None}

        def _repl(m):
            try:
                meta = json.loads(m.group(2))
            except json.JSONDecodeError:
                return m.group(0)
            if meta.get("id") != cell_id:
                return m.group(0)
            state["hit"] = True
            state["title"] = meta.get("title")
            if pinned:
                meta["pinned"] = True
                meta.setdefault("pinned_at", _now_iso())
            else:
                meta.pop("pinned", None)
                meta.pop("pinned_at", None)
            marker = (
                "<!-- trackio-cell\n" + json.dumps(meta, ensure_ascii=False) + "\n-->"
            )
            return f"{m.group(1)}---\n{marker}\n{m.group(3)}"

        new_text = CELL_RE.sub(_repl, text)
        if state["hit"]:
            path.write_text(new_text, encoding="utf-8")
            write_site_files(proj)
            return {
                "page": node["slug"],
                "page_title": node["title"],
                "title": state["title"],
                "pinned": pinned,
            }
    raise LogbookError(f"No cell with id '{cell_id}' in this logbook.")


# ---- auto-note (called from trackio.finish / log_artifact) ----


def _autonote_enabled() -> bool:
    return os.environ.get("TRACKIO_LOGBOOK_AUTONOTE", "1").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _new_cell_id() -> str:
    return f"cell_{uuid.uuid4().hex[:12]}"


def _cell_marker(cell_type: str, title: str | None = None, **metadata) -> str:
    if cell_type not in CELL_TYPES:
        raise LogbookError(f"Unsupported logbook cell type: {cell_type}")
    title = (title or "").strip() or "Untitled"
    payload = {
        "type": cell_type,
        "id": metadata.pop("id", _new_cell_id()),
        "created_at": metadata.pop("created_at", _now_iso()),
        "title": title,
    }
    payload.update({k: v for k, v in metadata.items() if v not in (None, "", [])})
    return "<!-- trackio-cell\n" + json.dumps(payload, ensure_ascii=False) + "\n-->"


def _shorten(text: str, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _strip_markdown_title(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`>#]+", "", text)
    return text.strip(" -:\t")


def _default_cell_title(cell_type: str, body: str, metadata: dict) -> str:
    command = metadata.get("command")
    if command:
        try:
            return _shorten(f"Run: {shlex.join(command)}")
        except TypeError:
            return "Run"
    if cell_type == "code":
        titled = re.search(r"^````\w*\s+title=([^\n]+)", body, re.M)
        if titled:
            return _shorten(f"Code: {titled.group(1).strip()}")
        return "Code cell"
    if cell_type == "figure":
        return "Figure"
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("````") or line.startswith("<!--"):
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        title = _strip_markdown_title(line)
        if title:
            return _shorten(title)
    return "Markdown cell"


def _parse_cell_meta(raw: str, body: str = "") -> dict:
    try:
        meta = json.loads(raw)
    except Exception:
        meta = {}
    cell_type = meta.get("type") or "markdown"
    if cell_type not in CELL_TYPES:
        cell_type = "markdown"
    meta["type"] = cell_type
    meta["id"] = meta.get("id") or _new_cell_id()
    meta["title"] = (meta.get("title") or "").strip() or _default_cell_title(
        cell_type, body, meta
    )
    return meta


def _parse_cells_from_text(text: str, page_slug: str, page_title: str) -> list[dict]:
    cells = []
    for match in CELL_RE.finditer(text):
        body = match.group(3).strip()
        meta = _parse_cell_meta(match.group(2), body)
        cells.append(
            {
                "id": meta["id"],
                "type": meta["type"],
                "title": meta["title"],
                "created_at": meta.get("created_at"),
                "page": page_slug,
                "page_title": page_title,
                "metadata": meta,
                "body": body,
            }
        )
    return cells


def _append_cell(
    proj: Path,
    page_slug: str,
    cell_type: str,
    body: str,
    title: str | None = None,
    **metadata,
) -> None:
    page_path = _page_file_for_slug(proj, page_slug)
    if page_path is None:
        raise LogbookError(f"No page with slug '{page_slug}' in this logbook.")
    title = (title or "").strip() or _default_cell_title(cell_type, body, metadata)
    block = (
        f"\n\n---\n{_cell_marker(cell_type, title=title, **metadata)}\n{body.strip()}\n"
    )
    with page_path.open("a", encoding="utf-8") as f:
        f.write(block)
    _remember_page(proj, page_slug)
    write_site_files(proj)


def add_markdown_cell(
    proj: Path,
    page_slug: str,
    body: str,
    title: str | None = None,
) -> None:
    _append_cell(proj, page_slug, "markdown", body.strip(), title=title)


def add_code_cell(
    proj: Path,
    page_slug: str,
    output: str,
    title: str | None = None,
    code_paths: list[str] | None = None,
    code_text: str | None = None,
    language: str | None = None,
) -> None:
    lines: list[str] = []
    for path in code_paths or []:
        lines += _code_block_lines(path)
    if code_text:
        lang = language or ""
        lines += ["", f"````{lang}".rstrip(), *code_text.split("\n"), "````", ""]
    lines += ["", "````output", *output.split("\n"), "````", ""]
    _append_cell(
        proj,
        page_slug,
        "code",
        "\n".join(lines),
        title=title,
        language=language,
    )


def _format_size(size: int | None) -> str:
    gb = (size or 0) / 1e9
    if gb >= 0.01:
        return f" · {gb:.2f} GB"
    if size and size >= 100_000:
        return f" · {size / 1e6:.1f} MB"
    if size and size >= 1_000:
        return f" · {size / 1e3:.1f} kB"
    if size:
        return f" · {size} B"
    return ""


def _artifact_stats(qualified_name: str) -> tuple[int, int]:
    try:
        from trackio.sqlite_storage import SQLiteStorage  # noqa: PLC0415

        project_and_name = qualified_name.split(":")[0]
        if "/" not in project_and_name:
            return (0, 0)
        project, art_name = project_and_name.split("/", 1)
        manifest = SQLiteStorage.get_artifact_manifest(project, art_name)
        return (sum(entry.get("size", 0) for entry in manifest), len(manifest))
    except Exception:
        return (0, 0)


def add_artifact_cell(
    proj: Path,
    page_slug: str,
    qualified_name: str,
    size: int | None = None,
    title: str | None = None,
    artifact_type: str | None = None,
) -> None:
    files = 0
    if size is None:
        size, files = _artifact_stats(qualified_name)
    register_local(proj, artifact=qualified_name)
    line = f"**📦 Artifact** `{qualified_name}`"
    if artifact_type and artifact_type != "artifact":
        line += f" · {artifact_type}"
    if files:
        line += f" · {files} files"
    line += _format_size(size)
    body = f"{line}\n\n{ARTIFACT_URI_PREFIX}{qualified_name}"
    _append_cell(
        proj,
        page_slug,
        "artifact",
        body,
        title=title or f"Artifact: {qualified_name}",
        artifact=qualified_name,
        artifact_type=artifact_type,
    )


def add_dashboard_cell(
    proj: Path,
    page_slug: str,
    project: str,
    space_id: str | None = None,
    title: str | None = None,
) -> None:
    if space_id:
        link = f"https://huggingface.co/spaces/{space_id}"
    else:
        link = f"{LOCAL_DASHBOARD_PREFIX}{project}"
        register_local(proj, dashboard_project=project)
    body = f"**🎯 Trackio dashboard** `{project}`\n\n{link}"
    _append_cell(
        proj,
        page_slug,
        "dashboard",
        body,
        title=title or f"Dashboard: {project}",
        dashboard_project=project,
    )


def add_path_artifact_cell(
    proj: Path,
    page_slug: str,
    path: str,
    size: int,
    artifact_type: str | None = None,
    title: str | None = None,
) -> None:
    display = _artifact_display_path(path)
    shown = display if "`" in display else f"`{display}`"
    line = f"**📦 Artifact** {shown}"
    if artifact_type:
        line += f" · {artifact_type}"
    line += _format_size(size)
    body = f"{line}\n\n{PATH_ARTIFACT_URI_PREFIX}{display}"
    register_local(
        proj,
        path_artifact={
            "path": display,
            "abs_path": str(Path(path).resolve()),
            "size": size,
            "artifact_type": artifact_type,
        },
    )
    _append_cell(
        proj,
        page_slug,
        "artifact",
        body,
        title=title or f"Artifact: {Path(path).name}",
        path=display,
        size=size,
        artifact_type=artifact_type,
        auto=True,
    )


FIGURE_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".avif": "image/avif",
    ".svg": "image/svg+xml",
}


def is_figure_image_path(path: str | Path) -> bool:
    """Whether ``path`` points at an image file trackio can embed in a figure."""
    return Path(path).suffix.lower() in FIGURE_IMAGE_MIME_BY_SUFFIX


def figure_html_from_image(path: str | Path) -> str:
    """Build an ``<img>`` tag with a base64 data URI from a local image file.

    Lets figure cells accept an image path (e.g. a matplotlib PNG) directly,
    instead of requiring the caller to hand-encode the image into HTML.
    """
    path = Path(path)
    mime = FIGURE_IMAGE_MIME_BY_SUFFIX.get(path.suffix.lower())
    if mime is None:
        supported = ", ".join(sorted(FIGURE_IMAGE_MIME_BY_SUFFIX))
        raise LogbookError(
            f"Unsupported image type '{path.suffix or path.name}'. "
            f"Supported image extensions: {supported}."
        )
    if not path.is_file():
        raise LogbookError(f"Image file not found: {path}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    alt = html.escape(path.stem)
    return (
        f'<img src="data:{mime};base64,{encoded}" alt="{alt}" '
        'style="max-width:100%;height:auto;" />'
    )


def add_figure_cell(
    proj: Path,
    page_slug: str,
    html: str | None = None,
    raw: str | None = None,
    title: str | None = None,
    image: str | Path | None = None,
) -> None:
    if image:
        html = figure_html_from_image(image)
    if not html:
        raise LogbookError("Figure cells require HTML content or an image.")
    if len(html) > 1_000_000:
        print(
            f"Note: figure HTML is {len(html) / 1_000_000:.1f} MB and is stored "
            "inside the page. For Plotly, export with "
            'fig.write_html(..., include_plotlyjs="cdn") to keep pages small.',
            file=sys.stderr,
        )
    lines = ["````html", html, "````", ""]
    if raw:
        lines += ["````raw", raw, "````", ""]
    _append_cell(proj, page_slug, "figure", "\n".join(lines), title=title)


def register_local(
    proj: Path,
    dashboard_project: str | None = None,
    artifact: str | None = None,
    path_artifact: dict | None = None,
) -> None:
    metadata = read_metadata(proj)
    if dashboard_project:
        metadata.setdefault("local_dashboards", {}).setdefault(dashboard_project, None)
    if artifact:
        arts = metadata.setdefault("local_artifacts", [])
        if artifact not in arts:
            arts.append(artifact)
    if path_artifact:
        entries = metadata.setdefault("local_path_artifacts", [])
        entries[:] = [e for e in entries if e.get("path") != path_artifact["path"]]
        entries.append(path_artifact)
    write_metadata(proj, metadata)


def _page_has_dashboard_cell(proj: Path, slug: str, project: str) -> bool:
    path = _page_file_for_slug(proj, slug)
    if path is None or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if f"{LOCAL_DASHBOARD_PREFIX}{project}" in text:
        return True
    for cell in _parse_cells_from_text(text, slug, slug):
        if (
            cell["type"] == "dashboard"
            and cell["metadata"].get("dashboard_project") == project
        ):
            return True
    return False


def auto_note_dashboard(project: str, space_id: str | None = None) -> None:
    if not _autonote_enabled():
        return
    proj = find_project_dir()
    if proj is None:
        return
    try:
        slug = resolve_page(proj)
        if _page_has_dashboard_cell(proj, slug, project):
            return
        add_dashboard_cell(proj, slug, project, space_id=space_id)
    except Exception:
        pass


def auto_note_artifact(
    project: str,
    qualified_name: str,
    size: int = 0,
    artifact_type: str | None = None,
) -> None:
    if not _autonote_enabled():
        return
    proj = find_project_dir()
    if proj is None:
        return
    try:
        slug = ensure_page(proj, project)
        add_artifact_cell(
            proj, slug, qualified_name, size=size, artifact_type=artifact_type
        )
    except Exception:
        pass


_LANG_BY_EXT = {
    ".py": "python",
    ".sh": "bash",
    ".bash": "bash",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".js": "javascript",
    ".ts": "typescript",
    ".sql": "sql",
    ".toml": "toml",
    ".md": "markdown",
}

_ARTIFACT_TYPE_BY_EXT = {
    ".pt": "model",
    ".pth": "model",
    ".ckpt": "model",
    ".safetensors": "model",
    ".gguf": "model",
    ".onnx": "model",
    ".pkl": "model",
    ".joblib": "model",
    ".h5": "model",
    ".tflite": "model",
    ".pb": "model",
    ".npz": "dataset",
    ".npy": "dataset",
    ".parquet": "dataset",
    ".csv": "dataset",
    ".tsv": "dataset",
    ".arrow": "dataset",
    ".jsonl": "dataset",
    ".feather": "dataset",
    ".msgpack": "dataset",
}
_SNAPSHOT_SKIP_DIRS = {"__pycache__", "node_modules", "venv", "env", "site-packages"}
_SNAPSHOT_MAX_ENTRIES = 50_000
_MAX_AUTO_ARTIFACT_CELLS = 10


def _code_block_lines(path: str) -> list[str]:
    p = Path(path)
    try:
        content = p.read_text(encoding="utf-8")
    except OSError:
        return []
    if len(content) > 200_000:
        content = content[:200_000] + "\n# … truncated …"
    lang = _LANG_BY_EXT.get(p.suffix.lower(), "")
    return ["", f"````{lang} title={p.name}", *content.split("\n"), "````", ""]


def _truncate_run_output(output: str) -> str:
    if len(output) <= RUN_OUTPUT_LIMIT:
        return output
    omitted = len(output) - RUN_OUTPUT_HEAD - RUN_OUTPUT_TAIL
    marker = f"\n... [{omitted} chars elided] ...\n"
    return output[:RUN_OUTPUT_HEAD] + marker + output[-RUN_OUTPUT_TAIL:]


def _detect_code_paths(command: list[str]) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for token in command:
        path = Path(token)
        if not path.is_file() or path.suffix.lower() not in _LANG_BY_EXT:
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        paths.append(str(path))
    return paths


def _snapshot_output_files(root: Path) -> dict[str, tuple[int, int]] | None:
    snapshot: dict[str, tuple[int, int]] = {}
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".") and d not in _SNAPSHOT_SKIP_DIRS
        ]
        scanned += len(dirnames) + len(filenames)
        if scanned > _SNAPSHOT_MAX_ENTRIES:
            return None
        for name in filenames:
            if Path(name).suffix.lower() not in _ARTIFACT_TYPE_BY_EXT:
                continue
            full = os.path.join(dirpath, name)
            try:
                if os.path.islink(full):
                    continue
                stat = os.stat(full)
            except OSError:
                continue
            snapshot[full] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _diff_output_files(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
) -> list[tuple[str, int]]:
    changed = [
        (path, stat[1])
        for path, stat in after.items()
        if stat[1] > 0 and before.get(path) != stat
    ]
    changed.sort(key=lambda item: (-item[1], item[0]))
    return changed


def _artifact_display_path(path: str) -> str:
    try:
        rel = os.path.relpath(path)
    except ValueError:
        return Path(path).as_posix()
    if rel.startswith(".."):
        return Path(path).as_posix()
    return Path(rel).as_posix()


def add_run_cell(
    proj: Path,
    page_slug: str,
    command: list[str],
    output: str,
    exit_code: int,
    duration_s: float,
    code_paths: list[str],
    title: str | None = None,
    artifact_note: str | None = None,
) -> None:
    command_line = shlex.join(command)
    lines = [
        "````bash",
        f"$ {command_line}",
        "````",
        "",
        f"exit {exit_code} · {duration_s:.1f}s",
        "",
    ]
    if artifact_note:
        lines += [artifact_note, ""]
    for path in code_paths:
        lines += _code_block_lines(path)
    lines += ["", "````output", *output.split("\n"), "````", ""]
    if title is None:
        command_name = Path(command[0]).name
        if code_paths:
            command_name = f"{command_name} {Path(code_paths[0]).name}"
        title = f"Run: {command_name} (exit {exit_code})"
    _append_cell(
        proj,
        page_slug,
        "code",
        "\n".join(lines),
        title=title,
        command=command,
        exit_code=exit_code,
        duration_s=round(duration_s, 3),
    )


def run_and_log(
    proj: Path,
    command: list[str],
    page: str | None = None,
    title: str | None = None,
    capture_artifacts: bool = True,
) -> int:
    if not command:
        raise LogbookError("No command provided. Use: trackio logbook run -- <command>")
    slug = resolve_page(proj, page)
    code_paths = _detect_code_paths(command)
    before = None
    if capture_artifacts and _autonote_enabled():
        try:
            before = _snapshot_output_files(Path.cwd())
        except Exception:
            before = None
    output_parts: list[str] = []
    started = time.monotonic()
    interrupted = False
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as e:
        raise LogbookError(f"Command not found: {command[0]}") from e

    try:
        assert proc.stdout is not None
        for chunk in proc.stdout:
            sys.stdout.write(chunk)
            sys.stdout.flush()
            output_parts.append(chunk)
        exit_code = proc.wait()
    except KeyboardInterrupt:
        interrupted = True
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        exit_code = 130
        marker = "\n[interrupted]\n"
        sys.stdout.write(marker)
        sys.stdout.flush()
        output_parts.append(marker)

    duration_s = time.monotonic() - started
    output = _truncate_run_output("".join(output_parts))
    changed: list[tuple[str, int]] = []
    artifact_note = None
    if before is not None:
        try:
            after = _snapshot_output_files(Path.cwd())
            changed = _diff_output_files(before, after or {})
        except Exception:
            changed = []
        if len(changed) > _MAX_AUTO_ARTIFACT_CELLS:
            artifact_note = (
                f"{len(changed)} output files detected; recording the "
                f"{_MAX_AUTO_ARTIFACT_CELLS} largest."
            )
            changed = changed[:_MAX_AUTO_ARTIFACT_CELLS]
    add_run_cell(
        proj,
        slug,
        command,
        output,
        exit_code,
        duration_s,
        code_paths,
        title=title,
        artifact_note=artifact_note,
    )
    for path, size in changed:
        try:
            add_path_artifact_cell(
                proj,
                slug,
                path,
                size,
                artifact_type=_ARTIFACT_TYPE_BY_EXT.get(Path(path).suffix.lower()),
            )
        except Exception:
            pass
    return 130 if interrupted else exit_code


def status_text(proj: Path) -> str:
    manifest = write_site_files(proj)
    metadata = read_metadata(proj)
    lines = [
        f"🎯  {manifest['title']}",
        f"    dir     {logbook_root(proj)}",
    ]
    if metadata.get("space_id"):
        lines.append(f"    space   {metadata['space_id']}  (publish manually)")

    def render(node, depth):
        marker = "•" if depth else "▸"
        lines.append(f"    {'  ' * depth}{marker} {node['title']}  ({node['slug']})")
        for child in node.get("children", []):
            render(child, depth + 1)

    lines.append("")
    lines.append("  Pages:")
    render(manifest["root"], 0)
    return "\n".join(lines)


# ---- serve / publish ----


def _highlight_command(text: str) -> str:
    return f"\033[1m\033[38;5;208m{text}\033[0m"


def _find_preview_port(port: int) -> int:
    import socket  # noqa: PLC0415

    if port == 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
    for candidate in range(port, port + TRY_NUM_PORTS):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return candidate
    raise LogbookError(
        f"Cannot find empty port in range: {port}-{port + TRY_NUM_PORTS - 1}. "
        "Pass --port to choose another starting port."
    )


def start_preview(proj: Path, port: int = 7861, open_browser: bool = True) -> str:
    import webbrowser  # noqa: PLC0415

    write_site_files(proj)
    actual_port = _find_preview_port(port)
    root = logbook_root(proj)
    log_path = root / ".serve.log"
    cmd = [
        sys.executable,
        "-m",
        "trackio.cli",
        "logbook",
        "serve",
        str(proj.parent),
        "--port",
        str(actual_port),
        "--no-browser",
    ]
    log = log_path.open("a", encoding="utf-8")
    subprocess.Popen(
        cmd,
        cwd=str(proj.parent),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    url = f"http://localhost:{actual_port}/"
    print(_highlight_command(f"* Trackio logbook launched at: {url}"))
    print(f"  Server logs: {log_path}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return url


def _logbook_static_app(root: Path):
    from starlette.applications import Starlette  # noqa: PLC0415
    from starlette.responses import FileResponse, PlainTextResponse  # noqa: PLC0415
    from starlette.routing import Route  # noqa: PLC0415

    root = root.resolve()

    async def endpoint(request):
        rel = request.path_params.get("path", "") or "index.html"
        candidate = (root / rel).resolve()
        if not candidate.is_relative_to(root):
            return PlainTextResponse("Not found", status_code=404)
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            return PlainTextResponse("Not found", status_code=404)
        return FileResponse(candidate, headers={"Cache-Control": "no-store, max-age=0"})

    return Starlette(routes=[Route("/{path:path}", endpoint)])


def _build_preview_app(proj: Path):
    import threading  # noqa: PLC0415

    from starlette.applications import Starlette  # noqa: PLC0415
    from starlette.concurrency import run_in_threadpool  # noqa: PLC0415
    from starlette.responses import FileResponse, PlainTextResponse  # noqa: PLC0415
    from starlette.routing import Mount, Route  # noqa: PLC0415

    from trackio.frontend_config import resolve_frontend_dir  # noqa: PLC0415
    from trackio.server import build_starlette_app_only  # noqa: PLC0415

    dashboard_app, _write_token = build_starlette_app_only(
        mcp_server=False,
        frontend_dir=str(resolve_frontend_dir(None).path),
    )
    static_app = _logbook_static_app(logbook_root(proj))
    refresh_lock = threading.Lock()
    refresh_state = {"last": 0.0}

    def refresh_live_files() -> None:
        with refresh_lock:
            now = time.monotonic()
            if now - refresh_state["last"] < 2.0:
                return
            write_site_files(proj)
            refresh_state["last"] = now

    async def live_manifest(_request):
        # The frontend polls this file every 1.5 seconds. Refreshing here keeps
        # explicitly attached active traces and their Workspace view current
        # without a background process or any remote upload.
        await run_in_threadpool(refresh_live_files)
        return FileResponse(
            _manifest_path(proj),
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    async def workspace_file(request):
        from trackio import logbook_trace  # noqa: PLC0415

        relative = request.path_params.get("path", "")
        candidate = logbook_trace.resolve_workspace_file(proj, relative)
        if candidate is None:
            return PlainTextResponse("Not found", status_code=404)
        return FileResponse(
            candidate,
            filename=candidate.name,
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    return Starlette(
        routes=[
            Route("/logbook.json", live_manifest),
            Route("/__trackio_workspace__/{path:path}", workspace_file),
            Mount("/dashboard", app=dashboard_app),
            Mount("/", app=static_app),
        ]
    )


def serve(
    path: str | Path | None = None, port: int = 7861, open_browser: bool = True
) -> None:
    import time as _time  # noqa: PLC0415
    import webbrowser  # noqa: PLC0415

    from trackio.launch import start_server  # noqa: PLC0415

    proj = require_project_dir(path)
    write_site_files(proj)
    app = _build_preview_app(proj)

    candidates = (
        [_find_preview_port(0)] if port == 0 else range(port, port + TRY_NUM_PORTS)
    )
    server = None
    actual_port = None
    last_err: Exception | None = None
    for candidate_port in candidates:
        try:
            _name, actual_port, _url, server = start_server(
                app, server_name="127.0.0.1", server_port=candidate_port
            )
            break
        except OSError as e:
            last_err = e
            continue
    if server is None:
        raise LogbookError(
            f"Cannot find empty port in range: {port}-{port + TRY_NUM_PORTS - 1}. "
            "Pass --port to choose another starting port."
        ) from last_err

    url = f"http://localhost:{actual_port}/"
    print(_highlight_command(f"* Trackio logbook launched at: {url}"))
    print(f"  Dashboard embedded at: {url}dashboard/")
    print("Press Ctrl+C to stop.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        while True:
            _time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.")


def _readme(manifest: dict) -> str:
    emoji = manifest.get("emoji", "🎯")
    title = json.dumps(manifest["title"], ensure_ascii=False)
    extra_tags = "".join(f" - {tag}\n" for tag in manifest.get("tags") or [])
    return (
        f"---\ntitle: {title}\nemoji: {emoji}\ncolorFrom: yellow\ncolorTo: red\n"
        "sdk: static\npinned: false\ntags:\n - trackio\n - trackio-logbook\n"
        f" - open-experiment\n{extra_tags}---\n\n"
        f"# {manifest['title']}\n\nAn open experiment logbook, published with "
        "[Trackio](https://github.com/gradio-app/trackio).\n"
    )


def _push(
    proj: Path,
    hf_token: str | None = None,
    private: bool = False,
) -> str:
    import huggingface_hub  # noqa: PLC0415

    from trackio import logbook_trace  # noqa: PLC0415

    metadata = read_metadata(proj)
    space_id = metadata["space_id"]
    private = bool(metadata.get("private", private))
    trace_policy = metadata.get("trace_publication", "none")
    trace_dataset = metadata.get("trace_dataset")
    generated = logbook_trace.refresh_all(proj, bucket_id=_workspace_bucket(metadata))
    trace_count = len(generated.get("traces", {}).get("sessions") or [])
    workspace_file_count = generated.get("workspace", {}).get("file_count", 0)
    if trace_count and trace_policy in {"public", "private"} and trace_dataset:
        print(f"  · pushing agent traces → dataset {trace_dataset}")
        try:
            logbook_trace.sync_trace_dataset(
                proj,
                trace_dataset,
                private=trace_policy == "private",
                token=hf_token,
            )
        except logbook_trace.TraceCaptureError as e:
            raise LogbookError(str(e)) from e
    workspace_policy = metadata.get("workspace_publication", "none")
    workspace_bucket = metadata.get("workspace_bucket")
    if (
        workspace_file_count
        and workspace_policy in {"public", "private"}
        and workspace_bucket
    ):
        print(f"  · pushing Workspace files → bucket {workspace_bucket}")
        try:
            logbook_trace.sync_workspace_bucket(
                proj,
                workspace_bucket,
                private=workspace_policy == "private",
                token=hf_token,
            )
        except logbook_trace.TraceCaptureError as e:
            raise LogbookError(str(e)) from e
    manifest = write_site_files(proj)
    (logbook_root(proj) / "README.md").write_text(_readme(manifest), encoding="utf-8")
    api = huggingface_hub.HfApi(token=hf_token)
    huggingface_hub.create_repo(
        space_id,
        repo_type="space",
        space_sdk="static",
        exist_ok=True,
        private=private,
        token=hf_token,
    )
    with tempfile.TemporaryDirectory(prefix="trackio-logbook-publish-") as tmp:
        upload_root = Path(tmp) / "logbook"
        shutil.copytree(logbook_root(proj), upload_root)
        published_manifest = json.loads(json.dumps(manifest))
        can_embed_traces = trace_policy == "public" or (
            trace_policy == "private" and private
        )
        if trace_policy == "private" and not private:
            print("  · private traces are not embedded in the public logbook Space")
        if not can_embed_traces:
            published_manifest["traces"] = []
            shutil.rmtree(upload_root / "traces", ignore_errors=True)
        if trace_dataset and trace_policy in {"public", "private"}:
            published_manifest["trace_dataset"] = (
                f"https://huggingface.co/datasets/{trace_dataset}"
            )
        if workspace_bucket and workspace_policy in {"public", "private"}:
            published_manifest["workspace_bucket"] = (
                f"https://huggingface.co/buckets/{workspace_bucket}"
            )
        can_embed_workspace = workspace_policy == "public" or (
            workspace_policy == "private" and private
        )
        if workspace_policy == "private" and not private:
            print(
                "  · private Workspace inventory is not embedded in the public "
                "logbook Space"
            )
        if not can_embed_workspace:
            published_manifest["workspace"] = {
                "file": "workspace.json",
                "file_count": 0,
                "total_size": 0,
                "bucket_id": None,
            }
            (upload_root / "workspace.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "file_count": 0,
                        "total_size": 0,
                        "files": [],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        (upload_root / "logbook.json").write_text(
            json.dumps(published_manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        api.upload_folder(
            repo_id=space_id,
            repo_type="space",
            folder_path=str(upload_root),
            commit_message=f"Update logbook: {manifest['title']}",
            ignore_patterns=[".sync_lock", ".sync_pending", ".sync.log"],
            delete_patterns=["traces/**", "workspace.json"],
        )
    return f"https://huggingface.co/spaces/{space_id}"


def _rewrite_in_pages(proj: Path, old: str, new: str) -> None:
    for md in _pages_dir(proj).rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        if old in text:
            md.write_text(text.replace(old, new), encoding="utf-8")


def _promote_local_deps(proj: Path, ns: str, private: bool) -> None:
    metadata = read_metadata(proj)
    dashboards = metadata.get("local_dashboards", {})
    for project, published in list(dashboards.items()):
        target = published or f"{ns}/{project}"
        if published is None:
            try:
                from trackio import sync as trackio_sync  # noqa: PLC0415

                print(f"  · promoting dashboard '{project}' → {target}")
                trackio_sync(project=project, space_id=target, private=private)
                dashboards[project] = target
            except Exception as e:
                print(f"  · could not promote dashboard '{project}': {e}")
                continue
        _rewrite_in_pages(
            proj,
            f"{LOCAL_DASHBOARD_PREFIX}{project}",
            f"https://huggingface.co/spaces/{target}",
        )
    metadata["local_dashboards"] = dashboards

    arts = metadata.get("local_artifacts", [])
    path_arts = metadata.get("local_path_artifacts", [])
    bucket = metadata.get("artifacts_bucket")
    if arts or path_arts:
        owner, _, name = metadata["space_id"].partition("/")
        bucket = bucket or f"{owner}/{name}-artifacts"
        metadata["artifacts_bucket"] = bucket
        try:
            from trackio import bucket_storage  # noqa: PLC0415

            bucket_storage.create_bucket_if_not_exists(bucket, private=private)

            for project in sorted({a.split("/")[0] for a in arts if "/" in a}):
                print(f"  · pushing artifacts for '{project}' → bucket {bucket}")
                bucket_storage.upload_project_to_bucket(project, bucket)
            for art in arts:
                _rewrite_in_pages(
                    proj,
                    f"{ARTIFACT_URI_PREFIX}{art}",
                    f"https://huggingface.co/buckets/{bucket}#{art}",
                )

            if path_arts:
                print(
                    f"  · pushing {len(path_arts)} local file artifact(s) → "
                    f"bucket {bucket}"
                )
                uploaded = bucket_storage.upload_logbook_path_artifacts_to_bucket(
                    bucket, path_arts
                )
                for rel in uploaded:
                    _rewrite_in_pages(
                        proj,
                        f"{PATH_ARTIFACT_URI_PREFIX}{rel}",
                        f"https://huggingface.co/buckets/{bucket}#"
                        f"{bucket_storage.LOGBOOK_FILES_BUCKET_PREFIX}/{rel}",
                    )
                missing = [e["path"] for e in path_arts if e["path"] not in uploaded]
                for rel in missing:
                    print(f"  · skipped local file artifact (missing on disk): {rel}")

        except Exception as e:
            print(f"  · could not push artifacts to bucket: {e}")

    write_metadata(proj, metadata)


def _retract_retired_publications(proj: Path, hf_token: str | None) -> None:
    import huggingface_hub  # noqa: PLC0415

    metadata = read_metadata(proj)
    dataset_id = metadata.get("trace_retraction_pending")
    bucket_id = metadata.get("workspace_retraction_pending")
    if not dataset_id and not bucket_id:
        return
    api = huggingface_hub.HfApi(token=hf_token)
    if dataset_id:
        print(f"  · retracting prior agent traces Dataset {dataset_id}")
        api.delete_repo(
            dataset_id,
            repo_type="dataset",
            missing_ok=True,
            token=hf_token,
        )
        metadata.pop("trace_retraction_pending", None)
        if (
            metadata.get("trace_publication") == "none"
            and metadata.get("trace_dataset") == dataset_id
        ):
            metadata.pop("trace_dataset", None)
    if bucket_id:
        print(f"  · retracting prior Workspace Bucket {bucket_id}")
        api.delete_bucket(bucket_id, missing_ok=True, token=hf_token)
        metadata.pop("workspace_retraction_pending", None)
        if (
            metadata.get("workspace_publication") == "none"
            and metadata.get("workspace_bucket") == bucket_id
        ):
            metadata.pop("workspace_bucket", None)
    write_metadata(proj, metadata)


def publish(
    space_id: str | None = None,
    hf_token: str | None = None,
    private: bool = False,
    trace_publication: str | None = None,
    workspace_publication: str | None = None,
) -> str:
    proj = require_project_dir()
    metadata = read_metadata(proj)
    metadata_before_publish = copy.deepcopy(metadata)
    previous_space = metadata.get("space_id")
    previous_trace_policy = metadata.get("trace_publication")
    previous_workspace_policy = metadata.get("workspace_publication")
    remember_trace_policy = (
        trace_publication is not None or previous_trace_policy is not None
    )
    remember_workspace_policy = (
        workspace_publication is not None or previous_workspace_policy is not None
    )
    space_id = space_id or metadata.get("space_id")
    if not space_id:
        raise LogbookError(
            "No Space id. Provide one: trackio logbook publish <username/space>"
        )
    trace_publication = trace_publication or previous_trace_policy or "none"
    workspace_publication = workspace_publication or previous_workspace_policy or "none"
    valid_publication = {"public", "private", "none"}
    if trace_publication not in valid_publication:
        raise LogbookError(f"Unknown trace publication policy: {trace_publication}")
    if workspace_publication not in valid_publication:
        raise LogbookError(
            f"Unknown Workspace publication policy: {workspace_publication}"
        )
    owner, _, name = space_id.partition("/")
    old_owner, _, old_name = (previous_space or "").partition("/")
    old_trace_default = (
        f"{old_owner}/{old_name}-traces" if old_owner and old_name else None
    )
    old_workspace_defaults = (
        {
            f"{old_owner}/{old_name}-workspace",
            f"{old_owner}/{old_name}-workspace-public",
            f"{old_owner}/{old_name}-workspace-private",
        }
        if old_owner and old_name
        else set()
    )
    if previous_space and previous_space != space_id:
        if (
            not metadata.get("trace_dataset")
            or metadata.get("trace_dataset") == old_trace_default
        ):
            metadata["trace_dataset"] = f"{owner}/{name}-traces"
        if (
            not metadata.get("workspace_bucket")
            or metadata.get("workspace_bucket") in old_workspace_defaults
        ):
            metadata["workspace_bucket"] = f"{owner}/{name}-workspace"
    metadata["space_id"] = space_id
    metadata.pop("autosync", None)
    metadata["private"] = private
    if remember_trace_policy:
        metadata["trace_publication"] = trace_publication
    if remember_workspace_policy:
        metadata["workspace_publication"] = workspace_publication
    if trace_publication in {"public", "private"}:
        metadata["trace_dataset"] = metadata.get("trace_dataset") or (
            f"{owner}/{name}-traces"
        )
        if metadata.get("trace_retraction_pending") == metadata["trace_dataset"]:
            metadata.pop("trace_retraction_pending", None)
    if workspace_publication in {"public", "private"}:
        workspace_bucket = metadata.get("workspace_bucket")
        if (
            workspace_bucket
            and previous_workspace_policy in {"public", "private"}
            and previous_workspace_policy != workspace_publication
        ):
            print(
                "  · Workspace visibility changed; using a new Bucket because "
                "existing HF Buckets cannot change visibility. The previous "
                f"Bucket {workspace_bucket} will be retracted after publishing."
            )
            metadata["workspace_retraction_pending"] = workspace_bucket
            workspace_bucket = f"{owner}/{name}-workspace-{workspace_publication}"
        metadata["workspace_bucket"] = workspace_bucket or f"{owner}/{name}-workspace"
        if metadata.get("workspace_retraction_pending") == metadata["workspace_bucket"]:
            metadata.pop("workspace_retraction_pending", None)
    if previous_trace_policy in {"public", "private"} and trace_publication == "none":
        print(
            "  · Traces are not included in this publish. The prior Dataset "
            f"{metadata.get('trace_dataset')} will be retracted after publishing."
        )
        metadata["trace_retraction_pending"] = metadata.get("trace_dataset")
    if (
        previous_workspace_policy in {"public", "private"}
        and workspace_publication == "none"
    ):
        print(
            "  · Workspace files are not included in this publish. The prior "
            f"Bucket {metadata.get('workspace_bucket')} will be retracted after "
            "publishing."
        )
        metadata["workspace_retraction_pending"] = metadata.get("workspace_bucket")
    write_metadata(proj, metadata)
    try:
        _promote_local_deps(proj, space_id.split("/")[0], private=private)
        url = _push(proj, hf_token=hf_token, private=private)
    except Exception as e:
        write_metadata(proj, metadata_before_publish)
        destinations = [f"Space {space_id}"]
        if trace_publication in {"public", "private"}:
            destinations.append(f"Dataset {metadata.get('trace_dataset')}")
        if workspace_publication in {"public", "private"}:
            destinations.append(f"Bucket {metadata.get('workspace_bucket')}")
        raise LogbookError(
            "Publish failed. One or more remote uploads may already have succeeded; "
            f"inspect {', '.join(destinations)} before retrying. Original error: {e}"
        ) from e
    try:
        _retract_retired_publications(proj, hf_token)
    except Exception as e:
        raise LogbookError(
            "The new logbook was published, but Trackio could not retract a prior "
            "Trace Dataset or Workspace Bucket. The pending retraction was saved "
            f"and will be retried on the next publish. Original error: {e}"
        ) from e
    return url
