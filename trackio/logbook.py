from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR_NAME = ".trackio"
LOGBOOK_SUBDIR = "logbook"
METADATA_FILE = "metadata.json"
SCHEMA_VERSION = 1
ROOT_SLUG = "index"
VIEWER_DIR = Path(__file__).parent / "frontend_templates" / "logbook"

BOARD_HEADER = "| Who | In progress | Completed | Task | Notes |"
BOARD_SEP = "| --- | --- | --- | --- | --- |"
DEFAULT_SECTION = "Backlog"


class LogbookError(Exception):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _human_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return dt.strftime("%b %d, %Y · %H:%M UTC")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "page"


def find_project_dir(start: str | Path | None = None) -> Path | None:
    start = Path(start or Path.cwd()).resolve()
    for d in (start, *start.parents):
        candidate = d / PROJECT_DIR_NAME
        if (candidate / LOGBOOK_SUBDIR / "logbook.json").is_file():
            return candidate
    return None


def require_project_dir() -> Path:
    proj = find_project_dir()
    if proj is None:
        raise LogbookError(
            "No logbook in this directory (or any parent). "
            "Start one with: trackio logbook open [SPACE_ID]"
        )
    return proj


def logbook_root(proj: Path) -> Path:
    return proj / LOGBOOK_SUBDIR


def _manifest_path(proj: Path) -> Path:
    return logbook_root(proj) / "logbook.json"


def _metadata_path(proj: Path) -> Path:
    return proj / METADATA_FILE


def read_manifest(proj: Path) -> dict:
    return json.loads(_manifest_path(proj).read_text(encoding="utf-8"))


def write_manifest(proj: Path, manifest: dict) -> None:
    manifest["updated_at"] = _now_iso()
    _manifest_path(proj).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def read_metadata(proj: Path) -> dict:
    path = _metadata_path(proj)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_metadata(proj: Path, metadata: dict) -> None:
    _metadata_path(proj).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _iter_nodes(node: dict):
    yield node
    for child in node.get("children", []):
        yield from _iter_nodes(child)


def find_node(manifest: dict, slug: str) -> dict | None:
    for node in _iter_nodes(manifest["root"]):
        if node["slug"] == slug:
            return node
    return None


def _all_slugs(manifest: dict) -> set[str]:
    return {node["slug"] for node in _iter_nodes(manifest["root"])}


def create_logbook(
    title: str,
    space_id: str | None = None,
    emoji: str = "🧪",
) -> Path:
    proj = find_project_dir() or (Path.cwd() / PROJECT_DIR_NAME)
    if _manifest_path(proj).exists():
        raise LogbookError(
            f"A logbook already exists at {logbook_root(proj)}. "
            "Attach to it with `trackio logbook open` (no --title)."
        )
    root = logbook_root(proj)
    (root / "pages").mkdir(parents=True, exist_ok=True)
    now = _now_iso()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "title": title,
        "emoji": emoji,
        "created_at": now,
        "updated_at": now,
        "root": {
            "slug": ROOT_SLUG,
            "title": title,
            "file": "pages/index.md",
            "created_at": now,
            "children": [],
        },
    }
    (root / "pages" / "index.md").write_text(
        f"# {title}\n\n"
        "> Plan and track this experiment campaign. Edit this page freely — "
        "the board below is just a Markdown table. Detailed findings live on "
        "subpages.\n\n"
        "## Tasks\n\n"
        f"### {DEFAULT_SECTION}\n\n"
        f"{BOARD_HEADER}\n{BOARD_SEP}\n"
        "| to assign |  |  | "
        'Add tasks with `trackio logbook task "..."` or by editing this table'
        " |  |\n",
        encoding="utf-8",
    )
    write_manifest(proj, manifest)
    write_metadata(proj, {"space_id": space_id, "created_at": now})
    (proj / ".gitignore").write_text(
        ".site/\n.sync_lock\n.sync_pending\n.sync.log\n", encoding="utf-8"
    )
    return proj


def add_page(
    proj: Path,
    title: str,
    parent_slug: str = ROOT_SLUG,
    slug: str | None = None,
) -> str:
    manifest = read_manifest(proj)
    parent = find_node(manifest, parent_slug)
    if parent is None:
        raise LogbookError(f"No page with slug '{parent_slug}' in this logbook.")
    existing = _all_slugs(manifest)
    base = _slugify(slug or title)
    page_slug = base
    n = 2
    while page_slug in existing:
        page_slug = f"{base}-{n}"
        n += 1
    parent_dir = Path(parent["file"]).parent
    if parent["slug"] == ROOT_SLUG:
        rel = Path("pages") / page_slug / "page.md"
    else:
        rel = parent_dir / page_slug / "page.md"
    abs_path = logbook_root(proj) / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(f"# {title}\n", encoding="utf-8")
    now = _now_iso()
    parent.setdefault("children", []).append(
        {
            "slug": page_slug,
            "title": title,
            "file": str(rel).replace("\\", "/"),
            "created_at": now,
            "children": [],
        }
    )
    write_manifest(proj, manifest)
    return page_slug


def _resolve_artifact(name: str) -> str:
    try:
        from trackio.sqlite_storage import SQLiteStorage

        project_and_name = name.split(":")[0] if ":" in name else name
        if "/" not in project_and_name:
            return f"**📦 Artifact** `{name}`"
        project, art_name = project_and_name.split("/", 1)
        manifest = SQLiteStorage.get_artifact_manifest(project, art_name)
        size = sum(entry.get("size", 0) for entry in manifest)
        gb = size / 1e9
        size_str = f"{gb:.2f} GB" if gb >= 0.01 else f"{size / 1e6:.1f} MB"
        return f"**📦 Artifact** `{name}` · {len(manifest)} files · {size_str}"
    except Exception:
        return f"**📦 Artifact** `{name}`"


def add_note(
    proj: Path,
    body: str,
    title: str | None = None,
    page_slug: str = ROOT_SLUG,
    links: list[str] | None = None,
    artifacts: list[str] | None = None,
) -> None:
    manifest = read_manifest(proj)
    node = find_node(manifest, page_slug)
    if node is None:
        raise LogbookError(f"No page with slug '{page_slug}' in this logbook.")
    page_path = logbook_root(proj) / node["file"]
    now = _now_iso()
    lines = ["", "---", ""]
    lines.append(f"### {title.strip() if title else 'Note'}")
    lines.append(f"<!-- entry ts={now} -->")
    lines.append(f"`{_human_time(now)}`")
    lines.append("")
    lines.append(body.strip())
    lines.append("")
    for art in artifacts or []:
        lines.append(f"- {_resolve_artifact(art)}")
    for url in links or []:
        lines.append(f"- {url.strip()}")
    if artifacts or links:
        lines.append("")
    with page_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    write_manifest(proj, manifest)


def _esc_cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _insert_task_row(text: str, section: str, row: str) -> str:
    lines = text.split("\n")
    target = f"### {section}".lower()
    idx = next((i for i, ln in enumerate(lines) if ln.strip().lower() == target), None)
    if idx is None:
        lines += ["", f"### {section}", "", BOARD_HEADER, BOARD_SEP, row, ""]
        return "\n".join(lines)
    j = idx + 1
    while j < len(lines) and not lines[j].strip().startswith("|"):
        j += 1
    if j >= len(lines):
        lines[idx + 1 : idx + 1] = ["", BOARD_HEADER, BOARD_SEP, row, ""]
        return "\n".join(lines)
    k = j
    while k < len(lines) and lines[k].strip().startswith("|"):
        k += 1
    lines.insert(k, row)
    return "\n".join(lines)


def add_task(
    proj: Path,
    task: str,
    who: str = "to assign",
    section: str = DEFAULT_SECTION,
    in_progress: bool = False,
    completed: bool = False,
    notes: str = "",
    page_slug: str = ROOT_SLUG,
) -> None:
    manifest = read_manifest(proj)
    node = find_node(manifest, page_slug)
    if node is None:
        raise LogbookError(f"No page with slug '{page_slug}' in this logbook.")
    path = logbook_root(proj) / node["file"]
    row = (
        f"| {_esc_cell(who)} | {'x' if in_progress else ''} | "
        f"{'x' if completed else ''} | {_esc_cell(task)} | {_esc_cell(notes)} |"
    )
    path.write_text(
        _insert_task_row(path.read_text(encoding="utf-8"), section, row),
        encoding="utf-8",
    )
    write_manifest(proj, manifest)


def _tree_lines(node: dict, depth: int = 0) -> list[str]:
    marker = "•" if depth else "▸"
    out = [f"{'  ' * depth}{marker} {node['title']}  ({node['slug']})"]
    for child in node.get("children", []):
        out.extend(_tree_lines(child, depth + 1))
    return out


def status_text(proj: Path) -> str:
    manifest = read_manifest(proj)
    metadata = read_metadata(proj)
    lines = [
        f"{manifest['emoji']}  {manifest['title']}",
        f"    dir     {logbook_root(proj)}",
        f"    updated {manifest['updated_at']}",
    ]
    if metadata.get("space_id"):
        lines.append(f"    space   {metadata['space_id']}")
    lines.append("")
    lines.append("  Pages:")
    for line in _tree_lines(manifest["root"]):
        lines.append("    " + line)
    return "\n".join(lines)


def flatten_markdown(proj: Path) -> str:
    manifest = read_manifest(proj)
    root = logbook_root(proj)
    out = [f"# {manifest['title']}", ""]

    def walk(node):
        text = (root / node["file"]).read_text(encoding="utf-8")
        out.append(re.sub(r"<!--.*?-->", "", text).strip())
        out.append("")
        for child in node.get("children", []):
            walk(child)

    walk(manifest["root"])
    return "\n".join(out)


def _readme(manifest: dict) -> str:
    emoji = manifest.get("emoji", "🧪")
    title = manifest["title"].replace('"', "'")
    return (
        f"---\ntitle: {title}\nemoji: {emoji}\ncolorFrom: yellow\ncolorTo: red\n"
        "sdk: static\npinned: false\ntags:\n - trackio\n - trackio-logbook\n"
        " - open-experiment\n---\n\n"
        f"# {manifest['title']}\n\nAn open experiment logbook, published with "
        "[Trackio](https://github.com/gradio-app/trackio).\n"
    )


def assemble_site(proj: Path, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    root = logbook_root(proj)
    for item in VIEWER_DIR.iterdir():
        if item.is_file():
            shutil.copy2(item, out_dir / item.name)
    shutil.copy2(root / "logbook.json", out_dir / "logbook.json")
    if (out_dir / "pages").exists():
        shutil.rmtree(out_dir / "pages")
    shutil.copytree(root / "pages", out_dir / "pages")
    if (root / "media").exists():
        if (out_dir / "media").exists():
            shutil.rmtree(out_dir / "media")
        shutil.copytree(root / "media", out_dir / "media")
    (out_dir / "logbook.md").write_text(flatten_markdown(proj), encoding="utf-8")
    (out_dir / "README.md").write_text(_readme(read_manifest(proj)), encoding="utf-8")
    return out_dir


def serve(port: int = 7861, open_browser: bool = True) -> None:
    import functools
    import http.server
    import socketserver
    import webbrowser

    proj = require_project_dir()
    site = proj / ".site"
    if site.exists():
        shutil.rmtree(site)
    assemble_site(proj, site)
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(site)
    )
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        url = f"http://localhost:{port}/"
        print(f"Serving logbook at {url}\nPress Ctrl+C to stop.")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


def _push(proj: Path, hf_token: str | None = None) -> str:
    import tempfile

    import huggingface_hub

    metadata = read_metadata(proj)
    space_id = metadata["space_id"]
    api = huggingface_hub.HfApi(token=hf_token)
    huggingface_hub.create_repo(
        space_id,
        repo_type="space",
        space_sdk="static",
        exist_ok=True,
        token=hf_token,
    )
    manifest = read_manifest(proj)
    with tempfile.TemporaryDirectory() as tmp:
        assemble_site(proj, Path(tmp))
        api.upload_folder(
            repo_id=space_id,
            repo_type="space",
            folder_path=tmp,
            commit_message=f"Update logbook: {manifest['title']}",
        )
    return f"https://huggingface.co/spaces/{space_id}"


def publish(space_id: str | None = None, hf_token: str | None = None) -> str:
    proj = require_project_dir()
    metadata = read_metadata(proj)
    space_id = space_id or metadata.get("space_id")
    if not space_id:
        raise LogbookError(
            "No Space id. Provide one: trackio logbook publish <username/space>"
        )
    metadata["space_id"] = space_id
    metadata["autosync"] = True
    write_metadata(proj, metadata)
    return _push(proj, hf_token=hf_token)


def is_autosync(proj: Path) -> bool:
    metadata = read_metadata(proj)
    return bool(metadata.get("autosync") and metadata.get("space_id"))


def trigger_autosync(proj: Path) -> None:
    import subprocess
    import sys

    if not is_autosync(proj):
        return
    (proj / ".sync_pending").write_text("1", encoding="utf-8")
    try:
        log = open(proj / ".sync.log", "a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, "-m", "trackio.cli", "logbook", "_sync"],
            cwd=str(proj.parent),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception:
        pass


def sync_worker(debounce: float = 2.5) -> None:
    import fcntl
    import time

    proj = find_project_dir()
    if proj is None:
        return
    lock = open(proj / ".sync_lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    try:
        pending = proj / ".sync_pending"
        while pending.exists():
            pending.unlink()
            time.sleep(debounce)
            try:
                _push(proj)
            except Exception:
                pass
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        finally:
            lock.close()
