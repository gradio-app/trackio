"""
Minimal reproducer for parallel writers logging to the same Trackio Space.

Multiple independent processes, each with a unique run name, all logging to the same Trackio project/Space.

Usage:
    python examples/reproduce-space-parallel-writers.py \
        --space-id hf-carbon/trackio-experiments \
        --project repro-parallel \
        --workers 5 \
        --steps 400 \
        --sleep 0.05

To mimic "different machines" more closely, run this same script from multiple
machines with the same `--space-id` and `--project`, and set `--workers 1`.
"""

from __future__ import annotations

import argparse
import math
import multiprocessing as mp
import os
import random
import sys
import time
import traceback
import uuid


def _worker(
    worker_idx: int,
    project: str,
    space_id: str,
    steps: int,
    sleep_s: float,
    system_every: int,
    start_event,
) -> None:
    import trackio

    run_name = f"repro-{worker_idx}-{uuid.uuid4().hex[:8]}"
    seed = int(time.time()) + worker_idx
    random.seed(seed)

    start_event.wait()

    trackio.init(
        project=project,
        space_id=space_id,
        name=run_name,
        config={
            "worker_idx": worker_idx,
            "seed": seed,
            "steps": steps,
            "sleep_s": sleep_s,
            "pid": os.getpid(),
            "host": os.uname().nodename if hasattr(os, "uname") else "unknown",
        },
    )

    try:
        for step in range(steps):
            progress = step / max(steps - 1, 1)
            loss = 2.0 * math.exp(-4 * progress) + random.uniform(0.0, 0.05)
            accuracy = min(0.999, progress + random.uniform(0.0, 0.03))
            lr = 1e-3 * (1 - progress * 0.9)

            trackio.log(
                {
                    "train/loss": round(loss, 6),
                    "train/accuracy": round(accuracy, 6),
                    "train/lr": round(lr, 8),
                    "system/tokens_per_second": random.randint(500, 2500),
                    "system/gpu_util": random.randint(30, 99),
                    "worker/index": worker_idx,
                },
                step=step,
            )

            if system_every > 0 and step % system_every == 0:
                trackio.log_system(
                    {
                        "gpu/utilization": random.randint(20, 100),
                        "gpu/memory_used_gb": round(random.uniform(4.0, 23.0), 2),
                        "cpu/percent": random.randint(10, 100),
                    }
                )

            if sleep_s > 0:
                time.sleep(sleep_s)
    finally:
        trackio.finish()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--space-id", required=True, help="HF Space ID")
    parser.add_argument("--project", required=True, help="Trackio project name")
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of parallel worker processes to start",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=400,
        help="Number of log steps per worker",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.05,
        help="Sleep between log calls in seconds",
    )
    parser.add_argument(
        "--system-every",
        type=int,
        default=5,
        help="Log system metrics every N steps (0 disables)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    # Prepare the Space exactly once before spawning workers. Without this,
    # every child process can race through `trackio.init()` and concurrently
    # try to deploy/update the same Space repo, which causes Hub commit 412s.
    import trackio
    from trackio import deploy, utils

    space_id, dataset_id, bucket_id = utils.preprocess_space_and_dataset_ids(
        args.space_id, None, None
    )
    if space_id is None:
        raise ValueError("--space-id is required")
    deploy.create_space_if_not_exists(
        space_id=space_id,
        dataset_id=dataset_id,
        bucket_id=bucket_id,
        private=None,
    )
    args.space_id = space_id

    ctx = mp.get_context("spawn")
    start_event = ctx.Event()
    processes: list[mp.Process] = []

    for worker_idx in range(args.workers):
        process = ctx.Process(
            target=_worker,
            args=(
                worker_idx,
                args.project,
                args.space_id,
                args.steps,
                args.sleep,
                args.system_every,
                start_event,
            ),
        )
        process.start()
        processes.append(process)

    print(
        f"Starting {args.workers} workers against space={args.space_id} project={args.project}",
        flush=True,
    )
    start_event.set()

    failed = False
    for process in processes:
        process.join()
        if process.exitcode != 0:
            failed = True
            print(
                f"Worker process pid={process.pid} exited with code {process.exitcode}",
                file=sys.stderr,
                flush=True,
            )

    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
