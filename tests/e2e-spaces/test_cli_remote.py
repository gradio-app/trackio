import json
import secrets
import subprocess


def test_cli_remote_list_and_get(test_space_id):
    import trackio

    project_name = f"test_cli_remote_{secrets.token_urlsafe(8)}"
    run_name = "cli_run"

    trackio.init(project=project_name, name=run_name, space_id=test_space_id)
    trackio.log({"loss": 0.5, "acc": 0.8})
    trackio.log({"loss": 0.3, "acc": 0.9})
    trackio.finish()

    def cli(*args):
        result = subprocess.run(
            ["trackio", *args, "--space", test_space_id, "--json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        return json.loads(result.stdout)

    projects = cli("list", "projects")
    assert project_name in projects["projects"]

    runs = cli("list", "runs", "--project", project_name)
    assert run_name in runs["runs"]

    metrics = cli("list", "metrics", "--project", project_name, "--run", run_name)
    assert "loss" in metrics["metrics"]
    assert "acc" in metrics["metrics"]

    values = cli(
        "get",
        "metric",
        "--project",
        project_name,
        "--run",
        run_name,
        "--metric",
        "loss",
    )
    assert len(values["values"]) == 2
    assert values["values"][0]["value"] == 0.5
    assert values["values"][1]["value"] == 0.3

    summary = cli("get", "run", "--project", project_name, "--run", run_name)
    assert summary["num_logs"] == 2
    assert "loss" in summary["metrics"]
