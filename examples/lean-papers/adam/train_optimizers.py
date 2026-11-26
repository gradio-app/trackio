# /// script
# requires-python = ">=3.10"
# dependencies = ["torch", "datasets", "numpy", "pillow"]
# ///
"""Rerun Section 6 of "Adam: A Method for Stochastic Optimization" at small scale.

Tasks (Section 6.1-6.3): L2-regularized logistic regression on MNIST with the
stepsize decayed as α/√t, a 784-1000-1000-10 ReLU network with dropout on MNIST, and
the c64-c64-c128-1000 CNN on CIFAR-10 with dropout. Optimizers: Adam, SGD with
Nesterov momentum, Adagrad, and (for the MLP) RMSProp and AdaDelta. As in the paper
("searched over a dense grid ... reported using the best"), each optimizer gets a
learning-rate grid on seed 0, and the best rate by final training cost is rerun on
seeds 1 and 2. The grids are per task and wide enough that the best rate is never at
an edge (`Claims.lean` checks this).

Every run logs the training cost each epoch. Adam runs also log a probe: PyTorch's
Adam applied to fixed gradients, which `Conformance.lean` checks against Algorithm 1.
CNN runs with Adam log statistics of √v̂ relative to ε, for Section 6.3's claim
that "the second moment estimate v̂_t vanishes to zeros after a few epochs and is
dominated by the ε".
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

import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from datasets import load_dataset  # noqa: E402
from torch import nn  # noqa: E402

import trackio  # noqa: E402
from trackio.bucket_storage import (  # noqa: E402
    create_bucket_if_not_exists,
    upload_project_to_bucket,
)

PROJECT = "adam-optimizers"
L2 = 1e-4
BATCH = 128

OPTIMIZERS = {
    "logreg": ["adam", "sgd_nesterov", "adagrad"],
    "mlp": ["adam", "sgd_nesterov", "adagrad", "rmsprop", "adadelta"],
    "cnn": ["adam", "sgd_nesterov", "adagrad"],
}

GRID = {
    "logreg": {
        "adam": [3e-3, 1e-2, 3e-2, 1e-1, 3e-1, 1.0],
        "sgd_nesterov": [0.1, 0.3, 1.0, 3.0],
        "adagrad": [0.03, 0.1, 0.3, 1.0],
    },
    "mlp": {
        "adam": [1e-4, 3e-4, 1e-3, 3e-3],
        "sgd_nesterov": [0.01, 0.03, 0.1, 0.3],
        "adagrad": [0.003, 0.01, 0.03, 0.1],
        "rmsprop": [1e-4, 3e-4, 1e-3, 3e-3],
        "adadelta": [0.1, 0.3, 1.0, 3.0],
    },
    "cnn": {
        "adam": [1e-4, 3e-4, 1e-3],
        "sgd_nesterov": [0.001, 0.003, 0.01, 0.03],
        "adagrad": [3e-4, 1e-3, 3e-3, 1e-2],
    },
}

EPOCHS = {"logreg": 20, "mlp": 20, "cnn": 15}

PROBE_GRADS = [[((7 * t + 3 * i) % 9 - 4) / 8 for i in range(3)] for t in range(10)]
PROBE_INIT = [0.5, -0.25, 1.0]


def load(task, device):
    if task == "cnn":
        ds = load_dataset("uoft-cs/cifar10", split="train")
        x = np.stack([np.asarray(im, dtype=np.float32) for im in ds["img"]]) / 255.0
        x = torch.tensor(x).permute(0, 3, 1, 2)
        x = (x - x.mean(dim=(0, 2, 3), keepdim=True)) / x.std(
            dim=(0, 2, 3), keepdim=True
        )
        y = torch.tensor(ds["label"])
    else:
        ds = load_dataset("ylecun/mnist", split="train")
        x = np.stack([np.asarray(im, dtype=np.float32) for im in ds["image"]]) / 255.0
        x = torch.tensor(x).reshape(len(ds), -1)
        y = torch.tensor(ds["label"])
    return x.to(device), y.to(device)


def build(task):
    if task == "logreg":
        return nn.Linear(784, 10)
    if task == "mlp":
        return nn.Sequential(
            nn.Dropout(0.2),
            nn.Linear(784, 1000),
            nn.ReLU(),
            nn.Dropout(0.5),
            nn.Linear(1000, 1000),
            nn.ReLU(),
            nn.Dropout(0.5),
            nn.Linear(1000, 10),
        )
    return nn.Sequential(
        nn.Dropout(0.2),
        nn.Conv2d(3, 64, 5, padding=2),
        nn.ReLU(),
        nn.MaxPool2d(3, stride=2, padding=1),
        nn.Conv2d(64, 64, 5, padding=2),
        nn.ReLU(),
        nn.MaxPool2d(3, stride=2, padding=1),
        nn.Conv2d(64, 128, 5, padding=2),
        nn.ReLU(),
        nn.MaxPool2d(3, stride=2, padding=1),
        nn.Flatten(),
        nn.Linear(128 * 4 * 4, 1000),
        nn.ReLU(),
        nn.Dropout(0.5),
        nn.Linear(1000, 10),
    )


def make_optimizer(name, params, lr):
    if name == "adam":
        return torch.optim.Adam(params, lr=lr, betas=(0.9, 0.999), eps=1e-8)
    if name == "sgd_nesterov":
        return torch.optim.SGD(params, lr=lr, momentum=0.9, nesterov=True)
    if name == "adagrad":
        return torch.optim.Adagrad(params, lr=lr)
    if name == "rmsprop":
        return torch.optim.RMSprop(params, lr=lr, alpha=0.99)
    return torch.optim.Adadelta(params, lr=lr)


def adam_probe():
    p = torch.tensor(PROBE_INIT, dtype=torch.float64, requires_grad=True)
    opt = torch.optim.Adam([p], lr=1e-3, betas=(0.9, 0.999), eps=1e-8)
    out = {}
    for t, g in enumerate(PROBE_GRADS, 1):
        p.grad = torch.tensor(g, dtype=torch.float64)
        opt.step()
        for i, value in enumerate(p.detach().tolist()):
            out[f"probe/adam/t{t}_p{i}"] = value
    return out


def second_moment_stats(opt):
    ratios = []
    for group in opt.param_groups:
        for p in group["params"]:
            state = opt.state.get(p)
            if not state:
                continue
            step = float(state["step"])
            vhat = state["exp_avg_sq"] / (1 - 0.999**step)
            ratios.append((vhat.sqrt() / group["eps"]).flatten())
    r = torch.cat(ratios)
    return {
        "adam/sqrt_vhat_over_eps_median": r.median().item(),
        "adam/frac_sqrt_vhat_below_eps": (r < 1).float().mean().item(),
    }


def train_run(task, opt_name, lr, seed, phase, data, args, device):
    torch.manual_seed(seed)
    x, y = data
    model = build(task).to(device)
    opt = make_optimizer(opt_name, model.parameters(), lr)
    decay = task == "logreg" and opt_name in ("adam", "sgd_nesterov")
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda step: 1 / math.sqrt(step + 1) if decay else 1.0
    )
    epochs = args.epochs or EPOCHS[task]
    trackio.init(
        project=args.project,
        name=f"{task}-{opt_name}-lr{lr:g}-s{seed}{args.run_suffix}",
        group=f"{task}-{opt_name}",
        config={
            "task": task,
            "optimizer": opt_name,
            "lr": lr,
            "seed": seed,
            "phase": phase,
            "epochs": epochs,
            "batch": BATCH,
            "l2": L2,
            "lr_decay_inv_sqrt_t": decay,
        },
    )
    if opt_name == "adam":
        trackio.log(adam_probe(), step=0)
    gen = torch.Generator(device="cpu").manual_seed(seed)
    n = x.shape[0]
    step = 0
    for epoch in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(n, generator=gen).to(device)
        total, count = 0.0, 0
        for i in range(0, n, BATCH):
            idx = perm[i : i + BATCH]
            out = model(x[idx])
            loss = F.cross_entropy(out, y[idx])
            if task == "logreg":
                loss = loss + L2 * model.weight.pow(2).sum()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            step += 1
            total += loss.item() * idx.numel()
            count += idx.numel()
        metrics = {"epoch": epoch, "train/cost": total / count}
        if not math.isfinite(metrics["train/cost"]):
            metrics["train/cost"] = 1e9
        if task == "cnn" and opt_name == "adam":
            metrics.update(second_moment_stats(opt))
        trackio.log(metrics, step=step)
        print(
            f"{task} {opt_name} lr={lr:g} s{seed} epoch {epoch}: {metrics['train/cost']:.4f}",
            flush=True,
        )
        if metrics["train/cost"] >= 1e9:
            break
    trackio.finish()
    return metrics["train/cost"]


def run_task(task, args, device):
    data = load(task, device)
    best = {}
    for opt_name in OPTIMIZERS[task]:
        results = {}
        for lr in GRID[task][opt_name]:
            results[lr] = train_run(task, opt_name, lr, 0, "grid", data, args, device)
        best[opt_name] = min(results, key=results.get)
        print(f"{task} {opt_name}: best lr {best[opt_name]:g}", flush=True)
    for opt_name in OPTIMIZERS[task]:
        for seed in (1, 2):
            train_run(task, opt_name, best[opt_name], seed, "final", data, args, device)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=PROJECT)
    parser.add_argument("--run-suffix", default="")
    parser.add_argument("--tasks", nargs="+", default=["logreg", "mlp", "cnn"])
    parser.add_argument("--epochs", type=int, default=0)
    parser.add_argument("--parallel", action="store_true", help="One process per task")
    parser.add_argument("--upload-bucket")
    parser.add_argument("--static-space")
    parser.add_argument(
        "--trackio-wheel", help="Trackio wheel the HF Job installed (not used here)"
    )
    args = parser.parse_args()

    if args.parallel and len(args.tasks) > 1:
        procs = []
        for task in args.tasks:
            cmd = [
                sys.executable,
                os.path.abspath(__file__),
                "--project",
                args.project,
                f"--run-suffix={args.run_suffix}",
                "--tasks",
                task,
                "--epochs",
                str(args.epochs),
            ]
            procs.append(subprocess.Popen(cmd))
            time.sleep(5)
        for proc in procs:
            if proc.wait() != 0:
                raise SystemExit(f"Task failed: {' '.join(proc.args)}")
    else:
        device = torch.device(
            "cuda"
            if torch.cuda.is_available()
            else "mps"
            if torch.backends.mps.is_available()
            else "cpu"
        )
        for task in args.tasks:
            run_task(task, args, device)
    if args.upload_bucket:
        create_bucket_if_not_exists(args.upload_bucket, private=False)
        upload_project_to_bucket(args.project, args.upload_bucket)
        print(f"Uploaded {args.project} to hf://buckets/{args.upload_bucket}")
    if args.static_space:
        trackio.sync(project=args.project, space_id=args.static_space, sdk="static")


if __name__ == "__main__":
    main()
