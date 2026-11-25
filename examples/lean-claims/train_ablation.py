# /// script
# requires-python = ">=3.10"
# dependencies = ["torch", "sacrebleu", "datasets", "tokenizers"]
# ///
"""Rerun Table 3 rows (A), (B) and the label-smoothing rows of (D) from
"Attention Is All You Need" at small scale, logging every run to Trackio.

The model is not defined here. It is `generated_model.py`, which `lake exe codegen`
writes from the Transformer program in `Model.lean`, so the theorems in
`ModelProofs.lean` are about the code that trains. Training is Multi30k
English->German with Adam (beta2=0.98) and the inverse-sqrt warmup schedule. Each run
logs training loss, learning rate, throughput, dev loss/perplexity/BLEU every epoch,
test BLEU, the model's parameter count, and an attention probe: the generated
`ProbeAttention` on fixed, exactly representable inputs, which `Conformance.lean`
checks against the paper's attention in `Spec.lean`.

    cd examples/lean-claims && lake exe codegen
    python examples/lean-claims/train_ablation.py --variants base h1 --seeds 0 --epochs 1

To run on Hugging Face Jobs, see `run_on_hf_jobs.py`.
"""

import argparse
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("TRACKIO_DIR", str(HERE / ".trackio"))

import sacrebleu  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from datasets import load_dataset  # noqa: E402
from generated_model import MODELS, ProbeAttention  # noqa: E402
from tokenizers import SentencePieceBPETokenizer, Tokenizer  # noqa: E402

import trackio  # noqa: E402
from trackio.bucket_storage import (  # noqa: E402
    create_bucket_if_not_exists,
    upload_project_to_bucket,
)

PROJECT = "attention-ablation"
PAD, BOS, EOS, UNK = 0, 1, 2, 3
SPECIALS = ["<pad>", "<s>", "</s>", "<unk>"]


def build_tokenizer(train, vocab_size: int, cache: Path) -> SentencePieceBPETokenizer:
    path = cache / f"bpe-{vocab_size}.json"
    if path.exists():
        return Tokenizer.from_file(str(path))
    tokenizer = SentencePieceBPETokenizer()
    tokenizer.train_from_iterator(
        [row["en"] for row in train] + [row["de"] for row in train],
        vocab_size=vocab_size,
        special_tokens=SPECIALS,
        min_frequency=2,
    )
    cache.mkdir(parents=True, exist_ok=True)
    tokenizer.save(str(path))
    return tokenizer


def encode(tokenizer, rows, max_len: int = 100):
    src = tokenizer.encode_batch([row["en"] for row in rows])
    tgt = tokenizer.encode_batch([row["de"] for row in rows])
    return [
        (s.ids[:max_len], [BOS] + t.ids[: max_len - 2] + [EOS])
        for s, t in zip(src, tgt)
    ]


def batches(pairs, batch_tokens: int, shuffle: bool, rng: random.Random):
    order = sorted(range(len(pairs)), key=lambda i: (len(pairs[i][0]), rng.random()))
    groups, current, longest = [], [], 0
    for i in order:
        longest = max(longest, len(pairs[i][0]), len(pairs[i][1]))
        if current and longest * (len(current) + 1) > batch_tokens:
            groups.append(current)
            current, longest = [], max(len(pairs[i][0]), len(pairs[i][1]))
        current.append(i)
    if current:
        groups.append(current)
    if shuffle:
        rng.shuffle(groups)
    yield from groups


def pad(seqs, device):
    width = max(len(s) for s in seqs)
    out = torch.full((len(seqs), width), PAD, dtype=torch.long)
    for i, s in enumerate(seqs):
        out[i, : len(s)] = torch.tensor(s)
    return out.to(device)


PROBE_LENGTH, PROBE_D_MODEL = 3, 4


def probe_weight(row: int, col: int, salt: int) -> float:
    return (((3 * row + 2 * col + salt) % 5) - 2) / 8


def probe_input(t: int, c: int) -> float:
    return (((2 * t + 3 * c) % 5) - 2) / 2


@torch.no_grad()
def attention_probe(device):
    attn = ProbeAttention().to(device)
    for salt, name in enumerate(["probe_wq", "probe_wk", "probe_wv", "probe_wo"], 1):
        rows, cols = attn.params[name].shape
        attn.params[name].copy_(
            torch.tensor(
                [[probe_weight(r, c, salt) for c in range(cols)] for r in range(rows)]
            )
        )
    x = torch.tensor(
        [
            [
                [probe_input(t, c) for c in range(PROBE_D_MODEL)]
                for t in range(PROBE_LENGTH)
            ]
        ],
        device=device,
    )
    outputs = {"self": attn.unmasked(x), "causal": attn.masked(x)}
    return {
        f"probe/{kind}/t{t}_c{c}": out[0, t, c].item()
        for kind, out in outputs.items()
        for t in range(PROBE_LENGTH)
        for c in range(PROBE_D_MODEL)
    }


def logits_for(model, src, tgt_in):
    return model.decode(tgt_in, model.encode(src), src)


@torch.no_grad()
def greedy(model, src, max_extra: int = 50):
    memory = model.encode(src)
    out = torch.full((src.shape[0], 1), BOS, dtype=torch.long, device=src.device)
    done = torch.zeros(src.shape[0], dtype=torch.bool, device=src.device)
    for _ in range(src.shape[1] + max_extra):
        next_id = model.decode(out, memory, src)[:, -1].argmax(-1)
        next_id = torch.where(done, torch.full_like(next_id, PAD), next_id)
        out = torch.cat([out, next_id[:, None]], dim=1)
        done |= next_id == EOS
        if done.all():
            break
    return out[:, 1:]


def evaluate(model, pairs, refs, tokenizer, device, batch_tokens, with_bleu=True):
    model.eval()
    total_nll, total_tokens, hyps = 0.0, 0, {}
    for ids in batches(pairs, batch_tokens, False, random.Random(0)):
        src = pad([pairs[i][0] for i in ids], device)
        tgt = pad([pairs[i][1] for i in ids], device)
        with torch.no_grad():
            logits = logits_for(model, src, tgt[:, :-1])
            nll = F.cross_entropy(
                logits.reshape(-1, logits.shape[-1]),
                tgt[:, 1:].reshape(-1),
                ignore_index=PAD,
                reduction="sum",
            )
        total_nll += nll.item()
        total_tokens += (tgt[:, 1:] != PAD).sum().item()
        if not with_bleu:
            continue
        for i, row in zip(ids, greedy(model, src).tolist()):
            row = row[: row.index(EOS)] if EOS in row else row
            hyps[i] = tokenizer.decode([t for t in row if t != PAD])
    model.train()
    loss = total_nll / total_tokens
    if not with_bleu:
        return loss, math.exp(loss), None
    bleu = sacrebleu.corpus_bleu([hyps[i] for i in range(len(pairs))], [refs]).score
    return loss, math.exp(loss), bleu


def train_run(variant, seed, data, tokenizer, args, device):
    torch.manual_seed(seed)
    rng = random.Random(seed)
    model = MODELS[variant]().to(device)
    config = dict(model.config)
    if config["vocab_size"] != tokenizer.get_vocab_size():
        raise SystemExit("The tokenizer's vocabulary differs from the model's.")
    params = sum(p.numel() for p in model.parameters())
    optimizer = torch.optim.Adam(
        model.parameters(), lr=1.0, betas=(0.9, 0.98), eps=1e-9
    )
    scale = config["d_model"] ** -0.5
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: args.lr_factor
        * scale
        * min((step + 1) ** -0.5, (step + 1) * args.warmup**-1.5),
    )
    trackio.init(
        project=args.project,
        name=f"{variant}-s{seed}{args.run_suffix}",
        group=variant,
        config={
            **config,
            "variant": variant,
            "seed": seed,
            "epochs": args.epochs,
            "batch_tokens": args.batch_tokens,
            "warmup": args.warmup,
            "bleu_every": args.bleu_every,
            "lr_factor": args.lr_factor,
            "device": str(device),
        },
    )
    trackio.log({"model/params": params, **attention_probe(device)}, step=0)
    step, window_tokens, window_start = 0, 0, time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        for ids in batches(data["train"], args.batch_tokens, True, rng):
            src = pad([data["train"][i][0] for i in ids], device)
            tgt = pad([data["train"][i][1] for i in ids], device)
            loss = model.loss(logits_for(model, src, tgt[:, :-1]), tgt[:, 1:])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            schedule.step()
            step += 1
            window_tokens += (tgt != PAD).sum().item() + (src != PAD).sum().item()
            if step % 50 == 0:
                elapsed = time.perf_counter() - window_start
                trackio.log(
                    {
                        "train/loss": loss.item(),
                        "train/lr": schedule.get_last_lr()[0],
                        "train/tokens_per_sec": window_tokens / elapsed,
                    },
                    step=step,
                )
                window_tokens, window_start = 0, time.perf_counter()
        with_bleu = epoch % args.bleu_every == 0 or epoch == args.epochs
        dev_loss, dev_ppl, dev_bleu = evaluate(
            model,
            data["dev"],
            data["dev_refs"],
            tokenizer,
            device,
            args.batch_tokens,
            with_bleu,
        )
        metrics = {"epoch": epoch, "dev/loss": dev_loss, "dev/ppl": dev_ppl}
        if with_bleu:
            metrics["dev/bleu"] = dev_bleu
        trackio.log(metrics, step=step)
        print(
            f"{variant}-s{seed}{args.run_suffix} epoch {epoch}: dev ppl {dev_ppl:.2f} bleu {dev_bleu}",
            flush=True,
        )
    _, _, test_bleu = evaluate(
        model, data["test"], data["test_refs"], tokenizer, device, args.batch_tokens
    )
    trackio.log({"test/bleu": test_bleu}, step=step)
    trackio.finish()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=PROJECT)
    parser.add_argument("--run-suffix", default="")
    parser.add_argument("--variants", nargs="+", default=list(MODELS))
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--bleu-every", type=int, default=5)
    parser.add_argument("--batch-tokens", type=int, default=4000)
    parser.add_argument("--warmup", type=int, default=400)
    parser.add_argument("--lr-factor", type=float, default=1.0)
    parser.add_argument("--vocab-size", type=int, default=8000)
    parser.add_argument("--cache-dir", default=str(HERE / ".cache"))
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Train this many seeds at once, each in its own process",
    )
    parser.add_argument(
        "--upload-bucket",
        help="After training, upload the project's database to this HF bucket",
    )
    parser.add_argument(
        "--generated-model",
        help="Path of generated_model.py, so HF Jobs stages it next to this script "
        "(set by run_on_hf_jobs.py; the import finds it by name)",
    )
    parser.add_argument(
        "--trackio-wheel",
        help="Trackio wheel the HF Job installed (set by run_on_hf_jobs.py; not used here)",
    )
    parser.add_argument(
        "--static-space",
        help="After training, publish the project to this static Trackio Space",
    )
    args = parser.parse_args()

    if args.workers > 1 and len(args.seeds) > 1:
        run_seeds_in_parallel(args)
    else:
        train_all(args)
    if args.upload_bucket:
        create_bucket_if_not_exists(args.upload_bucket, private=False)
        upload_project_to_bucket(args.project, args.upload_bucket)
        print(f"Uploaded {args.project} to hf://buckets/{args.upload_bucket}")
    if args.static_space:
        trackio.sync(project=args.project, space_id=args.static_space, sdk="static")


def run_seeds_in_parallel(args):
    shared = [
        "--project",
        args.project,
        f"--run-suffix={args.run_suffix}",
        "--variants",
        *args.variants,
        "--epochs",
        str(args.epochs),
        "--bleu-every",
        str(args.bleu_every),
        "--batch-tokens",
        str(args.batch_tokens),
        "--warmup",
        str(args.warmup),
        "--lr-factor",
        str(args.lr_factor),
        "--vocab-size",
        str(args.vocab_size),
        "--cache-dir",
        args.cache_dir,
    ]
    pending = list(args.seeds)
    running = []
    while pending or running:
        while pending and len(running) < args.workers:
            seed = pending.pop(0)
            cmd = [
                sys.executable,
                os.path.abspath(__file__),
                *shared,
                "--seeds",
                str(seed),
            ]
            running.append(subprocess.Popen(cmd))
            time.sleep(5)
        for proc in list(running):
            if proc.poll() is not None:
                running.remove(proc)
                if proc.returncode != 0:
                    raise SystemExit(f"Seed worker failed: {' '.join(proc.args)}")
        time.sleep(2)


def train_all(args):
    device = torch.device(
        "mps"
        if torch.backends.mps.is_available()
        else "cuda"
        if torch.cuda.is_available()
        else "cpu"
    )
    ds = load_dataset("bentrevett/multi30k")
    tokenizer = build_tokenizer(ds["train"], args.vocab_size, Path(args.cache_dir))
    data = {
        "train": encode(tokenizer, ds["train"]),
        "dev": encode(tokenizer, ds["validation"]),
        "test": encode(tokenizer, ds["test"]),
        "dev_refs": [row["de"] for row in ds["validation"]],
        "test_refs": [row["de"] for row in ds["test"]],
    }
    for seed in args.seeds:
        for variant in args.variants:
            train_run(variant, seed, data, tokenizer, args, device)


if __name__ == "__main__":
    main()
