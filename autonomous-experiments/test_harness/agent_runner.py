"""
Agent test runner for autonomous ML experiments with Trackio.

Acts as an autonomous agent that:
1. Launches simulated training via subprocess
2. Polls alerts via trackio CLI
3. Decides next hyperparameters based on results
4. Iterates for N rounds
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SIMULATOR = str(Path(__file__).parent / "simulate_training.py")


def run_cli(args_list):
    result = subprocess.run(
        ["trackio"] + args_list + ["--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def run_training(project, run_name, **kwargs):
    cmd = [
        sys.executable,
        SIMULATOR,
        "--project",
        project,
        "--run-name",
        run_name,
    ]
    for key, value in kwargs.items():
        cmd.extend([f"--{key.replace('_', '-')}", str(value)])

    print(f"\n{'=' * 60}")
    print(f"Launching training: {run_name}")
    print(f"  Config: {kwargs}")
    print(f"{'=' * 60}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"  stdout: {result.stdout.strip()}")
    if result.stderr:
        print(f"  stderr: {result.stderr.strip()[:200]}")
    return result.returncode


def get_alerts(project, run_name=None, since=None):
    args = ["list", "alerts", "--project", project]
    if run_name:
        args.extend(["--run", run_name])
    if since:
        args.extend(["--since", since])
    result = run_cli(args)
    if result and "alerts" in result:
        return result["alerts"]
    return []


def experiment_failure_recovery(project):
    print("\n" + "=" * 60)
    print("EXPERIMENT: Failure Recovery")
    print("Goal: Detect crashes and restart with adjusted parameters")
    print("=" * 60)

    attempts = []
    lr = 1.0
    max_attempts = 5

    for attempt in range(max_attempts):
        run_name = f"attempt-{attempt}-lr{lr}"
        returncode = run_training(project, run_name, steps=500, lr=lr, seed=42)

        alerts = get_alerts(project, run_name)
        error_alerts = [a for a in alerts if a.get("level") == "error"]

        if returncode != 0 or error_alerts:
            error_msg = (
                error_alerts[0]["title"] if error_alerts else "non-zero exit code"
            )
            print(f"  [AGENT] Attempt {attempt} failed: {error_msg}")
            lr *= 0.1
            print(f"  [AGENT] Reducing LR to {lr}")
            attempts.append({"run": run_name, "status": "failed", "lr": lr * 10})
        else:
            result = run_cli(
                [
                    "get",
                    "metric",
                    "--project",
                    project,
                    "--run",
                    run_name,
                    "--metric",
                    "val/loss",
                ]
            )
            val_loss = (
                result["values"][-1]["value"]
                if result and result.get("values")
                else None
            )
            print(f"  [AGENT] Attempt {attempt} succeeded! val_loss={val_loss}")
            attempts.append(
                {"run": run_name, "status": "success", "val_loss": val_loss}
            )
            break

    print("\n[AGENT] Recovery history:")
    for a in attempts:
        print(f"  {a}")
    return {"attempts": len(attempts)}


def experiment_long_monitoring(project):
    print("\n" + "=" * 60)
    print("EXPERIMENT: Long-Running Monitoring")
    print("Goal: Test alert polling with --since during active training")
    print("=" * 60)

    run_name = "long-run"
    since = datetime.now(timezone.utc).isoformat()

    cmd = [
        sys.executable,
        SIMULATOR,
        "--project",
        project,
        "--run-name",
        run_name,
        "--steps",
        "1000",
        "--lr",
        "0.05",
        "--spike-at-step",
        "500",
        "--sleep",
        "0.005",
        "--seed",
        "42",
    ]

    print("  [AGENT] Starting long training run in background...")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    all_alerts = []

    while proc.poll() is None:
        time.sleep(0.5)
        alerts = get_alerts(project, run_name, since=since)

        new_alerts = [a for a in alerts if a not in all_alerts]
        if new_alerts:
            for alert in new_alerts:
                print(
                    f"  [AGENT] New alert: [{alert.get('level', '?')}] {alert.get('title', '?')}"
                )
                all_alerts.append(alert)
            since = datetime.now(timezone.utc).isoformat()

    stdout, _ = proc.communicate()
    print(f"  [AGENT] Training finished. Exit code: {proc.returncode}")
    print(f"  [AGENT] stdout: {stdout.strip()}")

    final_alerts = get_alerts(project, run_name)
    print(f"\n[AGENT] Total alerts captured: {len(final_alerts)}")
    return {"alerts": len(final_alerts)}


EXPERIMENTS = {
    "failure_recovery": experiment_failure_recovery,
    "long_monitoring": experiment_long_monitoring,
    "all": None,
}


def main():
    parser = argparse.ArgumentParser(description="Agent test runner for autonomous ML")
    parser.add_argument(
        "--experiment",
        choices=list(EXPERIMENTS.keys()),
        default="all",
        help="Which experiment to run",
    )
    parser.add_argument(
        "--project-prefix",
        default="agent-test",
        help="Prefix for project names",
    )
    args = parser.parse_args()

    if args.experiment == "all":
        experiments = [k for k in EXPERIMENTS if k != "all"]
    else:
        experiments = [args.experiment]

    results = {}

    for exp_name in experiments:
        project = f"{args.project_prefix}-{exp_name}"
        try:
            result = EXPERIMENTS[exp_name](project)
            results[exp_name] = result
        except Exception as e:
            print(f"\n[ERROR] Experiment {exp_name} failed: {e}")
            results[exp_name] = {"error": str(e)}

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, result in results.items():
        print(f"\n{name}:")
        for k, v in result.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
