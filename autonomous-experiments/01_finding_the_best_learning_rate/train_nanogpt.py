"""
train_nanogpt.py — Minimal NanoGPT (GPT-2 Small, 124M) Training Script
=======================================================================

Train a GPT-2 Small model from scratch on FineWeb, on a single GPU.
Based on techniques from https://github.com/KellerJordan/modded-nanogpt,
distilled into a minimal, hackable script for optimizer experimentation.

Architecture (modernized GPT-2 Small, 124M params):
  - 12 layers, 768 dim, 12 heads
  - RoPE (Rotary Position Embeddings)
  - RMSNorm (instead of LayerNorm)
  - ReLU-squared activation (instead of GELU)
  - QK-Norm for training stability
  - Zero-init output projections (muP-like)
  - Weight tying between embedding and LM head

Optimizer choices (--optimizer):
  "muon"  — Muon for hidden weight matrices + AdamW for embeddings/norms (default)
  "adamw" — Standard AdamW for all parameters

Data: FineWeb (pre-tokenized with GPT-2 tokenizer, auto-downloaded from HF Hub).
      Downloads ~1.8GB for 9 training shards (~900M tokens) + validation.

Run with Hugging Face Jobs like this:

hf jobs uv run \
    --flavor a100-large \
    --timeout 10m \
    --secrets HF_TOKEN \
    --with torch \
    --with numpy \
    train_nanogpt.py
"""

import glob
import math
import os
import time
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import trackio

# =====================================================================
# Configuration
# =====================================================================


@dataclass
class GPTConfig:
    vocab_size: int = 50257
    seq_len: int = 1024
    num_layers: int = 12
    num_heads: int = 12
    model_dim: int = 768


# =====================================================================
# Model
# =====================================================================


class RMSNorm(nn.Module):
    def __init__(self, dim, eps=1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps) * self.weight


class RotaryEmbedding(nn.Module):
    def __init__(self, dim, max_seq_len=2048, theta=10000.0):
        super().__init__()
        freqs = 1.0 / (theta ** (torch.arange(0, dim, 2).float() / dim))
        t = torch.arange(max_seq_len).float()
        emb = torch.outer(t, freqs)
        self.register_buffer("cos_cached", emb.cos())
        self.register_buffer("sin_cached", emb.sin())

    def forward(self, x):
        seq_len = x.size(-2)
        cos = self.cos_cached[:seq_len]
        sin = self.sin_cached[:seq_len]
        d = x.shape[-1] // 2
        x1, x2 = x[..., :d], x[..., d:]
        return torch.cat([x1 * cos - x2 * sin, x2 * cos + x1 * sin], dim=-1)


class CausalSelfAttention(nn.Module):
    def __init__(self, config: GPTConfig):
        super().__init__()
        self.num_heads = config.num_heads
        self.head_dim = config.model_dim // config.num_heads
        self.qkv = nn.Linear(config.model_dim, 3 * config.model_dim, bias=False)
        self.out_proj = nn.Linear(config.model_dim, config.model_dim, bias=False)
        nn.init.zeros_(self.out_proj.weight)
        self.q_norm = RMSNorm(self.head_dim)
        self.k_norm = RMSNorm(self.head_dim)
        self.rope = RotaryEmbedding(self.head_dim, config.seq_len)

    def forward(self, x):
        B, T, C = x.shape
        qkv = self.qkv(x).view(B, T, 3, self.num_heads, self.head_dim)
        q, k, v = qkv.unbind(2)
        q, k, v = q.transpose(1, 2), k.transpose(1, 2), v.transpose(1, 2)
        q, k = self.q_norm(q), self.k_norm(k)
        q, k = self.rope(q), self.rope(k)
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        return self.out_proj(y.transpose(1, 2).reshape(B, T, C))


class MLP(nn.Module):
    def __init__(self, config: GPTConfig):
        super().__init__()
        hidden = 4 * config.model_dim
        self.c_fc = nn.Linear(config.model_dim, hidden, bias=False)
        self.c_proj = nn.Linear(hidden, config.model_dim, bias=False)
        nn.init.zeros_(self.c_proj.weight)

    def forward(self, x):
        return self.c_proj(F.relu(self.c_fc(x)).square())


class Block(nn.Module):
    def __init__(self, config: GPTConfig):
        super().__init__()
        self.ln1 = RMSNorm(config.model_dim)
        self.attn = CausalSelfAttention(config)
        self.ln2 = RMSNorm(config.model_dim)
        self.mlp = MLP(config)

    def forward(self, x):
        x = x + self.attn(self.ln1(x))
        x = x + self.mlp(self.ln2(x))
        return x


class GPT(nn.Module):
    def __init__(self, config: GPTConfig):
        super().__init__()
        self.config = config
        self.embed = nn.Embedding(config.vocab_size, config.model_dim)
        self.blocks = nn.ModuleList([Block(config) for _ in range(config.num_layers)])
        self.ln_f = RMSNorm(config.model_dim)
        self.lm_head = nn.Linear(config.model_dim, config.vocab_size, bias=False)
        self.lm_head.weight = self.embed.weight

    def forward(self, idx, targets=None):
        x = self.embed(idx)
        for block in self.blocks:
            x = block(x)
        x = self.ln_f(x)
        logits = self.lm_head(x)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss


# =====================================================================
# Muon Optimizer
# =====================================================================


@torch.compile
def zeropower_via_newtonschulz5(G, steps=5, eps=1e-7):
    """
    Newton-Schulz iteration to compute the zeroth power / orthogonalization of G.
    Approximately replaces G with U @ V^T where U, S, V = G.svd().

    From https://github.com/KellerJordan/Muon
    """
    assert len(G.shape) == 2
    a, b, c = (3.4445, -4.7750, 2.0315)
    X = G.bfloat16()
    if G.size(0) > G.size(1):
        X = X.T
    X = X / (X.norm() + eps)
    for _ in range(steps):
        A = X @ X.T
        B = b * A + c * A @ A
        X = a * X + B @ X
    if G.size(0) > G.size(1):
        X = X.T
    return X


class Muon(torch.optim.Optimizer):
    """
    Muon — MomentUm Orthogonalized by Newton-schulz

    Runs SGD with Nesterov momentum, then replaces the update with its
    nearest orthogonal matrix via a Newton-Schulz iteration. This makes
    it ~1.5x more sample-efficient than Adam for hidden weight matrices.

    Should only be applied to 2D weight matrices in hidden layers.
    Embeddings, LM heads, norms, and biases should use AdamW.

    Reference: https://kellerjordan.github.io/posts/muon/
    """

    def __init__(self, params, lr=0.02, momentum=0.95, weight_decay=0.0, ns_steps=5):
        defaults = dict(lr=lr, momentum=momentum, weight_decay=weight_decay, ns_steps=ns_steps)
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self):
        for group in self.param_groups:
            lr = group["lr"]
            beta = group["momentum"]
            wd = group["weight_decay"]
            ns_steps = group["ns_steps"]

            for p in group["params"]:
                if p.grad is None:
                    continue

                g = p.grad
                state = self.state[p]
                if "momentum_buffer" not in state:
                    state["momentum_buffer"] = torch.zeros_like(g)

                buf = state["momentum_buffer"]
                buf.lerp_(g, 1 - beta)

                # Nesterov momentum then orthogonalize
                update = g.lerp_(buf, beta)
                update = zeropower_via_newtonschulz5(update, steps=ns_steps)
                update *= max(1, p.size(0) / p.size(1)) ** 0.5

                p.mul_(1 - lr * wd)
                p.add_(update, alpha=-lr)


# =====================================================================
# Data Loading
# =====================================================================


def download_data(data_dir, num_train_shards=9):
    """Download pre-tokenized FineWeb data (GPT-2 tokens) from HF Hub."""
    from huggingface_hub import hf_hub_download

    os.makedirs(data_dir, exist_ok=True)
    repo_id = "kjj0/fineweb10B-gpt2"

    print("Downloading validation shard...")
    hf_hub_download(
        repo_id=repo_id,
        filename="fineweb_val_000000.bin",
        repo_type="dataset",
        local_dir=data_dir,
    )

    for i in range(1, num_train_shards + 1):
        fname = f"fineweb_train_{i:06d}.bin"
        print(f"Downloading training shard {i}/{num_train_shards}...")
        hf_hub_download(
            repo_id=repo_id,
            filename=fname,
            repo_type="dataset",
            local_dir=data_dir,
        )

    print("Data download complete.\n")


class DataLoader:
    """Sequential data loader over memory-mapped tokenized shards."""

    @staticmethod
    def _load_token_shard(path):
        header = np.memmap(path, dtype=np.int32, mode="r", shape=(256,))
        if int(header[0]) == 20240520:
            num_tokens = int(header[2])
            return np.memmap(path, dtype=np.uint16, mode="r", offset=256 * 4, shape=(num_tokens,))
        return np.memmap(path, dtype=np.uint16, mode="r")

    def __init__(self, data_dir, split, batch_size, seq_len, device, vocab_size):
        pattern = os.path.join(data_dir, f"fineweb_{split}_*.bin")
        files = sorted(glob.glob(pattern))
        assert len(files) > 0, f"No data files found at {pattern}"

        self.shards = [self._load_token_shard(f) for f in files]
        self.batch_size = batch_size
        self.seq_len = seq_len
        self.device = device
        self.vocab_size = vocab_size
        self.shard_idx = 0
        self.pos = 0

        total_tokens = sum(len(s) for s in self.shards)
        print(f"  {split}: {len(files)} shard(s), {total_tokens / 1e6:.0f}M tokens")

        sample_tokens = np.concatenate([s[: min(4096, len(s))] for s in self.shards[:2]])
        sample_max = int(sample_tokens.max()) if len(sample_tokens) > 0 else -1
        assert sample_max < self.vocab_size, (
            f"Token id {sample_max} exceeds vocab_size={self.vocab_size}. "
            "Data shard format or vocab size is inconsistent."
        )

    def next_batch(self):
        B, T = self.batch_size, self.seq_len
        n = B * T + 1
        buf = np.empty(n, dtype=np.int64)

        filled = 0
        while filled < n:
            shard = self.shards[self.shard_idx]
            avail = len(shard) - self.pos
            take = min(avail, n - filled)
            buf[filled : filled + take] = shard[self.pos : self.pos + take].astype(
                np.int64
            )
            self.pos += take
            filled += take
            if self.pos >= len(shard):
                self.pos = 0
                self.shard_idx = (self.shard_idx + 1) % len(self.shards)

        tokens = torch.from_numpy(buf).to(self.device)
        return tokens[:-1].view(B, T), tokens[1:].view(B, T)

    def reset(self):
        self.shard_idx = 0
        self.pos = 0


# =====================================================================
# Learning Rate Schedule
# =====================================================================


def get_lr(step, warmup_steps, max_steps, max_lr, min_lr_ratio=0.1):
    """Cosine annealing with linear warmup."""
    min_lr = max_lr * min_lr_ratio
    if step < warmup_steps:
        return max_lr * (step + 1) / warmup_steps
    if step >= max_steps:
        return min_lr
    progress = (step - warmup_steps) / (max_steps - warmup_steps)
    return min_lr + 0.5 * (max_lr - min_lr) * (1 + math.cos(math.pi * progress))


# =====================================================================
# Evaluation
# =====================================================================


@torch.no_grad()
def evaluate(model, val_loader, eval_steps=20):
    model.eval()
    losses = []
    for _ in range(eval_steps):
        x, y = val_loader.next_batch()
        with torch.autocast("cuda", dtype=torch.bfloat16):
            _, loss = model(x, y)
        losses.append(loss.item())
    model.train()
    val_loader.reset()
    return sum(losses) / len(losses)


# =====================================================================
# Main
# =====================================================================


def build_optimizers(model, args):
    """
    Build optimizer(s) based on --optimizer flag.

    "muon": Muon for hidden 2D weight matrices + AdamW for embeddings/scalars.
    "adamw": Standard AdamW for everything.

    Returns a list of optimizers and a function to set learning rates per step.
    """
    if args.optimizer == "muon":
        muon_params, adam_embed_params, adam_scalar_params = [], [], []

        for name, p in model.named_parameters():
            if not p.requires_grad:
                continue
            if p.ndim >= 2 and "embed" not in name and "lm_head" not in name:
                muon_params.append(p)
            elif p.ndim >= 2:
                adam_embed_params.append(p)
            else:
                adam_scalar_params.append(p)

        opt_muon = Muon(
            muon_params,
            lr=args.muon_lr,
            momentum=0.95,
            weight_decay=args.weight_decay,
        )
        opt_adam = torch.optim.AdamW(
            [
                {"params": adam_embed_params, "lr": args.adam_lr},
                {
                    "params": adam_scalar_params,
                    "lr": args.adam_lr * 0.1,
                    "weight_decay": 0.0,
                },
            ],
            betas=(0.9, 0.95),
            weight_decay=args.weight_decay,
        )

        optimizers = [opt_muon, opt_adam]

        print(f"Optimizer: Muon (lr={args.muon_lr}) + AdamW (lr={args.adam_lr})")
        print(
            f"  Muon:  {sum(p.numel() for p in muon_params) / 1e6:.1f}M params "
            f"(hidden weight matrices)"
        )
        print(
            f"  AdamW: {sum(p.numel() for p in adam_embed_params + adam_scalar_params) / 1e6:.1f}M params "
            f"(embeddings + norms)"
        )

        def set_lr(step):
            muon_lr = get_lr(step, args.warmup_steps, args.max_steps, args.muon_lr)
            adam_lr = get_lr(step, args.warmup_steps, args.max_steps, args.adam_lr)
            for g in opt_muon.param_groups:
                g["lr"] = muon_lr
            for i, g in enumerate(opt_adam.param_groups):
                g["lr"] = adam_lr if i == 0 else adam_lr * 0.1
            return muon_lr

    else:
        opt = torch.optim.AdamW(
            model.parameters(),
            lr=args.adam_lr,
            betas=(0.9, 0.95),
            weight_decay=args.weight_decay,
        )
        optimizers = [opt]
        print(f"Optimizer: AdamW (lr={args.adam_lr})")

        def set_lr(step):
            lr = get_lr(step, args.warmup_steps, args.max_steps, args.adam_lr)
            for g in opt.param_groups:
                g["lr"] = lr
            return lr

    return optimizers, set_lr


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Minimal NanoGPT training on FineWeb"
    )

    parser.add_argument(
        "--optimizer",
        type=str,
        default="muon",
        choices=["muon", "adamw"],
        help="Optimizer: muon (Muon+AdamW) or adamw (pure AdamW)",
    )
    parser.add_argument("--learning_rate", type=float, default=None,
                        help="Primary learning rate. Overrides --adam_lr for adamw, "
                             "or both --muon_lr and --adam_lr (scaled) for muon.")
    parser.add_argument("--muon_lr", type=float, default=0.02)
    parser.add_argument("--adam_lr", type=float, default=6e-4)
    parser.add_argument("--weight_decay", type=float, default=0.01)

    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument("--seq_len", type=int, default=1024)
    parser.add_argument("--max_steps", type=int, default=5100)
    parser.add_argument("--warmup_steps", type=int, default=250)
    parser.add_argument("--grad_clip", type=float, default=1.0)
    parser.add_argument("--grad_accum_steps", type=int, default=1)
    parser.add_argument("--no_compile", action="store_true")

    parser.add_argument("--data_dir", type=str, default="data/fineweb10B")
    parser.add_argument(
        "--num_train_shards",
        type=int,
        default=9,
        help="Number of 100M-token training shards to download (1-103)",
    )

    parser.add_argument("--eval_interval", type=int, default=250)
    parser.add_argument("--eval_steps", type=int, default=20)
    parser.add_argument("--log_interval", type=int, default=10)
    parser.add_argument("--heartbeat_seconds", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run_name", type=str, default=None,
                        help="Override the auto-generated Trackio run name.")

    args = parser.parse_args()

    # --learning_rate overrides the per-optimizer defaults
    if args.learning_rate is not None:
        if args.optimizer == "adamw":
            args.adam_lr = args.learning_rate
        else:  # muon
            args.muon_lr = args.learning_rate
            args.adam_lr = args.learning_rate * (6e-4 / 0.02)  # keep default ratio

    # Determine the primary LR for display / run naming
    primary_lr = args.muon_lr if args.optimizer == "muon" else args.adam_lr
    run_name = args.run_name or f"{args.optimizer}-{primary_lr}"

    trackio.init(
        project="nanogpt_experiments",
        name=run_name,
        space_id="nanogpt_experiments",
        config={
            "optimizer": args.optimizer,
            "learning_rate": primary_lr,
            "muon_lr": args.muon_lr,
            "adam_lr": args.adam_lr,
            "weight_decay": args.weight_decay,
            "batch_size": args.batch_size,
            "seq_len": args.seq_len,
            "max_steps": args.max_steps,
            "warmup_steps": args.warmup_steps,
            "grad_clip": args.grad_clip,
            "grad_accum_steps": args.grad_accum_steps,
        },
    )

    launch_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[startup] train_nanogpt.py launched at {launch_time}")
    print(f"[startup] pid={os.getpid()} | cwd={os.getcwd()}")
    print(
        f"[startup] max_steps={args.max_steps} | batch_size={args.batch_size} | "
        f"grad_accum_steps={args.grad_accum_steps} | seq_len={args.seq_len}"
    )
    print()

    # ---- Setup ----
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_float32_matmul_precision("high")

    print(f"Device: {device}")
    if device == "cuda":
        print(f"GPU: {torch.cuda.get_device_name()}")
    print()

    config = GPTConfig(seq_len=args.seq_len)

    # ---- Data ----
    if not os.path.exists(os.path.join(args.data_dir, "fineweb_val_000000.bin")):
        download_data(args.data_dir, args.num_train_shards)

    print("Loading data...")
    train_loader = DataLoader(
        args.data_dir, "train", args.batch_size, args.seq_len, device, config.vocab_size
    )
    val_loader = DataLoader(
        args.data_dir, "val", args.batch_size, args.seq_len, device, config.vocab_size
    )
    print()

    # ---- Model ----
    model = GPT(config).to(device)
    num_params = sum(p.numel() for p in model.parameters())
    print(f"Model: GPT-2 Small — {num_params / 1e6:.1f}M parameters (weight-tied)")

    if not args.no_compile:
        print("Compiling model with torch.compile...")
        model = torch.compile(model)

    # ---- Optimizer ----
    optimizers, set_lr = build_optimizers(model, args)

    tokens_per_step = args.batch_size * args.seq_len * args.grad_accum_steps
    print(f"\nTraining:")
    print(f"  Batch size: {args.batch_size} x {args.grad_accum_steps} accum = {args.batch_size * args.grad_accum_steps} effective")
    print(f"  Sequence length: {args.seq_len}")
    print(f"  Tokens/step: {tokens_per_step:,}")
    print(f"  Max steps: {args.max_steps}")
    print(f"  Total tokens: ~{args.max_steps * tokens_per_step / 1e6:.0f}M")
    print(f"  Warmup: {args.warmup_steps} steps")
    print(f"  torch.compile: {not args.no_compile}")
    print()

    # ---- Training loop ----
    model.train()
    best_val_loss = float("inf")
    prev_val_loss = None
    t0 = time.time()
    last_heartbeat_t = t0

    for step in range(args.max_steps):
        current_lr = set_lr(step)

        loss_accum = 0.0
        for _micro_step in range(args.grad_accum_steps):
            x, y = train_loader.next_batch()
            with torch.autocast("cuda", dtype=torch.bfloat16):
                _, loss = model(x, y)
                loss = loss / args.grad_accum_steps
            loss.backward()
            loss_accum += loss.item()

        if args.grad_clip > 0:
            nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)

        for opt in optimizers:
            opt.step()
        for opt in optimizers:
            opt.zero_grad(set_to_none=True)

        if step % args.log_interval == 0:
            dt = time.time() - t0
            tokens_seen = (step + 1) * tokens_per_step
            tps = tokens_seen / dt if dt > 0 else 0
            trackio.log({"train_loss": loss_accum, "lr": current_lr, "tok_per_sec": tps, "step": step})
            last_heartbeat_t = time.time()
        elif args.heartbeat_seconds > 0 and (time.time() - last_heartbeat_t) >= args.heartbeat_seconds:
            dt = time.time() - t0
            pct = (step + 1) / args.max_steps * 100
            last_heartbeat_t = time.time()

        if step > 0 and step % args.eval_interval == 0:
            val_loss = evaluate(model, val_loader, args.eval_steps)
            best_val_loss = min(best_val_loss, val_loss)
            trackio.log({"val_loss": val_loss, "best_val_loss": best_val_loss, "step": step})
            if prev_val_loss is not None and val_loss > prev_val_loss:
                trackio.alert(
                    title="Val loss increasing",
                    text=f"Val loss rose from {prev_val_loss:.4f} to {val_loss:.4f} at step {step}",
                    level=trackio.AlertLevel.WARN,
                )
            prev_val_loss = val_loss

    # ---- Final evaluation ----
    val_loss = evaluate(model, val_loader, args.eval_steps)
    best_val_loss = min(best_val_loss, val_loss)
    total_time = time.time() - t0
    total_tokens = args.max_steps * tokens_per_step

    report = trackio.Markdown(f"""# Training Complete

| Metric | Value |
|--------|-------|
| Final val loss | {val_loss:.4f} |
| Best val loss | {best_val_loss:.4f} |
| Total time | {total_time:.1f}s ({total_time / 60:.1f}min) |
| Total tokens | {total_tokens / 1e6:.0f}M |
| Throughput | {total_tokens / total_time / 1e3:.1f}K tok/s |
""")
    trackio.log({"val_loss": val_loss, "best_val_loss": best_val_loss, "step": args.max_steps, "report": report})

    trackio.finish()


if __name__ == "__main__":
    main()
