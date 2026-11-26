"""Export a Trackio project as a Lean 4 module so claims about it can be proven.

The generated module imports the `Trackio` prelude (shipped in
`trackio/lean/Trackio.lean`) and defines, for one project:

- `Run`, `Metric`, and `Key` enumerations whose constructors are sanitized run,
  metric, and config-key names,
- `series : Run → Metric → Series` with every finite numeric value logged,
- `config : Run → Key → Option Value` with flattened scalar config values,
- `digest`, a SHA-256 over the exported data so a reader can re-export and
  confirm the module matches the logs.

Numbers become exact rationals. By default each float becomes the shortest
decimal that round-trips to the same float64 (what Python's `repr` prints);
with `exact=True` it becomes the float64's exact binary value.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from trackio.sqlite_storage import SQLiteStorage

PRELUDE_PATH = Path(__file__).parent / "lean" / "Trackio.lean"

_LEAN_KEYWORDS = {
    "Prop",
    "Sort",
    "Type",
    "abbrev",
    "at",
    "attribute",
    "axiom",
    "break",
    "by",
    "calc",
    "catch",
    "class",
    "continue",
    "def",
    "deriving",
    "do",
    "else",
    "end",
    "example",
    "exists",
    "extends",
    "finally",
    "for",
    "forall",
    "from",
    "fun",
    "have",
    "if",
    "import",
    "in",
    "inductive",
    "instance",
    "lemma",
    "let",
    "local",
    "macro",
    "match",
    "mut",
    "mutual",
    "namespace",
    "noncomputable",
    "nofun",
    "nomatch",
    "obtain",
    "open",
    "partial",
    "private",
    "protected",
    "return",
    "section",
    "set_option",
    "show",
    "sorry",
    "structure",
    "suffices",
    "syntax",
    "then",
    "theorem",
    "this",
    "try",
    "universe",
    "unless",
    "unsafe",
    "variable",
    "where",
    "with",
}

_RESERVED_CONSTRUCTOR_NAMES = {
    "below",
    "binductionOn",
    "brecOn",
    "casesOn",
    "ctorIdx",
    "decEq",
    "ibelow",
    "mk",
    "name",
    "noConfusion",
    "noConfusionType",
    "ofNat",
    "rec",
    "recOn",
    "sizeOf_spec",
    "toCtorIdx",
}


@dataclass
class _ExportedRun:
    name: str
    ident: str
    series: dict[str, list[tuple[int, Fraction]]] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    code_files: dict[str, str] = field(default_factory=dict)


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _to_fraction(value: int | float, exact: bool) -> Fraction:
    if isinstance(value, int) or exact:
        return Fraction(value)
    return Fraction(repr(value))


def _lean_ident(name: str, used: set[str], prefix: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
    if not ident or ident[0].isdigit():
        ident = f"{prefix}_{ident}" if ident else prefix
    if ident in _LEAN_KEYWORDS or ident in _RESERVED_CONSTRUCTOR_NAMES:
        ident = f"{ident}_"
    candidate, suffix = ident, 2
    while candidate in used:
        candidate = f"{ident}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def module_name_for_project(project: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", project) if part]
    name = "".join(part[:1].upper() + part[1:] for part in parts)
    if not name or name[0].isdigit():
        name = f"Project{name}"
    return name


def _lean_string(value: str) -> str:
    out = []
    for char in value:
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif char == "\r":
            out.append("\\r")
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            out.append(f"\\x{ord(char):02x}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def _lean_q(value: Fraction) -> str:
    num, den = value.numerator, value.denominator
    num_text = f"({num})" if num < 0 else str(num)
    return f"q {num_text}" if den == 1 else f"q {num_text} {den}"


def _flatten_config(config: dict, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in config.items():
        key = str(key)
        if not prefix and key.startswith("_"):
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_config(value, path))
        elif isinstance(value, (bool, str)) or _is_finite_number(value):
            flat[path] = value
    return flat


def _config_value(value: Any, exact: bool) -> tuple[str, str]:
    if isinstance(value, bool):
        return "bool", "true" if value else "false"
    if isinstance(value, str):
        return "str", value
    fraction = _to_fraction(value, exact)
    return "num", f"{fraction.numerator}/{fraction.denominator}"


def _lean_value(value: Any, exact: bool) -> str:
    if isinstance(value, bool):
        return f".bool {'true' if value else 'false'}"
    if isinstance(value, str):
        return f".str {_lean_string(value)}"
    return f".num ({_lean_q(_to_fraction(value, exact))})"


def _collect_runs(
    project: str, metrics: list[str] | None, exact: bool
) -> tuple[list[_ExportedRun], int]:
    records = SQLiteStorage.get_run_records(project)
    if not records:
        raise ValueError(f"Project '{project}' has no runs to export.")
    configs = SQLiteStorage.get_all_run_configs(project)
    wanted = list(metrics) if metrics else None
    used_idents: set[str] = set()
    skipped = 0
    runs: list[_ExportedRun] = []
    for record in records:
        name = record["name"] or record["id"] or "run"
        run = _ExportedRun(name=name, ident=_lean_ident(name, used_idents, "r"))
        logs = SQLiteStorage.get_logs(project, run=record["name"], run_id=record["id"])
        for log in logs:
            step = log.get("step")
            for key, value in log.items():
                if key in ("step", "timestamp") or key.startswith("_"):
                    continue
                if wanted is not None and not any(
                    fnmatch.fnmatchcase(key, pattern) for pattern in wanted
                ):
                    continue
                if isinstance(value, float) and not math.isfinite(value):
                    skipped += 1
                    continue
                if not _is_finite_number(value) or step is None:
                    continue
                run.series.setdefault(key, []).append(
                    (int(step), _to_fraction(value, exact))
                )
        raw_config = configs.get(record["id"]) or configs.get(record["name"]) or {}
        run.config = _flatten_config(raw_config)
        code = raw_config.get("_Code") or {}
        job = raw_config.get("_Job") or {}
        for key, value in (
            ("codeSha256", code.get("sha256")),
            ("codePath", code.get("path")),
            ("hfJobId", job.get("id")),
        ):
            if isinstance(value, str):
                run.provenance[key] = value
        files = code.get("files") or {}
        if isinstance(files, dict):
            run.code_files = {
                str(k): v for k, v in sorted(files.items()) if isinstance(v, str)
            }
        runs.append(run)
    return runs, skipped


def _digest(project: str, runs: list[_ExportedRun], exact: bool) -> str:
    payload = {
        "project": project,
        "exact": exact,
        "runs": [
            {
                "name": run.name,
                "config": {
                    key: _config_value(value, exact)
                    for key, value in sorted(run.config.items())
                },
                "provenance": dict(sorted(run.provenance.items())),
                "code_files": run.code_files,
                "series": {
                    metric: [
                        [step, f"{value.numerator}/{value.denominator}"]
                        for step, value in points
                    ]
                    for metric, points in sorted(run.series.items())
                },
            }
            for run in runs
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _enum(name: str, idents: list[str], labels: list[str]) -> list[str]:
    lines = [f"inductive {name} where"]
    lines += [f"  | {ident}" for ident in idents]
    lines += ["  deriving DecidableEq, Repr", ""]
    lines.append(f"def {name}.name : {name} → String")
    lines += [
        f"  | .{ident} => {_lean_string(label)}" for ident, label in zip(idents, labels)
    ]
    lines.append("")
    return lines


def export_project_to_lean(
    project: str,
    metrics: list[str] | None = None,
    exact: bool = False,
    module_name: str | None = None,
) -> str:
    """Return the source of a Lean module holding `project`'s logged data."""
    runs, skipped = _collect_runs(project, metrics, exact)
    module = module_name or module_name_for_project(project)
    digest = _digest(project, runs, exact)

    metric_names = sorted({m for run in runs for m in run.series})
    key_names = sorted({k for run in runs for k in run.config})
    used: set[str] = set()
    metric_idents = {m: _lean_ident(m, used, "m") for m in metric_names}
    used = set()
    key_idents = {k: _lean_ident(k, used, "k") for k in key_names}

    number_mode = (
        "exact binary value of each float64"
        if exact
        else "shortest decimal that round-trips to each float64"
    )
    lines = [
        "import Trackio",
        "",
        "/-!",
        f"Generated by `trackio export --format lean` from project {_lean_string(project)}.",
        "Do not edit by hand: re-export and compare `digest` instead.",
        "",
        f"Runs: {len(runs)} · Metrics: {len(metric_names)} · Config keys: {len(key_names)}",
        f"Numbers: {number_mode}.",
        f"Non-finite values skipped: {skipped}.",
        "-/",
        "",
        f"namespace {module}",
        "open Trackio",
        "",
        f"def project : String := {_lean_string(project)}",
        f"def digest : String := {_lean_string(digest)}",
        "",
    ]
    lines += _enum("Run", [run.ident for run in runs], [run.name for run in runs])
    lines.append(
        "def runs : List Run := [" + ", ".join(f".{run.ident}" for run in runs) + "]"
    )
    lines.append("")

    if metric_names:
        lines += _enum("Metric", [metric_idents[m] for m in metric_names], metric_names)
        covered = 0
        series_cases = []
        for run in runs:
            for metric in metric_names:
                points = run.series.get(metric)
                if not points:
                    continue
                const = f"series_{run.ident}_{metric_idents[metric]}"
                body = ",\n    ".join(
                    f"({step}, {_lean_q(value)})" for step, value in points
                )
                lines += [f"def {const} : Series := [\n    {body}]", ""]
                series_cases.append(
                    f"  | .{run.ident}, .{metric_idents[metric]} => {const}"
                )
                covered += 1
        lines.append("def series : Run → Metric → Series")
        lines += series_cases
        if covered < len(runs) * len(metric_names):
            lines.append("  | _, _ => []")
        lines += [
            "",
            "def initial (r : Run) (m : Metric) : Option Q := (series r m).first?",
            "def final (r : Run) (m : Metric) : Option Q := (series r m).last?",
            "def atStep (r : Run) (m : Metric) (step : Nat) : Option Q := (series r m).at? step",
            "def peak (r : Run) (m : Metric) : Option Q := (series r m).max?",
            "def lowest (r : Run) (m : Metric) : Option Q := (series r m).min?",
            "",
        ]

    if key_names:
        lines += _enum("Key", [key_idents[k] for k in key_names], key_names)
        config_cases = []
        for run in runs:
            for key in key_names:
                if key in run.config:
                    config_cases.append(
                        f"  | .{run.ident}, .{key_idents[key]} => some ({_lean_value(run.config[key], exact)})"
                    )
        lines.append("def config : Run → Key → Option Value")
        lines += config_cases
        if len(config_cases) < len(runs) * len(key_names):
            lines.append("  | _, _ => none")
        lines += [
            "",
            "def cfg (r : Run) (k : Key) : Option Q := (config r k).bind Value.num?",
            "def cfgStr (r : Run) (k : Key) : Option String := (config r k).bind Value.str?",
            "",
        ]

    provenance_keys = sorted({k for run in runs for k in run.provenance})
    provenance_docs = {
        "codeSha256": "SHA-256 of the entry script that produced each run, recorded by `trackio.init`.",
        "codePath": "File name of the entry script that produced each run.",
        "hfJobId": "Hugging Face Job each run ran in, if any.",
    }
    for key in provenance_keys:
        cases = [
            f"  | .{run.ident} => some {_lean_string(run.provenance[key])}"
            for run in runs
            if key in run.provenance
        ]
        lines += [f"/-- {provenance_docs[key]} -/", f"def {key} : Run → Option String"]
        lines += cases
        if len(cases) < len(runs):
            lines.append("  | _ => none")
        lines.append("")

    if any(run.code_files for run in runs):
        lines += [
            "/-- Local modules each run imported, with their SHA-256, recorded by `trackio.init`. -/",
            "def codeFiles : Run → List (String × String)",
        ]
        cases = []
        for run in runs:
            if run.code_files:
                items = ", ".join(
                    f"({_lean_string(k)}, {_lean_string(v)})"
                    for k, v in run.code_files.items()
                )
                cases.append(f"  | .{run.ident} => [{items}]")
        lines += cases
        if len(cases) < len(runs):
            lines.append("  | _ => []")
        lines.append("")

    lines += [f"end {module}", ""]
    return "\n".join(lines)


def write_lean_export(
    project: str,
    output: str | Path,
    metrics: list[str] | None = None,
    exact: bool = False,
) -> tuple[Path, Path]:
    """Write the project module and the `Trackio.lean` prelude next to it.

    `output` is either a `.lean` file path (its stem names the module) or a
    directory (the module is named after the project). Returns the module and
    prelude paths.
    """
    output = Path(output)
    if output.suffix == ".lean":
        module_path = output
        module_name = output.stem
    else:
        module_name = module_name_for_project(project)
        module_path = output / f"{module_name}.lean"
    source = export_project_to_lean(
        project, metrics=metrics, exact=exact, module_name=module_name
    )
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(source, encoding="utf-8")
    prelude_path = module_path.parent / "Trackio.lean"
    prelude_path.write_text(PRELUDE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return module_path, prelude_path
