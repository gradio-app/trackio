"""Launch `train_ablation.py` on Hugging Face Jobs.

The job installs the Trackio wheel you pass (so it records code provenance),
trains the requested variants with one worker per seed, uploads the project
database to `--bucket`, and publishes the dashboard to the static `--space`.
Each run's config records the job and the SHA-256 of the script HF Jobs ran,
which `trackio verify` checks later.

    uv build --wheel -o dist
    python examples/lean-claims/run_on_hf_jobs.py --trackio-wheel dist/trackio-*.whl \\
        --bucket <user>/attention-ablation-data --space <user>/attention-ablation
"""

import argparse
from pathlib import Path

import huggingface_hub

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trackio-wheel", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--space", required=True)
    parser.add_argument("--flavor", default="a10g-small")
    parser.add_argument("--timeout", default="2h")
    parser.add_argument("--seeds", nargs="+", default=["0", "1", "2"])
    parser.add_argument("--variants", nargs="+", default=["base", "h1", "dk8", "ls0"])
    args = parser.parse_args()

    wheel = Path(args.trackio_wheel).resolve()
    job = huggingface_hub.run_uv_job(
        str(HERE / "train_ablation.py"),
        script_args=[
            "--seeds",
            *args.seeds,
            "--variants",
            *args.variants,
            "--workers",
            str(len(args.seeds)),
            "--cache-dir",
            "/tmp/cache",
            "--upload-bucket",
            args.bucket,
            "--static-space",
            args.space,
            "--trackio-wheel",
            str(wheel),
        ],
        dependencies=[f"/data/{wheel.name}"],
        env={"TRACKIO_DIR": "/tmp/trackio"},
        secrets={"HF_TOKEN": huggingface_hub.get_token()},
        flavor=args.flavor,
        timeout=args.timeout,
        name="attention-ablation",
    )
    print(f"Job {job.id}: {job.url}")


if __name__ == "__main__":
    main()
