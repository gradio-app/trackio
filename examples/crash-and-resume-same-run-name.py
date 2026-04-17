"""
Demonstrates Trackio's run resume behavior when a job crashes and restarts with
the same human-readable run name.

Usage:
  python examples/crash-and-resume-same-run-name.py
  python examples/crash-and-resume-same-run-name.py --resume never
  python examples/crash-and-resume-same-run-name.py --resume allow
  python examples/crash-and-resume-same-run-name.py --resume must

This example runs both phases in a single invocation:
- phase 1 always starts a fresh run and logs 20 steps
- a simulated crash interrupts the job
- phase 2 restarts the job with the configured resume mode and logs 100 more steps

The restart behavior is controlled by `--resume`:
- `never`: restart creates a second run with the same name and a new run_id
- `allow`: restart resumes the latest run with that name if it exists
- `must`: restart must resume an existing run with that name
"""

import argparse
import math
import uuid
import warnings

warnings.filterwarnings(
    "ignore",
    category=SyntaxWarning,
    module=r"pydub\.utils",
)

import trackio  # noqa: E402

DEFAULT_PROJECT = f"crash-and-resume-demo-{uuid.uuid4().hex[:8]}"
DEFAULT_RUN_NAME = "trainer-job-42"
DEFAULT_CRASH_STEPS = 20
DEFAULT_RESTART_STEPS = 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME)
    parser.add_argument("--crash-steps", type=int, default=DEFAULT_CRASH_STEPS)
    parser.add_argument("--restart-steps", type=int, default=DEFAULT_RESTART_STEPS)
    parser.add_argument(
        "--resume",
        choices=["never", "allow", "must"],
        default="allow",
        help="Resume mode used for the simulated restart phase.",
    )
    return parser.parse_args()


def log_phase(
    start_step: int, num_steps: int, start_loss: float, end_loss: float
) -> None:
    print(f"Logging steps {start_step}..{start_step + num_steps - 1}")
    for offset in range(num_steps):
        progress = offset / max(1, num_steps - 1)
        loss = (
            start_loss
            + ((end_loss - start_loss) * progress)
            + (0.01 * math.sin(offset / 6))
        )
        accuracy = (
            0.25
            + (0.7 * (1 - (loss / max(start_loss, 0.01))))
            + (0.02 * math.cos(offset / 9))
        )
        trackio.log(
            {
                "loss": round(loss, 4),
                "accuracy": round(max(0.0, min(0.999, accuracy)), 4),
                "phase_progress": offset + 1,
            },
            step=None,
        )


def start_run(
    project: str,
    run_name: str,
    resume: str,
    phase: str,
    crash_steps: int,
    restart_steps: int,
):
    run = trackio.init(
        project=project,
        name=run_name,
        resume=resume,
        config={
            "phase": phase,
            "resume_mode": resume,
            "crash_steps": crash_steps,
            "restart_steps": restart_steps,
        },
    )
    print(f"Trackio run name: {run.name}")
    print(f"Trackio run id:   {run.id}")
    print(f"Phase:            {phase}")
    print(f"Resume mode:      {resume}")
    return run


def main() -> None:
    args = parse_args()

    print("=== phase 1: start fresh run ===")
    first_run = start_run(
        project=args.project,
        run_name=args.run_name,
        resume="never",
        phase="crash",
        crash_steps=args.crash_steps,
        restart_steps=args.restart_steps,
    )
    log_phase(start_step=0, num_steps=args.crash_steps, start_loss=0.7, end_loss=0.6)
    trackio.finish()

    print(f"Simulated crash after {args.crash_steps} steps. Restarting the job now.")

    print("=== phase 2: restart job ===")
    restarted_run = start_run(
        project=args.project,
        run_name=args.run_name,
        resume=args.resume,
        phase="restart",
        crash_steps=args.crash_steps,
        restart_steps=args.restart_steps,
    )
    log_phase(
        start_step=args.crash_steps,
        num_steps=args.restart_steps,
        start_loss=0.7,
        end_loss=0.2,
    )
    trackio.finish()

    resumed_same_run = restarted_run.id == first_run.id
    print(f"Restart reused original run id: {resumed_same_run}")
    print(f"Project:               {args.project}")
    print("Done. Open the dashboard to inspect the resulting run list and charts.")


if __name__ == "__main__":
    main()
