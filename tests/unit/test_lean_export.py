import shutil
import subprocess
from fractions import Fraction

import pytest

from trackio import cli
from trackio.lean_export import (
    _lean_ident,
    export_project_to_lean,
    module_name_for_project,
    write_lean_export,
)
from trackio.sqlite_storage import SQLiteStorage


def _log_ablation():
    SQLiteStorage.bulk_log(
        project="toy-ablation",
        run="heads=8",
        metrics_list=[
            {"dev/bleu": 2.0, "loss": 9.5},
            {"dev/bleu": 25.83, "loss": float("nan")},
        ],
        steps=[0, 100],
        config={
            "heads": 8,
            "dropout": 0.1,
            "optimizer": {"name": "adam", "beta2": 0.98},
            "tied": True,
            "_Username": "someone",
        },
    )
    SQLiteStorage.bulk_log(
        project="toy-ablation",
        run="heads=1",
        metrics_list=[{"dev/bleu": 1.5}, {"dev/bleu": 24.91}],
        steps=[0, 100],
        config={"heads": 1, "dropout": 0.1},
    )


def test_export_writes_runs_metrics_and_config(temp_dir):
    _log_ablation()

    source = export_project_to_lean("toy-ablation")

    assert source.startswith("import Trackio\n")
    assert "namespace ToyAblation" in source
    assert "  | heads_8\n  | heads_1\n" in source
    assert '  | .heads_8 => "heads=8"' in source
    assert "  | dev_bleu\n  | loss\n" in source
    assert "(100, q 2583 100)" in source
    assert "(100, q 2491 100)" in source
    assert "  | .heads_8, .optimizer_beta2 => some (.num (q 49 50))" in source
    assert '  | .heads_8, .optimizer_name => some (.str "adam")' in source
    assert "  | .heads_8, .tied => some (.bool true)" in source
    assert "_Username" not in source
    assert "Non-finite values skipped: 1." in source
    assert "  | _, _ => []" in source
    assert "  | _, _ => none" in source


def test_export_filters_metrics_and_supports_exact_floats(temp_dir):
    _log_ablation()

    source = export_project_to_lean("toy-ablation", metrics=["dev/bleu"], exact=True)

    exact = Fraction(25.83)
    assert f"(100, q {exact.numerator} {exact.denominator})" in source
    assert "| loss" not in source
    assert "  | _, _ => []" not in source


def test_digest_tracks_logged_values(temp_dir):
    _log_ablation()
    before = export_project_to_lean("toy-ablation")

    SQLiteStorage.log(
        project="toy-ablation", run="heads=1", metrics={"dev/bleu": 25.0}, step=200
    )
    after = export_project_to_lean("toy-ablation")

    digest = [line for line in before.splitlines() if line.startswith("def digest")]
    assert digest and digest[0] not in after
    assert export_project_to_lean("toy-ablation") == after


def test_export_of_missing_project_raises(temp_dir):
    with pytest.raises(ValueError, match="no runs"):
        export_project_to_lean("does-not-exist")


def test_identifiers_are_valid_and_unique():
    used: set[str] = set()
    assert _lean_ident("lr=1e-3", used, "r") == "lr_1e_3"
    assert _lean_ident("lr 1e-3", used, "r") == "lr_1e_3_2"
    assert _lean_ident("16-heads", used, "r") == "r_16_heads"
    assert _lean_ident("end", used, "r") == "end_"
    assert _lean_ident("name", used, "r") == "name_"
    assert _lean_ident("☃", used, "r") == "r"
    assert module_name_for_project("transformer-ablation") == "TransformerAblation"
    assert module_name_for_project("2024 sweep") == "Project2024Sweep"


def test_cli_export_writes_module_and_prelude(temp_dir, tmp_path, monkeypatch):
    _log_ablation()
    monkeypatch.setattr(
        "sys.argv",
        [
            "trackio",
            "export",
            "--project",
            "toy-ablation",
            "--format",
            "lean",
            "--output",
            str(tmp_path),
        ],
    )

    cli.main()

    assert (tmp_path / "ToyAblation.lean").read_text().startswith("import Trackio")
    assert "structure Q where" in (tmp_path / "Trackio.lean").read_text()


@pytest.mark.skipif(shutil.which("lake") is None, reason="Lean toolchain not installed")
def test_exported_module_proves_claims_in_lean(temp_dir, tmp_path):
    _log_ablation()
    write_lean_export("toy-ablation", tmp_path / "ToyAblation.lean")
    (tmp_path / "Claims.lean").write_text(
        "import ToyAblation\n"
        "open Trackio ToyAblation\n"
        "theorem more_heads_better : holds (do\n"
        "    let a ← final .heads_1 .dev_bleu\n"
        "    let b ← final .heads_8 .dev_bleu\n"
        "    return Q.roundsTo (b - a) 0.9 1) := by decide\n"
        "theorem no_loss_for_one_head : ¬ holds (final .heads_1 .loss |>.map (fun _ => true)) := by decide\n"
    )
    (tmp_path / "lakefile.toml").write_text(
        'name = "claims"\ndefaultTargets = ["Claims"]\n\n'
        '[[lean_lib]]\nname = "Claims"\nroots = ["Trackio", "ToyAblation", "Claims"]\n'
    )

    result = subprocess.run(
        ["lake", "build"], cwd=tmp_path, capture_output=True, text=True, timeout=600
    )

    assert result.returncode == 0, result.stdout + result.stderr
