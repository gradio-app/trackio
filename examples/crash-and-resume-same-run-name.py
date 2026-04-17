"""
Demonstrates Trackio's run resume behavior when a job crashes and is restarted
with the same human-readable run name.

Usage:
  python examples/crash-and-resume-same-run-name.py --project crash-and-resume-never --phase crash
  python examples/crash-and-resume-same-run-name.py --project crash-and-resume-never --phase restart
  python examples/crash-and-resume-same-run-name.py --project crash-and-resume-allow --phase crash
  python examples/crash-and-resume-same-run-name.py --project crash-and-resume-allow --phase restart --resume allow

The script always uses the same run name:
- `resume=never` creates a second run with the same name and a fresh `run_id`
- `resume=allow` resumes the latest run with that name and keeps the same `run_id`
- `resume=must` requires that such a run already exists
"""

import argparse
import math

import trackio

DEFAULT_PROJECT = "crash-and-resume-demo"
DEFAULT_RUN_NAME = "trainer-job-42"
DEFAULT_STEPS_PER_PHASE = 50


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["crash", "restart"], required=True)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME)
    parser.add_argument("--steps-per-phase", type=int, default=DEFAULT_STEPS_PER_PHASE)
    parser.add_argument(
        "--resume",
        choices=["never", "allow", "must"],
        default="never",
        help="Trackio resume mode for the init() call.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_step = 0 if args.phase == "crash" else args.steps_per_phase

    run = trackio.init(
        project=args.project,
        name=args.run_name,
        resume=args.resume,
        config={
            "phase": args.phase,
            "resume_mode": args.resume,
            "steps_per_phase": args.steps_per_phase,
        },
    )
    print(f"Trackio run name: {run.name}")
    print(f"Trackio run id:   {run.id}")
    print(f"Logging steps {start_step}..{start_step + args.steps_per_phase - 1}")

    for offset in range(args.steps_per_phase):
        step = start_step + offset
        progress = step / max(1, (args.steps_per_phase * 2) - 1)
        loss = 1.2 - (0.85 * progress) + (0.05 * math.sin(step / 5))
        accuracy = 0.35 + (0.6 * progress) + (0.03 * math.cos(step / 7))
        trackio.log(
            {
                "loss": round(loss, 4),
                "accuracy": round(min(0.999, accuracy), 4),
                "phase_progress": offset + 1,
            },
            step=None,
        )

    if args.phase == "crash":
        trackio.finish()
        raise RuntimeError(
            f"Simulated crash after {args.steps_per_phase} steps. "
            "Re-run with --phase restart to continue."
        )

    trackio.finish()

    print("Restart phase finished successfully.")


if __name__ == "__main__":
    main()
