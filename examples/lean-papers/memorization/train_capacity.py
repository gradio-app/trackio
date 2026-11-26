# /// script
# requires-python = ">=3.10"
# dependencies = ["torch", "transformers"]
# ///
"""Measure the memorization capacity of small GPT-2 models, as in Section 3.2 of
"How much do language models memorize?" (Morris et al., 2025).

Each run trains one model on N sequences of S tokens drawn uniformly from V tokens,
so the data's entropy is exactly N·(S-1)·log2(V) bits over the S-1 predicted tokens
of each sequence (the first token of a sequence is never predicted). Memorized bits
are that entropy minus the model's code length, -log2 p(data), measured in float32.
A model's capacity is the most it memorizes over all dataset sizes, and the paper's
claim is that capacity ≈ 3.6 bits per parameter. The paper trains for 10^6 steps;
we train far fewer, with warmup and cosine decay, so every number here is a lower
bound on capacity.

Every run logs to Trackio: the training loss, memorized bits and bits per parameter
during training, the exact entropy, and the parameter count.

    python train_capacity.py --models 1x32 2x64 --sizes 256 1024 4096 --steps 20000
"""

import argparse
import math
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("TRACKIO_DIR", str(HERE / ".trackio"))

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from transformers import GPT2Config, GPT2LMHeadModel  # noqa: E402

import trackio  # noqa: E402
from trackio.bucket_storage import (  # noqa: E402
    create_bucket_if_not_exists,
    upload_project_to_bucket,
)

PROJECT = "memorization-capacity"
V, S = 2048, 64


def build_model(L: int, d: int) -> GPT2LMHeadModel:
    config = GPT2Config(
        vocab_size=V,
        n_positions=S,
        n_embd=d,
        n_layer=L,
        n_head=max(1, d // 32),
        resid_pdrop=0.0,
        embd_pdrop=0.0,
        attn_pdrop=0.0,
        bos_token_id=0,
        eos_token_id=0,
    )
    return GPT2LMHeadModel(config)


@torch.no_grad()
def code_length_bits(model, data, chunk: int = 1024) -> float:
    model.eval()
    nats = 0.0
    for i in range(0, data.shape[0], chunk):
        x = data[i : i + chunk]
        logits = model(x).logits[:, :-1].float()
        nats += F.cross_entropy(
            logits.reshape(-1, V), x[:, 1:].reshape(-1), reduction="sum"
        ).item()
    model.train()
    return nats / math.log(2)


def train_run(L, d, N, args, device):
    torch.manual_seed(args.seed)
    gen = torch.Generator().manual_seed(1000 * args.seed + N)
    data = torch.randint(0, V, (N, S), generator=gen).to(device)
    model = build_model(L, d).to(device)
    params = sum(p.numel() for p in model.parameters())
    entropy_bits = N * (S - 1) * int(math.log2(V))
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    warmup = max(1, args.steps // 100)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda i: min(1.0, (i + 1) / warmup)
        * (0.5 * (1 + math.cos(math.pi * i / args.steps)) if args.cosine else 1.0),
    )
    batch = min(N, args.batch)
    trackio.init(
        project=args.project,
        name=f"L{L}-d{d}-N{N}-s{args.seed}{args.run_suffix}",
        group=f"L{L}-d{d}",
        config={
            "n_layer": L,
            "d_model": d,
            "N": N,
            "V": V,
            "S": S,
            "log2_V": int(math.log2(V)),
            "seed": args.seed,
            "steps": args.steps,
            "lr": args.lr,
            "cosine": args.cosine,
            "batch": batch,
            "precision": args.precision,
            "device": str(device),
        },
    )
    trackio.log({"model/params": params, "data/entropy_bits": entropy_bits}, step=0)
    autocast = args.precision == "bf16"
    t0 = time.perf_counter()
    for step in range(1, args.steps + 1):
        idx = torch.randint(0, N, (batch,), device=device)
        x = data[idx]
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=autocast):
            loss = model(x, labels=x).loss
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        scheduler.step()
        if step % args.eval_every == 0 or step == args.steps:
            bits = entropy_bits - code_length_bits(model, data)
            trackio.log(
                {
                    "train/loss": loss.item(),
                    "mem/bits": bits,
                    "mem/bits_per_param": bits / params,
                    "mem/fraction_of_entropy": bits / entropy_bits,
                    "time/seconds": time.perf_counter() - t0,
                },
                step=step,
            )
            print(
                f"L{L} d{d} N{N} step {step}: {bits:,.0f} bits, {bits / params:.3f} bpp",
                flush=True,
            )
    trackio.finish()


def parse_model(spec: str) -> tuple[int, int]:
    L, d = spec.lower().split("x")
    return int(L), int(d)


def run_in_parallel(args):
    jobs = [(m, n) for m in args.models for n in args.sizes]
    shared = [
        "--project",
        args.project,
        f"--run-suffix={args.run_suffix}",
        "--steps",
        str(args.steps),
        "--lr",
        str(args.lr),
        "--batch",
        str(args.batch),
        "--precision",
        args.precision,
        "--eval-every",
        str(args.eval_every),
        "--seed",
        str(args.seed),
        "--cosine" if args.cosine else "--no-cosine",
    ]
    running = []
    while jobs or running:
        while jobs and len(running) < args.workers:
            model, n = jobs.pop(0)
            cmd = [sys.executable, os.path.abspath(__file__), *shared]
            cmd += ["--models", model, "--sizes", str(n)]
            running.append(subprocess.Popen(cmd))
            time.sleep(3)
        for proc in list(running):
            if proc.poll() is not None:
                running.remove(proc)
                if proc.returncode != 0:
                    raise SystemExit(f"Worker failed: {' '.join(proc.args)}")
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=PROJECT)
    parser.add_argument("--run-suffix", default="")
    parser.add_argument("--models", nargs="+", default=["1x32", "2x32", "1x64", "2x64"])
    parser.add_argument(
        "--sizes", nargs="+", type=int, default=[128, 256, 512, 1024, 2048, 4096, 8192]
    )
    parser.add_argument("--steps", type=int, default=50000)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument(
        "--cosine",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Warm up for 1%% of steps, then decay the learning rate to 0",
    )
    parser.add_argument("--batch", type=int, default=2048)
    parser.add_argument("--precision", choices=["bf16", "fp32"], default="bf16")
    parser.add_argument("--eval-every", type=int, default=2500)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--upload-bucket")
    parser.add_argument("--static-space")
    parser.add_argument(
        "--trackio-wheel", help="Trackio wheel the HF Job installed (not used here)"
    )
    args = parser.parse_args()

    if args.workers > 1:
        run_in_parallel(args)
    else:
        device = torch.device(
            "cuda"
            if torch.cuda.is_available()
            else "mps"
            if torch.backends.mps.is_available()
            else "cpu"
        )
        for spec in args.models:
            L, d = parse_model(spec)
            for n in args.sizes:
                train_run(L, d, n, args, device)
    if args.upload_bucket:
        create_bucket_if_not_exists(args.upload_bucket, private=False)
        upload_project_to_bucket(args.project, args.upload_bucket)
        print(f"Uploaded {args.project} to hf://buckets/{args.upload_bucket}")
    if args.static_space:
        trackio.sync(project=args.project, space_id=args.static_space, sdk="static")


if __name__ == "__main__":
    main()
