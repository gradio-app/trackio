"""
hf-jobs-multi-gpu-system-metrics.py
===================================

Minimal example that exercises Trackio's multi-GPU system metrics path on a
single multi-GPU machine. The script uploads only this file with
`hf jobs uv run`, then relaunches itself under `torch.distributed.run` so each
GPU gets its own worker. Rank 0 initializes Trackio with `auto_log_gpu=True`,
which should record per-GPU system metrics for every visible GPU.

Run locally from this repo:

    python examples/hf-jobs-multi-gpu-system-metrics.py \
        --project local-multi-gpu-demo

Run on HF Jobs with the released package:

    hf jobs uv run \
        --flavor l4x4 \
        --timeout 20m \
        --secrets HF_TOKEN \
        --with torch \
        --with "trackio[gpu]" \
        examples/hf-jobs-multi-gpu-system-metrics.py \
        --project hf-jobs-multi-gpu-demo \
        --space-id <username>/<space-name>

Run on HF Jobs against this PR branch before release:

    hf jobs uv run \
        --flavor l4x4 \
        --timeout 20m \
        --secrets HF_TOKEN \
        --with torch \
        --with "trackio @ git+https://github.com/gradio-app/trackio.git@saba/multi-gpu" \
        --with nvidia-ml-py \
        --with psutil \
        examples/hf-jobs-multi-gpu-system-metrics.py \
        --project hf-jobs-multi-gpu-demo \
        --space-id <username>/<space-name>

After the job starts, open:

    https://huggingface.co/spaces/<username>/<space-name>

Then go to the run's System Metrics page and confirm that metrics such as
`utilization`, `allocated_memory`, `power`, and `temp` are present for multiple
GPUs on the same run.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import torch
import torch.distributed as dist

import trackio


def parse_args() -> argparse.Namespace:
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=f"hf-jobs-multi-gpu-{timestamp}")
    parser.add_argument("--run-name", default=f"distributed-smoke-{timestamp}")
    parser.add_argument("--space-id", default=None)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--matrix-size", type=int, default=2048)
    parser.add_argument("--matmul-repeats", type=int, default=6)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    parser.add_argument("--gpu-log-interval", type=float, default=1.0)
    parser.add_argument("--nproc-per-node", type=int, default=None)
    parser.add_argument("--no-launch", action="store_true")
    return parser.parse_args()


def maybe_relaunch_distributed(args: argparse.Namespace) -> None:
    if args.no_launch or "RANK" in os.environ:
        return

    if not torch.cuda.is_available():
        print("CUDA is not available, running a single-process fallback.", flush=True)
        return

    detected = torch.cuda.device_count()
    nproc_per_node = args.nproc_per_node or detected
    if nproc_per_node <= 1:
        print("Only one GPU detected, running a single-process fallback.", flush=True)
        return

    script_path = str(Path(__file__).resolve())
    cmd = [
        sys.executable,
        "-m",
        "torch.distributed.run",
        "--standalone",
        "--nnodes=1",
        f"--nproc-per-node={nproc_per_node}",
        script_path,
        "--no-launch",
        *sys.argv[1:],
    ]
    print("Launching distributed workers:", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    raise SystemExit(0)


def init_distributed() -> tuple[int, int, int, torch.device]:
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))

    if torch.cuda.is_available():
        torch.cuda.set_device(local_rank)
        device = torch.device("cuda", local_rank)
    else:
        device = torch.device("cpu")

    if world_size > 1 and not dist.is_initialized():
        backend = "nccl" if device.type == "cuda" else "gloo"
        dist.init_process_group(backend=backend)

    return rank, local_rank, world_size, device


def cleanup_distributed() -> None:
    if dist.is_initialized():
        dist.barrier()
        dist.destroy_process_group()


def average_across_workers(value: torch.Tensor, world_size: int) -> float:
    reduced = value.detach().clone()
    if world_size > 1:
        dist.all_reduce(reduced, op=dist.ReduceOp.SUM)
        reduced /= world_size
    return float(reduced.item())


def run_workload(args: argparse.Namespace) -> None:
    maybe_relaunch_distributed(args)
    rank, local_rank, world_size, device = init_distributed()

    if device.type == "cuda":
        dtype = torch.float16
        host = socket.gethostname()
        print(
            f"[rank {rank}] device={torch.cuda.get_device_name(device)} "
            f"host={host} world_size={world_size}",
            flush=True,
        )
    else:
        dtype = torch.float32
        print(f"[rank {rank}] running on CPU", flush=True)

    run = None
    if rank == 0:
        config = {
            "world_size": world_size,
            "matrix_size": args.matrix_size,
            "matmul_repeats": args.matmul_repeats,
            "steps": args.steps,
            "sleep_seconds": args.sleep_seconds,
            "gpu_log_interval": args.gpu_log_interval,
        }
        run = trackio.init(
            project=args.project,
            name=args.run_name,
            config=config,
            space_id=args.space_id,
            auto_log_gpu=True,
            gpu_log_interval=args.gpu_log_interval,
        )
        if args.space_id:
            print(
                f"DASHBOARD_URL=https://huggingface.co/spaces/{args.space_id}",
                flush=True,
            )

    left = torch.randn(args.matrix_size, args.matrix_size, device=device, dtype=dtype)
    right = torch.randn(args.matrix_size, args.matrix_size, device=device, dtype=dtype)

    for step in range(args.steps):
        start = time.perf_counter()
        work = left
        for _ in range(args.matmul_repeats):
            work = work @ right
        loss = work.float().pow(2).mean().sqrt()

        if device.type == "cuda":
            torch.cuda.synchronize(device)

        step_time = time.perf_counter() - start
        mean_loss = average_across_workers(loss, world_size)
        mean_step_time = average_across_workers(
            torch.tensor(step_time, device=device, dtype=torch.float32),
            world_size,
        )

        if rank == 0 and run is not None:
            total_flops = (
                2
                * args.matmul_repeats
                * (args.matrix_size**3)
                * world_size
            )
            tokens_per_second = (
                args.matrix_size * args.matrix_size * world_size / max(mean_step_time, 1e-6)
            )
            trackio.log(
                {
                    "train/rmse": mean_loss,
                    "train/step_time_seconds": mean_step_time,
                    "train/tokens_per_second": tokens_per_second,
                    "train/approx_tflops": total_flops / max(mean_step_time, 1e-6) / 1e12,
                },
                step=step,
            )
            print(
                f"[rank 0] step={step} rmse={mean_loss:.4f} "
                f"step_time={mean_step_time:.3f}s",
                flush=True,
            )

        if dist.is_initialized():
            dist.barrier()
        time.sleep(args.sleep_seconds)

    if rank == 0 and run is not None:
        time.sleep(max(args.gpu_log_interval, 1.0) + 1.0)
        trackio.finish()

    cleanup_distributed()


if __name__ == "__main__":
    run_workload(parse_args())
