import json
import os
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub.constants import HF_HOME

TRACKIO_USER_HOME = Path(HF_HOME) / "trackio"
TRACKIO_CONFIG_PATH = TRACKIO_USER_HOME / "config.json"
BUNDLED_FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"
STARTER_FRONTEND_DIR = Path(__file__).parent / "frontend_templates" / "starter"


@dataclass(frozen=True)
class ResolvedFrontend:
    path: Path
    source: str
    is_custom: bool
    used_fallback: bool = False
    requested_path: Path | None = None


def _normalize_frontend_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def is_valid_frontend_dir(path: str | Path | None) -> bool:
    if path is None:
        return False
    frontend_dir = _normalize_frontend_path(path)
    return frontend_dir.is_dir() and (frontend_dir / "index.html").is_file()


def load_trackio_config() -> dict:
    if not TRACKIO_CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(TRACKIO_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_trackio_config(config: dict) -> None:
    TRACKIO_USER_HOME.mkdir(parents=True, exist_ok=True)
    TRACKIO_CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")


def get_persisted_frontend_dir() -> Path | None:
    frontend_dir = load_trackio_config().get("frontend_dir")
    if not frontend_dir:
        return None
    return _normalize_frontend_path(frontend_dir)


def set_persisted_frontend_dir(path: str | Path) -> Path:
    frontend_dir = _normalize_frontend_path(path)
    if not is_valid_frontend_dir(frontend_dir):
        raise ValueError(
            f"Invalid frontend directory: {frontend_dir}. Expected a directory containing index.html."
        )
    config = load_trackio_config()
    config["frontend_dir"] = str(frontend_dir)
    save_trackio_config(config)
    return frontend_dir


def unset_persisted_frontend_dir() -> bool:
    config = load_trackio_config()
    if "frontend_dir" not in config:
        return False
    del config["frontend_dir"]
    if config:
        save_trackio_config(config)
    elif TRACKIO_CONFIG_PATH.exists():
        TRACKIO_CONFIG_PATH.unlink()
    return True


def _configured_frontend_candidates(
    frontend_dir: str | Path | None,
) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    if frontend_dir is not None:
        candidates.append(("argument", _normalize_frontend_path(frontend_dir)))
    env_dir = os.environ.get("TRACKIO_FRONTEND_DIR")
    if env_dir:
        candidates.append(("env", _normalize_frontend_path(env_dir)))
    persisted_dir = get_persisted_frontend_dir()
    if persisted_dir is not None:
        candidates.append(("config", persisted_dir))
    return candidates


def _announce_config_frontend(frontend_dir: Path) -> None:
    print(
        f"* Using Trackio custom frontend from config: {frontend_dir}\n"
        "  Reset with `trackio config unset frontend`."
    )


def resolve_frontend_dir(
    frontend_dir: str | Path | None = None,
    *,
    announce: bool = False,
) -> ResolvedFrontend:
    for source, candidate in _configured_frontend_candidates(frontend_dir):
        if is_valid_frontend_dir(candidate):
            if source == "config" and announce:
                _announce_config_frontend(candidate)
            return ResolvedFrontend(
                path=candidate,
                source=source,
                is_custom=True,
            )
        print(
            f"* Trackio frontend from {source} is invalid: {candidate}. "
            f"Falling back to starter template at {STARTER_FRONTEND_DIR}."
        )
        return ResolvedFrontend(
            path=STARTER_FRONTEND_DIR,
            source="starter",
            is_custom=True,
            used_fallback=True,
            requested_path=candidate,
        )

    if is_valid_frontend_dir(BUNDLED_FRONTEND_DIR):
        return ResolvedFrontend(
            path=BUNDLED_FRONTEND_DIR,
            source="bundled",
            is_custom=False,
        )

    return ResolvedFrontend(
        path=STARTER_FRONTEND_DIR,
        source="starter",
        is_custom=True,
        used_fallback=True,
    )
