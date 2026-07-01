from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from trackio.utils import TRACKIO_DIR

LOGBOOKS_DIR = TRACKIO_DIR / "logbooks"
ACTIVE_POINTER = LOGBOOKS_DIR / ".active"
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


def logbook_dir(slug: str) -> Path:
    return LOGBOOKS_DIR / slug


def _manifest_path(slug: str) -> Path:
    return logbook_dir(slug) / "logbook.json"


def read_manifest(slug: str) -> dict:
    path = _manifest_path(slug)
    if not path.exists():
        raise LogbookError(f"No logbook named '{slug}' found at {logbook_dir(slug)}.")
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(slug: str, manifest: dict) -> None:
    manifest["updated_at"] = _now_iso()
    _manifest_path(slug).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def set_active(slug: str) -> None:
    LOGBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_POINTER.write_text(slug, encoding="utf-8")


def get_active() -> str | None:
    if not ACTIVE_POINTER.exists():
        return None
    slug = ACTIVE_POINTER.read_text(encoding="utf-8").strip()
    return slug or None


def clear_active() -> None:
    if ACTIVE_POINTER.exists():
        ACTIVE_POINTER.unlink()


def require_active() -> str:
    slug = get_active()
    if slug is None:
        raise LogbookError(
            "No active logbook. Start one with: trackio logbook open [SPACE_ID]"
        )
    if not _manifest_path(slug).exists():
        raise LogbookError(
            f"Active logbook '{slug}' no longer exists. Start a new one with: "
            "trackio logbook open"
        )
    return slug


def list_logbooks() -> list[dict]:
    if not LOGBOOKS_DIR.exists():
        return []
    books = []
    for child in sorted(LOGBOOKS_DIR.iterdir()):
        manifest = child / "logbook.json"
        if manifest.is_file():
            books.append(json.loads(manifest.read_text(encoding="utf-8")))
    return books


def _unique_dir_slug(base: str) -> str:
    slug = base
    n = 2
    while logbook_dir(slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


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
    slug: str | None = None,
    space_id: str | None = None,
    emoji: str = "🧪",
) -> str:
    LOGBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    base = _slugify(slug or title)
    slug = _unique_dir_slug(base)
    book = logbook_dir(slug)
    (book / "pages").mkdir(parents=True)
    now = _now_iso()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "slug": slug,
        "title": title,
        "emoji": emoji,
        "space_id": space_id,
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
    (book / "pages" / "index.md").write_text(
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
    write_manifest(slug, manifest)
    return slug


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
    logbook_slug: str,
    task: str,
    who: str = "to assign",
    section: str = DEFAULT_SECTION,
    in_progress: bool = False,
    completed: bool = False,
    notes: str = "",
    page_slug: str = ROOT_SLUG,
) -> None:
    manifest = read_manifest(logbook_slug)
    node = find_node(manifest, page_slug)
    if node is None:
        raise LogbookError(f"No page with slug '{page_slug}' in this logbook.")
    path = logbook_dir(logbook_slug) / node["file"]
    row = (
        f"| {_esc_cell(who)} | {'x' if in_progress else ''} | "
        f"{'x' if completed else ''} | {_esc_cell(task)} | {_esc_cell(notes)} |"
    )
    path.write_text(
        _insert_task_row(path.read_text(encoding="utf-8"), section, row),
        encoding="utf-8",
    )
    write_manifest(logbook_slug, manifest)


def add_page(
    logbook_slug: str,
    title: str,
    parent_slug: str = ROOT_SLUG,
    slug: str | None = None,
) -> str:
    manifest = read_manifest(logbook_slug)
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
    abs_path = logbook_dir(logbook_slug) / rel
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
    write_manifest(logbook_slug, manifest)
    return page_slug


def _resolve_artifact(name: str) -> str:
    try:
        from trackio.sqlite_storage import SQLiteStorage

        if ":" in name:
            project_and_name = name.split(":")[0]
        else:
            project_and_name = name
        if "/" in project_and_name:
            project, art_name = project_and_name.split("/", 1)
        else:
            return f"**📦 Artifact** `{name}`"
        manifest = SQLiteStorage.get_artifact_manifest(project, art_name)
        size = sum(entry.get("size", 0) for entry in manifest)
        gb = size / 1e9
        size_str = f"{gb:.2f} GB" if gb >= 0.01 else f"{size / 1e6:.1f} MB"
        return f"**📦 Artifact** `{name}` · {len(manifest)} files · {size_str}"
    except Exception:
        return f"**📦 Artifact** `{name}`"


def add_note(
    logbook_slug: str,
    body: str,
    title: str | None = None,
    page_slug: str = ROOT_SLUG,
    links: list[str] | None = None,
    artifacts: list[str] | None = None,
) -> None:
    manifest = read_manifest(logbook_slug)
    node = find_node(manifest, page_slug)
    if node is None:
        raise LogbookError(f"No page with slug '{page_slug}' in this logbook.")
    page_path = logbook_dir(logbook_slug) / node["file"]
    now = _now_iso()
    lines = ["", "---", ""]
    heading = title.strip() if title else "Note"
    lines.append(f"### {heading}")
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
    write_manifest(logbook_slug, manifest)


def _tree_lines(node: dict, depth: int = 0) -> list[str]:
    marker = "•" if depth else "▸"
    out = [f"{'  ' * depth}{marker} {node['title']}  ({node['slug']})"]
    for child in node.get("children", []):
        out.extend(_tree_lines(child, depth + 1))
    return out


def status_text(logbook_slug: str) -> str:
    manifest = read_manifest(logbook_slug)
    lines = [
        f"{manifest['emoji']}  {manifest['title']}  ({manifest['slug']})",
        f"    updated {manifest['updated_at']}",
    ]
    if manifest.get("space_id"):
        lines.append(f"    space   {manifest['space_id']}")
    lines.append("")
    lines.append("  Pages:")
    for line in _tree_lines(manifest["root"]):
        lines.append("    " + line)
    return "\n".join(lines)


def flatten_markdown(logbook_slug: str) -> str:
    manifest = read_manifest(logbook_slug)
    book = logbook_dir(logbook_slug)
    out = [f"# {manifest['title']}", ""]

    def walk(node, depth):
        text = (book / node["file"]).read_text(encoding="utf-8")
        text = re.sub(r"<!--.*?-->", "", text)
        out.append(text.strip())
        out.append("")
        for child in node.get("children", []):
            walk(child, depth + 1)

    walk(manifest["root"], 0)
    return "\n".join(out)


def _readme(manifest: dict) -> str:
    emoji = manifest.get("emoji", "🧪")
    title = manifest["title"].replace('"', "'")
    return (
        f"---\ntitle: {title}\nemoji: {emoji}\ncolorFrom: indigo\ncolorTo: purple\n"
        "sdk: static\npinned: false\ntags:\n - trackio\n - trackio-logbook\n"
        " - open-experiment\n---\n\n"
        f"# {manifest['title']}\n\nAn open experiment logbook, published with "
        "[Trackio](https://github.com/gradio-app/trackio).\n"
    )


def assemble_site(logbook_slug: str, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    book = logbook_dir(logbook_slug)
    for item in VIEWER_DIR.iterdir():
        if item.is_file():
            shutil.copy2(item, out_dir / item.name)
    shutil.copy2(book / "logbook.json", out_dir / "logbook.json")
    if (out_dir / "pages").exists():
        shutil.rmtree(out_dir / "pages")
    shutil.copytree(book / "pages", out_dir / "pages")
    if (book / "media").exists():
        if (out_dir / "media").exists():
            shutil.rmtree(out_dir / "media")
        shutil.copytree(book / "media", out_dir / "media")
    (out_dir / "logbook.md").write_text(
        flatten_markdown(logbook_slug), encoding="utf-8"
    )
    manifest = read_manifest(logbook_slug)
    (out_dir / "README.md").write_text(_readme(manifest), encoding="utf-8")
    return out_dir


def serve(logbook_slug: str, port: int = 7861, open_browser: bool = True) -> None:
    import functools
    import http.server
    import socketserver
    import webbrowser

    site = logbook_dir(logbook_slug) / ".site"
    if site.exists():
        shutil.rmtree(site)
    assemble_site(logbook_slug, site)
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(site)
    )
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        url = f"http://localhost:{port}/"
        print(f"Serving logbook '{logbook_slug}' at {url}\nPress Ctrl+C to stop.")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


def publish(
    logbook_slug: str,
    space_id: str | None = None,
    hf_token: str | None = None,
) -> str:
    import tempfile

    import huggingface_hub

    manifest = read_manifest(logbook_slug)
    space_id = space_id or manifest.get("space_id")
    if not space_id:
        raise LogbookError(
            "No Space id. Provide one: trackio logbook publish <username/space>"
        )
    manifest["space_id"] = space_id
    write_manifest(logbook_slug, manifest)

    api = huggingface_hub.HfApi(token=hf_token)
    huggingface_hub.create_repo(
        space_id,
        repo_type="space",
        space_sdk="static",
        exist_ok=True,
        token=hf_token,
    )
    with tempfile.TemporaryDirectory() as tmp:
        assemble_site(logbook_slug, Path(tmp))
        api.upload_folder(
            repo_id=space_id,
            repo_type="space",
            folder_path=tmp,
            commit_message=f"Publish logbook: {manifest['title']}",
        )
    return f"https://huggingface.co/spaces/{space_id}"
