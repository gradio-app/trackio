import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

import trackio

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

_print_lock = threading.Lock()


def _progress(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


SPACE_HEAVY_KEYWORDS = (
    "deploy",
    "sync-static-space",
    "sync-gradio-space",
    "import-csv-to-spaces",
    "hf-jobs",
    "convert-gradio-to-static",
)

EXTRA_DEPS_KEYWORDS = (
    "transformers",
    "audio-synthesis",
    "fractal-evolution",
)

REQUIRES_SECRET_ENV_KEYWORDS = ("slack-webhook",)

BENIGN_CONSOLE_ERROR_SNIPPETS = (
    "favicon.ico",
    "Failed to load resource: the server responded with a status of 404",
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

TRACKIO_LIB_FRAME = re.compile(
    r'File "[^"]*(?:[/\\]trackio[/\\]trackio[/\\]|site-packages[/\\]trackio[/\\])',
    re.IGNORECASE,
)


@dataclass
class TrackioIssue:
    kind: str
    detail: str
    example: str | None = None
    artifact_path: str | None = None


@dataclass
class ValidationResult:
    example_path: Path
    trackio_dir: Path
    touched_projects: list[str]
    run_stdout_path: Path
    run_stderr_path: Path
    trackio_issues: list[TrackioIssue] = field(default_factory=list)


@dataclass
class ExampleOutcome:
    ok: bool
    result: ValidationResult | None
    issues: list[TrackioIssue]
    error_message: str | None = None


def apply_trackio_dir(path: Path) -> None:
    import trackio.bucket_storage as bucket_storage
    import trackio.sqlite_storage as sqlite_storage
    import trackio.utils as utils

    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    utils.TRACKIO_DIR = path
    utils.MEDIA_DIR = path / "media"
    sqlite_storage.TRACKIO_DIR = path
    sqlite_storage.MEDIA_DIR = path / "media"
    bucket_storage.TRACKIO_DIR = path
    bucket_storage.MEDIA_DIR = path / "media"


def scan_logs_for_trackio_issues(
    stdout: str, stderr: str, example_name: str, stdout_path: Path, stderr_path: Path
) -> list[TrackioIssue]:
    issues: list[TrackioIssue] = []
    combined = f"{stdout}\n{stderr}"
    if "Traceback (most recent call last):" in combined and TRACKIO_LIB_FRAME.search(
        combined
    ):
        issues.append(
            TrackioIssue(
                kind="python_traceback",
                detail="Traceback with frames under the trackio package appears in output",
                example=example_name,
                artifact_path=str(stderr_path if stderr.strip() else stdout_path),
            )
        )
    for line in combined.splitlines():
        plain = ANSI_ESCAPE.sub("", line)
        lower = plain.lower()
        if re.search(r"\[trackio\s+(info|warn|error)\]", plain, re.IGNORECASE):
            continue
        if "trackio" not in lower and "/trackio/" not in plain.lower():
            continue
        if any(
            w in lower
            for w in (
                "error",
                "exception",
                "traceback",
                "failed",
                "fatal",
            )
        ):
            issues.append(
                TrackioIssue(
                    kind="log_line",
                    detail=line.strip()[:500],
                    example=example_name,
                    artifact_path=str(stderr_path if stderr.strip() else stdout_path),
                )
            )
    return issues


def _run_command(
    cmd: list[str], env: dict[str, str], timeout_s: int, cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        env=env,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )


def _run_trackio_json(
    args: list[str], env: dict[str, str], cwd: Path, timeout_s: int = 90
) -> object:
    result = _run_command(
        ["trackio", *args, "--json"], env=env, timeout_s=timeout_s, cwd=cwd
    )
    if result.returncode != 0:
        raise RuntimeError(f"Trackio CLI failed: {' '.join(args)}\n{result.stderr}")
    return json.loads(result.stdout)


def _normalize_list_response(value: object, key: str) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict) and isinstance(value.get(key), list):
        return [str(item) for item in value[key]]
    return []


def _example_candidates(
    examples_dir: Path,
    include_spaces: bool,
    include_extra_deps: bool,
    include_secret_env: bool,
) -> list[Path]:
    paths = sorted(examples_dir.glob("*.py"))
    if include_spaces:
        return paths
    filtered: list[Path] = []
    for path in paths:
        name = path.name.lower()
        if any(keyword in name for keyword in SPACE_HEAVY_KEYWORDS):
            continue
        if not include_extra_deps and any(
            keyword in name for keyword in EXTRA_DEPS_KEYWORDS
        ):
            continue
        if not include_secret_env and any(
            keyword in name for keyword in REQUIRES_SECRET_ENV_KEYWORDS
        ):
            continue
        filtered.append(path)
    return filtered


def _ensure_serializable_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in name)


def run_example_and_collect_projects(
    example_path: Path,
    env: dict[str, str],
    repo_root: Path,
    trackio_dir: Path,
    timeout_s: int,
    artifacts_dir: Path,
    space: str | None,
) -> ExampleOutcome:
    env = {**env}
    env.setdefault("PYTHONUNBUFFERED", "1")
    list_args = ["list", "projects"]
    if space:
        list_args.extend(["--space", space])
    before_projects_raw = _run_trackio_json(list_args, env=env, cwd=repo_root)
    before_projects = set(_normalize_list_response(before_projects_raw, "projects"))
    before_runs_by_project: dict[str, set[str]] = {}
    for project in before_projects:
        runs_args = ["list", "runs", "--project", project]
        if space:
            runs_args.extend(["--space", space])
        runs = _run_trackio_json(runs_args, env=env, cwd=repo_root)
        before_runs_by_project[project] = set(_normalize_list_response(runs, "runs"))

    try:
        result = _run_command(
            [sys.executable, str(example_path)],
            env=env,
            timeout_s=timeout_s,
            cwd=example_path.parent,
        )
    except subprocess.TimeoutExpired as e:
        return ExampleOutcome(
            ok=False,
            result=None,
            issues=[
                TrackioIssue(
                    kind="example_timeout",
                    detail=str(e),
                    example=example_path.name,
                )
            ],
            error_message=str(e),
        )

    run_id = _ensure_serializable_name(example_path.stem)
    stdout_path = artifacts_dir / f"{run_id}.stdout.log"
    stderr_path = artifacts_dir / f"{run_id}.stderr.log"
    stdout_path.write_text(result.stdout)
    stderr_path.write_text(result.stderr)
    scanned = scan_logs_for_trackio_issues(
        result.stdout, result.stderr, example_path.name, stdout_path, stderr_path
    )

    if result.returncode != 0:
        scanned.append(
            TrackioIssue(
                kind="example_nonzero_exit",
                detail=f"exit code {result.returncode}",
                example=example_path.name,
                artifact_path=str(stderr_path),
            )
        )
        return ExampleOutcome(
            ok=False,
            result=None,
            issues=scanned,
            error_message=(
                f"Example failed: {example_path.name}\n"
                f"stdout: {stdout_path}\n"
                f"stderr: {stderr_path}"
            ),
        )

    after_projects_raw = _run_trackio_json(list_args, env=env, cwd=repo_root)
    after_projects = set(_normalize_list_response(after_projects_raw, "projects"))
    new_projects = after_projects - before_projects
    touched_projects = set(new_projects)

    for project in sorted(after_projects & before_projects):
        runs_args = ["list", "runs", "--project", project]
        if space:
            runs_args.extend(["--space", space])
        after_runs = _run_trackio_json(runs_args, env=env, cwd=repo_root)
        after_runs_set = set(_normalize_list_response(after_runs, "runs"))
        before_runs_set = before_runs_by_project.get(project, set())
        if after_runs_set - before_runs_set:
            touched_projects.add(project)

    touched_projects_sorted = sorted(touched_projects)
    if not touched_projects_sorted:
        msg = (
            f"No new Trackio run/project detected from {example_path.name}. "
            "This validator expects each sampled example to write Trackio data."
        )
        scanned.append(
            TrackioIssue(
                kind="no_trackio_data",
                detail=msg,
                example=example_path.name,
                artifact_path=str(stdout_path),
            )
        )
        return ExampleOutcome(
            ok=False,
            result=None,
            issues=scanned,
            error_message=msg,
        )

    return ExampleOutcome(
        ok=True,
        result=ValidationResult(
            example_path=example_path,
            trackio_dir=trackio_dir,
            touched_projects=touched_projects_sorted,
            run_stdout_path=stdout_path,
            run_stderr_path=stderr_path,
            trackio_issues=scanned,
        ),
        issues=scanned,
    )


def validate_cli_data(
    projects: list[str],
    env: dict[str, str],
    repo_root: Path,
    space: str | None,
) -> None:
    for project in projects:
        runs_args = ["list", "runs", "--project", project]
        if space:
            runs_args.extend(["--space", space])
        runs_response = _run_trackio_json(runs_args, env=env, cwd=repo_root)
        runs = _normalize_list_response(runs_response, "runs")
        if not runs:
            raise RuntimeError(f"Project has no runs according to CLI: {project}")

        for run in runs:
            metrics_args = ["list", "metrics", "--project", project, "--run", run]
            run_args = ["get", "run", "--project", project, "--run", run]
            if space:
                metrics_args.extend(["--space", space])
                run_args.extend(["--space", space])

            metrics_response = _run_trackio_json(metrics_args, env=env, cwd=repo_root)
            metrics = _normalize_list_response(metrics_response, "metrics")
            run_summary = _run_trackio_json(run_args, env=env, cwd=repo_root)

            if not isinstance(run_summary, dict):
                raise RuntimeError(
                    f"Unexpected CLI run summary format for {project}/{run}: {run_summary}"
                )
            if not metrics:
                raise RuntimeError(
                    f"Run has no metrics according to CLI: {project}/{run} ({metrics_response})"
                )


def validate_ui(
    results: list[ValidationResult], screenshots_dir: Path, browser_timeout_ms: int
) -> list[TrackioIssue]:
    ui_issues: list[TrackioIssue] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for vr in results:
                apply_trackio_dir(vr.trackio_dir)
                for project in vr.touched_projects:
                    app = None
                    page = None
                    try:
                        app, _, _, full_url = trackio.show(
                            project=project, block_thread=False, open_browser=False
                        )
                    except Exception as e:
                        ui_issues.append(
                            TrackioIssue(
                                kind="ui_launch",
                                detail=repr(e),
                                example=vr.example_path.name,
                            )
                        )
                        continue
                    raw_console_errors: list[str] = []
                    page_errors: list[str] = []
                    try:
                        page = browser.new_page()
                        page.set_default_timeout(browser_timeout_ms)
                        page.on(
                            "console",
                            lambda msg: (
                                raw_console_errors.append(msg.text)
                                if msg.type == "error"
                                else None
                            ),
                        )
                        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

                        page.goto(full_url)
                        page.wait_for_load_state("networkidle")

                        page.get_by_role("button", name="Runs", exact=True).click()
                        page.wait_for_load_state("networkidle")

                        checkboxes = page.locator(
                            ".checkbox-item input[type='checkbox']"
                        )
                        count = checkboxes.count()
                        if count > 0:
                            checkboxes.first.uncheck()
                            page.wait_for_timeout(300)
                            checkboxes.first.check()
                            page.wait_for_timeout(300)

                        latest_toggle = page.locator(
                            ".latest-toggle input[type='checkbox']"
                        )
                        if latest_toggle.count() > 0:
                            latest_toggle.first.check()
                            page.wait_for_timeout(300)

                        page.get_by_role("button", name="Metrics", exact=True).click()
                        page.wait_for_load_state("networkidle")
                        page.get_by_role(
                            "button", name="Media & Tables", exact=True
                        ).click()
                        page.wait_for_load_state("networkidle")
                        page.get_by_role(
                            "button", name="System Metrics", exact=True
                        ).click()
                        page.wait_for_load_state("networkidle")
                        page.get_by_role(
                            "button", name="Alerts & Reports", exact=True
                        ).click()
                        page.wait_for_load_state("networkidle")
                        page.get_by_role("button", name="Settings", exact=True).click()
                        page.wait_for_load_state("networkidle")

                        shot_name = (
                            f"{_ensure_serializable_name(vr.example_path.stem)}__"
                            f"{_ensure_serializable_name(project)}.png"
                        )
                        screenshot_path = screenshots_dir / shot_name
                        page.screenshot(path=str(screenshot_path), full_page=True)

                        console_errors = [
                            error
                            for error in raw_console_errors
                            if not any(
                                snippet in error
                                for snippet in BENIGN_CONSOLE_ERROR_SNIPPETS
                            )
                        ]
                        if console_errors:
                            msg = (
                                f"Browser console errors in project {project}: "
                                f"{console_errors}"
                            )
                            ui_issues.append(
                                TrackioIssue(
                                    kind="ui_console",
                                    detail=msg,
                                    example=vr.example_path.name,
                                    artifact_path=str(screenshot_path),
                                )
                            )
                        elif page_errors:
                            msg = f"Browser page errors in project {project}: {page_errors}"
                            ui_issues.append(
                                TrackioIssue(
                                    kind="ui_page",
                                    detail=msg,
                                    example=vr.example_path.name,
                                    artifact_path=str(screenshot_path),
                                )
                            )
                    except Exception as e:
                        ui_issues.append(
                            TrackioIssue(
                                kind="ui_exception",
                                detail=repr(e),
                                example=vr.example_path.name,
                            )
                        )
                    finally:
                        if page is not None:
                            page.close()
                        if app is not None:
                            app.close()
        finally:
            browser.close()
    return ui_issues


def validate_cli_for_results(
    results: list[ValidationResult],
    repo_root: Path,
    space: str | None,
) -> list[TrackioIssue]:
    issues: list[TrackioIssue] = []
    for r in results:
        env = dict(os.environ)
        env["TRACKIO_DIR"] = str(r.trackio_dir)
        try:
            validate_cli_data(r.touched_projects, env, repo_root, space)
        except Exception as e:
            issues.append(
                TrackioIssue(
                    kind="cli",
                    detail=repr(e),
                    example=r.example_path.name,
                )
            )
    return issues


def execute_examples(
    selected: list[Path],
    *,
    jobs: int,
    repo_root: Path,
    artifacts_root: Path,
    example_timeout: int,
    space: str | None,
) -> list[ExampleOutcome]:
    logs_root = artifacts_root / "logs"
    logs_root.mkdir(exist_ok=True)
    outcomes: list[ExampleOutcome] = []

    if jobs <= 1:
        shared = artifacts_root / "trackio-data"
        shared.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["TRACKIO_DIR"] = str(shared)
        env.setdefault("PYTHONUNBUFFERED", "1")
        n = len(selected)
        for idx, example in enumerate(selected):
            _progress(
                f"  Example [{idx + 1}/{n}]: starting subprocess {example.name} ..."
            )
            sublog = logs_root / f"{idx:02d}_{_ensure_serializable_name(example.stem)}"
            sublog.mkdir(parents=True, exist_ok=True)
            out = run_example_and_collect_projects(
                example_path=example,
                env=env,
                repo_root=repo_root,
                trackio_dir=shared,
                timeout_s=example_timeout,
                artifacts_dir=sublog,
                space=space,
            )
            outcomes.append(out)
            _progress(
                f"  Example [{idx + 1}/{n}]: finished {example.name} (ok={out.ok})"
            )
        return outcomes

    sandboxes_root = artifacts_root / "sandboxes"
    sandboxes_root.mkdir(exist_ok=True)

    max_workers = min(jobs, len(selected))
    _progress(
        f"Running {len(selected)} example subprocess(es) in parallel "
        f"(up to {max_workers} at a time; each may run for minutes) ..."
    )

    def run_idx(idx: int, example: Path) -> ExampleOutcome:
        _progress(f"  Subprocess started: [{idx}] {example.name}")
        try:
            trackio_dir = (
                sandboxes_root / f"{idx:02d}_{_ensure_serializable_name(example.stem)}"
            )
            trackio_dir.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env["TRACKIO_DIR"] = str(trackio_dir)
            env.setdefault("PYTHONUNBUFFERED", "1")
            sublog = logs_root / f"{idx:02d}_{_ensure_serializable_name(example.stem)}"
            sublog.mkdir(parents=True, exist_ok=True)
            return run_example_and_collect_projects(
                example_path=example,
                env=env,
                repo_root=repo_root,
                trackio_dir=trackio_dir,
                timeout_s=example_timeout,
                artifacts_dir=sublog,
                space=space,
            )
        except Exception as e:
            return ExampleOutcome(
                ok=False,
                result=None,
                issues=[
                    TrackioIssue(
                        kind="worker_exception",
                        detail=repr(e),
                        example=example.name,
                    )
                ],
                error_message=repr(e),
            )

    slot_outcomes: list[ExampleOutcome | None] = [None] * len(selected)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run_idx, i, ex): i for i, ex in enumerate(selected)}
        for fut in as_completed(futures):
            slot = futures[fut]
            done = fut.result()
            slot_outcomes[slot] = done
            _progress(
                f"  Subprocess finished: [{slot}] {selected[slot].name} (ok={done.ok})"
            )
    return [o for o in slot_outcomes if o is not None]


def dedupe_issues(issues: list[TrackioIssue]) -> list[TrackioIssue]:
    seen: set[tuple[str | None, str, str | None]] = set()
    out: list[TrackioIssue] = []
    for issue in issues:
        key = (issue.kind, issue.detail[:300], issue.example)
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


def print_trackio_library_report(issues: list[TrackioIssue]) -> None:
    _progress("\n=== Trackio library health report ===")
    _progress(
        "Focus: signals that suggest Trackio (library, CLI, or dashboard) regressions, "
        "not whether a particular example script is perfect."
    )
    if not issues:
        _progress("No Trackio-related problems were collected in this run.")
        return
    _progress(f"Collected {len(issues)} item(s) to review:\n")
    for i, issue in enumerate(issues, 1):
        ex = f" [{issue.example}]" if issue.example else ""
        art = f"\n  log: {issue.artifact_path}" if issue.artifact_path else ""
        _progress(f"{i}. ({issue.kind}){ex}\n  {issue.detail}{art}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise Trackio via random examples: subprocess runs, CLI queries, and UI. "
            "Designed to catch Trackio library regressions, not to certify every example script."
        )
    )
    parser.add_argument(
        "--count", type=int, default=3, help="Number of random examples to run."
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="Random seed for reproducibility."
    )
    parser.add_argument(
        "--include-space-examples",
        action="store_true",
        help="Include examples likely to require Spaces credentials/network.",
    )
    parser.add_argument(
        "--include-extra-deps-examples",
        action="store_true",
        help=(
            "Include examples that need optional third-party packages "
            "(e.g. transformers, datasets). Excluded by default so local health checks "
            "do not fail on missing optional deps."
        ),
    )
    parser.add_argument(
        "--include-secret-env-examples",
        action="store_true",
        help=(
            "Include examples that require secret env vars (e.g. SLACK_WEBHOOK_URL). "
            "Excluded by default."
        ),
    )
    parser.add_argument(
        "--space",
        default=None,
        help="HF Space ID or URL for querying remote data through Trackio CLI.",
    )
    parser.add_argument(
        "--example-timeout",
        type=int,
        default=240,
        help="Per-example timeout in seconds.",
    )
    parser.add_argument(
        "--browser-timeout-ms",
        type=int,
        default=12000,
        help="Playwright timeout in milliseconds.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=3,
        help="Run example scripts in parallel (each with its own TRACKIO_DIR). Default is 3.",
    )
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Run remaining examples after a failure; CLI/UI only run for successful examples.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    examples_dir = repo_root / "examples"
    candidates = _example_candidates(
        examples_dir,
        args.include_space_examples,
        args.include_extra_deps_examples,
        args.include_secret_env_examples,
    )
    if not candidates:
        raise RuntimeError("No example candidates available with current filters.")

    sample_count = min(args.count, len(candidates))
    if sample_count <= 0:
        raise RuntimeError("--count must be at least 1.")

    rng = random.Random(args.seed)
    selected = rng.sample(candidates, sample_count)

    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifacts_root = (
        Path(tempfile.gettempdir()) / f"trackio-example-validation-{run_stamp}"
    )
    artifacts_root.mkdir(parents=True, exist_ok=True)
    screenshots_dir = artifacts_root / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    _progress(f"Artifacts: {artifacts_root}")
    _progress(
        f"Execution: {'parallel' if args.jobs > 1 else 'sequential'} (--jobs {args.jobs})"
    )
    _progress(f"Selected examples ({sample_count}):")
    for example in selected:
        _progress(f"  - {example.name}")

    _progress(
        "\nRunning example scripts (no further output until a subprocess finishes; "
        "slow scripts with training loops can take several minutes) ..."
    )
    start = time.time()
    outcomes = execute_examples(
        selected,
        jobs=args.jobs,
        repo_root=repo_root,
        artifacts_root=artifacts_root,
        example_timeout=args.example_timeout,
        space=args.space,
    )

    collected_issues: list[TrackioIssue] = []
    for o in outcomes:
        collected_issues.extend(o.issues)

    failed = [o for o in outcomes if not o.ok]
    ok_results = [o.result for o in outcomes if o.ok and o.result]

    if failed:
        for o in failed:
            _progress(f"\nExample run failed: {o.error_message or 'unknown'}")
        if not args.continue_on_failure:
            collected_issues = dedupe_issues(collected_issues)
            print_trackio_library_report(collected_issues)
            summary = {
                "examples": [str(p.relative_to(repo_root)) for p in selected],
                "ok": False,
                "failed_examples": len(failed),
                "trackio_issues": [
                    {
                        "kind": i.kind,
                        "detail": i.detail,
                        "example": i.example,
                        "artifact_path": i.artifact_path,
                    }
                    for i in collected_issues
                ],
                "artifacts_root": str(artifacts_root),
                "duration_seconds": round(time.time() - start, 2),
                "space": args.space,
            }
            (artifacts_root / "summary.json").write_text(json.dumps(summary, indent=2))
            return 1

    if not ok_results:
        collected_issues = dedupe_issues(collected_issues)
        print_trackio_library_report(collected_issues)
        return 1

    _progress("\nValidating with Trackio CLI ...")
    cli_issues = validate_cli_for_results(ok_results, repo_root, args.space)
    collected_issues.extend(cli_issues)
    if cli_issues:
        _progress(
            f"  CLI reported {len(cli_issues)} problem(s); see Trackio library report."
        )
    else:
        _progress("  CLI checks passed")

    _progress(
        "\nValidating UI with Playwright (Chromium + local dashboard; often 30–120s) ..."
    )
    ui_issues = validate_ui(
        ok_results,
        screenshots_dir=screenshots_dir,
        browser_timeout_ms=args.browser_timeout_ms,
    )
    collected_issues.extend(ui_issues)
    if ui_issues:
        _progress(
            f"  UI reported {len(ui_issues)} problem(s); see Trackio library report."
        )
    else:
        _progress("  UI checks passed")

    collected_issues = dedupe_issues(collected_issues)
    print_trackio_library_report(collected_issues)

    summary = {
        "examples": [str(r.example_path.relative_to(repo_root)) for r in ok_results],
        "projects": sorted({p for r in ok_results for p in r.touched_projects}),
        "artifacts_root": str(artifacts_root),
        "duration_seconds": round(time.time() - start, 2),
        "space": args.space,
        "jobs": args.jobs,
        "ok": not collected_issues and not failed,
        "failed_example_runs": len(failed),
        "trackio_issues": [
            {
                "kind": i.kind,
                "detail": i.detail,
                "example": i.example,
                "artifact_path": i.artifact_path,
            }
            for i in collected_issues
        ],
    }
    summary_path = artifacts_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    _progress(f"\nSummary written to: {summary_path}")
    _progress(f"Screenshots: {screenshots_dir}")

    if failed or collected_issues:
        return 1
    _progress("\nTrackio library check completed with no collected issues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
