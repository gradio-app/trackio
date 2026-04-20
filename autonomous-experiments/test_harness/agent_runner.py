"""
Agent test runner for autonomous ML experiments with Trackio.

Acts as an autonomous agent that:
1. Launches simulated training via subprocess
2. Polls alerts via trackio CLI
3. Reads results via trackio CLI
4. Decides next hyperparameters based on results
5. Iterates for N rounds

Usage:
    python agent_runner.py --experiment lr_search
    python agent_runner.py --experiment architecture_search
    python agent_runner.py --experiment failure_recovery
    python agent_runner.py --experiment long_monitoring
    python agent_runner.py --experiment multi_objective
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


def get_run_metric(project, run_name, metric_name):
    result = run_cli(
        [
            "get",
            "metric",
            "--project",
            project,
            "--run",
            run_name,
            "--metric",
            metric_name,
        ]
    )
    if result and "values" in result:
        return result["values"]
    return []


def get_runs(project):
    result = run_cli(["list", "runs", "--project", project])
    if result and "runs" in result:
        return result["runs"]
    return []


def get_final_metric(project, run_name, metric_name):
    values = get_run_metric(project, run_name, metric_name)
    if values:
        return values[-1]["value"]
    return None


def find_best_run(project, metric_name, minimize=True):
    runs = get_runs(project)
    best_run = None
    best_value = float("inf") if minimize else float("-inf")

    for run_name in runs:
        val = get_final_metric(project, run_name, metric_name)
        if val is None:
            continue
        if minimize and val < best_value:
            best_value = val
            best_run = run_name
        elif not minimize and val > best_value:
            best_value = val
            best_run = run_name

    return best_run, best_value


def experiment_lr_search(project):
    print("\n" + "=" * 60)
    print("EXPERIMENT 1: Learning Rate Search")
    print("Goal: Find the best learning rate from a sequence")
    print("=" * 60)

    learning_rates = [1.0, 0.5, 0.1, 0.05, 0.01, 0.005, 0.001]
    commands_issued = 0

    for lr in learning_rates:
        run_name = f"lr-{lr}"
        run_training(project, run_name, steps=300, lr=lr, seed=42)

        alerts = get_alerts(project, run_name)
        commands_issued += 1
        error_alerts = [a for a in alerts if a.get("level") == "error"]

        if error_alerts:
            print(f"  [AGENT] LR {lr} caused errors: {error_alerts[0]['title']}")
            continue

        val_loss = get_final_metric(project, run_name, "val/loss")
        commands_issued += 1
        print(f"  [AGENT] LR {lr} -> final val_loss: {val_loss}")

    best_run, best_val = find_best_run(project, "val/loss", minimize=True)
    commands_issued += len(get_runs(project)) + 1
    print(f"\n[AGENT DECISION] Best run: {best_run} with val_loss={best_val:.4f}")
    print(f"[METRICS] Total CLI commands to find best: {commands_issued}")
    print("[METRICS] (With trackio best, this would be 1 command)")
    return {"best_run": best_run, "best_value": best_val, "commands": commands_issued}


def experiment_architecture_search(project):
    print("\n" + "=" * 60)
    print("EXPERIMENT 2: Architecture Search")
    print("Goal: Compare different model depths and find best architecture")
    print("=" * 60)

    configs = [
        {"depth": 2, "lr": 0.01, "batch_size": 32},
        {"depth": 4, "lr": 0.01, "batch_size": 32},
        {"depth": 6, "lr": 0.01, "batch_size": 32},
        {"depth": 8, "lr": 0.01, "batch_size": 32},
        {"depth": 12, "lr": 0.01, "batch_size": 32},
        {"depth": 4, "lr": 0.01, "batch_size": 64},
        {"depth": 6, "lr": 0.005, "batch_size": 64},
    ]
    commands_issued = 0

    for cfg in configs:
        run_name = f"arch-d{cfg['depth']}-bs{cfg['batch_size']}-lr{cfg['lr']}"
        run_training(project, run_name, steps=300, seed=42, **cfg)

    runs = get_runs(project)
    commands_issued += 1

    comparison = []
    for run_name in runs:
        val_loss = get_final_metric(project, run_name, "val/loss")
        accuracy = get_final_metric(project, run_name, "accuracy")
        commands_issued += 2
        comparison.append(
            {
                "run": run_name,
                "val_loss": val_loss,
                "accuracy": accuracy,
            }
        )

    comparison.sort(
        key=lambda x: x["val_loss"] if x["val_loss"] is not None else float("inf")
    )

    print("\n[AGENT] Run comparison (sorted by val_loss):")
    for entry in comparison:
        print(
            f"  {entry['run']}: val_loss={entry['val_loss']}, accuracy={entry['accuracy']}"
        )

    best = comparison[0]
    print(f"\n[AGENT DECISION] Best architecture: {best['run']}")
    print(f"[METRICS] Total CLI commands for comparison: {commands_issued}")
    print("[METRICS] (With trackio compare, this would be 1 command)")
    return {"best_run": best["run"], "commands": commands_issued}


def experiment_failure_recovery(project):
    print("\n" + "=" * 60)
    print("EXPERIMENT 3: Failure Recovery")
    print("Goal: Detect crashes and restart with adjusted parameters")
    print("=" * 60)

    attempts = []
    lr = 1.0
    max_attempts = 5
    commands_issued = 0

    for attempt in range(max_attempts):
        run_name = f"attempt-{attempt}-lr{lr}"
        returncode = run_training(project, run_name, steps=500, lr=lr, seed=42)

        alerts = get_alerts(project, run_name)
        commands_issued += 1

        error_alerts = [a for a in alerts if a.get("level") == "error"]

        if returncode != 0 or error_alerts:
            if error_alerts:
                error_msg = error_alerts[0]["title"]
            else:
                error_msg = "non-zero exit code"
            print(f"  [AGENT] Attempt {attempt} failed: {error_msg}")
            print(
                "  [AGENT] NOTE: Cannot determine run status (running vs crashed) from CLI"
            )
            lr *= 0.1
            print(f"  [AGENT] Reducing LR to {lr}")
            attempts.append({"run": run_name, "status": "failed", "lr": lr * 10})
        else:
            val_loss = get_final_metric(project, run_name, "val/loss")
            commands_issued += 1
            print(f"  [AGENT] Attempt {attempt} succeeded! val_loss={val_loss}")
            attempts.append(
                {"run": run_name, "status": "success", "val_loss": val_loss}
            )
            break

    print("\n[AGENT] Recovery history:")
    for a in attempts:
        print(f"  {a}")
    print(f"[METRICS] Total CLI commands: {commands_issued}")
    print("[METRICS] Gap: No run status tracking - must infer from alerts + exit code")
    return {"attempts": len(attempts), "commands": commands_issued}


def experiment_long_monitoring(project):
    print("\n" + "=" * 60)
    print("EXPERIMENT 4: Long-Running Monitoring")
    print("Goal: Test alert polling with --since during active training")
    print("=" * 60)

    run_name = "long-run"
    since = datetime.now(timezone.utc).isoformat()
    commands_issued = 0

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

    poll_count = 0
    all_alerts = []

    while proc.poll() is None:
        time.sleep(0.5)
        alerts = get_alerts(project, run_name, since=since)
        commands_issued += 1
        poll_count += 1

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
    commands_issued += 1

    print(f"\n[AGENT] Total alerts captured: {len(final_alerts)}")
    print(f"[METRICS] Poll count: {poll_count}")
    print(f"[METRICS] Total CLI commands: {commands_issued}")
    return {
        "poll_count": poll_count,
        "alerts": len(final_alerts),
        "commands": commands_issued,
    }


def experiment_multi_objective(project):
    print("\n" + "=" * 60)
    print("EXPERIMENT 5: Multi-Objective Optimization")
    print("Goal: Optimize for both val_loss AND accuracy simultaneously")
    print("=" * 60)

    configs = [
        {"lr": 0.001, "depth": 4, "batch_size": 16},
        {"lr": 0.005, "depth": 6, "batch_size": 32},
        {"lr": 0.01, "depth": 6, "batch_size": 32},
        {"lr": 0.01, "depth": 8, "batch_size": 64},
        {"lr": 0.05, "depth": 4, "batch_size": 32},
    ]
    commands_issued = 0

    for cfg in configs:
        run_name = f"multi-d{cfg['depth']}-lr{cfg['lr']}-bs{cfg['batch_size']}"
        run_training(project, run_name, steps=300, seed=42, **cfg)

    runs = get_runs(project)
    commands_issued += 1

    results = []
    for run_name in runs:
        val_loss = get_final_metric(project, run_name, "val/loss")
        accuracy = get_final_metric(project, run_name, "accuracy")
        commands_issued += 2
        results.append({"run": run_name, "val_loss": val_loss, "accuracy": accuracy})

    print("\n[AGENT] Multi-objective results:")
    for r in sorted(results, key=lambda x: (x["val_loss"] or float("inf"))):
        print(f"  {r['run']}: val_loss={r['val_loss']}, accuracy={r['accuracy']}")

    pareto_front = []
    for r in results:
        if r["val_loss"] is None or r["accuracy"] is None:
            continue
        dominated = False
        for other in results:
            if other["val_loss"] is None or other["accuracy"] is None:
                continue
            if (
                other["val_loss"] <= r["val_loss"]
                and other["accuracy"] >= r["accuracy"]
            ):
                if (
                    other["val_loss"] < r["val_loss"]
                    or other["accuracy"] > r["accuracy"]
                ):
                    dominated = True
                    break
        if not dominated:
            pareto_front.append(r)

    print("\n[AGENT] Pareto-optimal runs:")
    for r in pareto_front:
        print(f"  {r['run']}: val_loss={r['val_loss']}, accuracy={r['accuracy']}")

    print(f"\n[METRICS] Total CLI commands: {commands_issued}")
    print(
        "[METRICS] (With trackio compare --metrics val/loss,accuracy, this would be 1)"
    )
    return {"pareto_front": pareto_front, "commands": commands_issued}


EXPERIMENTS = {
    "lr_search": experiment_lr_search,
    "architecture_search": experiment_architecture_search,
    "failure_recovery": experiment_failure_recovery,
    "long_monitoring": experiment_long_monitoring,
    "multi_objective": experiment_multi_objective,
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
    total_commands = 0

    for exp_name in experiments:
        project = f"{args.project_prefix}-{exp_name}"
        try:
            result = EXPERIMENTS[exp_name](project)
            results[exp_name] = result
            total_commands += result.get("commands", 0)
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
    print(f"\nTotal CLI commands across all experiments: {total_commands}")


if __name__ == "__main__":
    main()
