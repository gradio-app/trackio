"""
Demonstrates Trackio's run resume behavior when a job crashes and is restarted
with the same human-readable run name.

Usage:
  python examples/crash-and-resume-same-run-name.py --phase crash
  python examples/crash-and-resume-same-run-name.py --phase restart --resume allow

The script uses the same `name` in both phases:
- `resume=never` creates a new run with the same name but a fresh run_id
- `resume=allow` resumes the latest run with that name if it exists
- `resume=must` requires that such a run already exists
"""

import argparse

import trackio

PROJECT = "crash-and-resume-demo"
RUN_NAME = "trainer-job-42"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["crash", "restart"], required=True)
    parser.add_argument(
        "--resume",
        choices=["never", "allow", "must"],
        default="never",
        help="Trackio resume mode for the init() call.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    run = trackio.init(
        project=PROJECT,
        name=RUN_NAME,
        resume=args.resume,
        config={"phase": args.phase},
    )
    print(f"Trackio run name: {run.name}")
    print(f"Trackio run id:   {run.id}")

    if args.phase == "crash":
        trackio.log({"loss": 1.0}, step=0)
        trackio.log({"loss": 0.8}, step=1)
        trackio.finish()
        raise RuntimeError(
            "Simulated crash after step 1. Re-run with --phase restart to continue."
        )

    trackio.log({"loss": 0.6}, step=None)
    trackio.log({"loss": 0.4}, step=None)
    trackio.finish()

    print("Restart phase finished successfully.")


if __name__ == "__main__":
    main()
