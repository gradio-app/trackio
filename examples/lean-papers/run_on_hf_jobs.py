"""Launch a training script from this folder on Hugging Face Jobs.

The job installs the Trackio wheel you pass (so each run records the SHA-256 of the
script and of any local module it imports), runs the script with the arguments
after `--`, and the script uploads its project to `--bucket` and, with `--space`,
publishes the dashboard there. `trackio verify` later checks the recorded hashes against
the files the job ran.

    uv build --wheel -o dist
    python examples/lean-papers/run_on_hf_jobs.py memorization/train_capacity.py \\
        --trackio-wheel dist/trackio-*.whl --bucket <user>/mem-data --space <user>/mem \\
        -- --models 1x32 2x64 --workers 4
"""

import argparse
import sys
from pathlib import Path

import huggingface_hub

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("script", help="Path relative to this folder")
    parser.add_argument("--trackio-wheel", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--space")
    parser.add_argument("--flavor", default="a10g-small")
    parser.add_argument("--timeout", default="3h")
    parser.add_argument("--name")
    argv = sys.argv[1:]
    split = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:split])
    extra = argv[split + 1 :]

    script = (HERE / args.script).resolve()
    wheel = Path(args.trackio_wheel).resolve()
    job = huggingface_hub.run_uv_job(
        str(script),
        script_args=[
            *extra,
            "--upload-bucket",
            args.bucket,
            *(["--static-space", args.space] if args.space else []),
            "--trackio-wheel",
            str(wheel),
        ],
        dependencies=[
            f"/data/{wheel.name}",
            *(["pyarrow>=21.0"] if args.space else []),
        ],
        env={"TRACKIO_DIR": "/tmp/trackio"},
        secrets={"HF_TOKEN": huggingface_hub.get_token()},
        flavor=args.flavor,
        timeout=args.timeout,
        name=args.name or script.stem,
    )
    print(f"Job {job.id}: {job.url}")


if __name__ == "__main__":
    main()
