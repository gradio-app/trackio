"""Check the model generated from Model.lean against the hand-written one it replaced.

For each variant, the generated model's weights are copied into
`reference_model.Transformer`, and the two must compute the same logits (in
float64), the same label-smoothed loss, the same greedy translations, and the same
attention-probe outputs. Exits non-zero on any mismatch.

    python examples/lean-claims/check_generated.py
"""

import sys
from pathlib import Path

import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import reference_model as ref  # noqa: E402
from generated_model import MODELS, ProbeAttention  # noqa: E402
from train_ablation import (  # noqa: E402
    PROBE_D_MODEL,
    PROBE_LENGTH,
    greedy,
    logits_for,
    probe_input,
    probe_weight,
)


def reference_name(name: str) -> str:
    if name == "embedding":
        return "embed.weight"
    part, rest = name.split("_", 1)
    stack, i = (
        ("encoder", part[3:]) if part.startswith("enc") else ("decoder", part[3:])
    )
    block, leaf = rest.rsplit("_", 1)
    module = {"attn": "attn", "self": "self_attn", "cross": "cross_attn"}.get(
        block, block
    )
    if leaf in ("wq", "wk", "wv", "wo"):
        return f"{stack}.{i}.{module}.w_{leaf[1]}.weight"
    if leaf in ("w1", "w2", "b1", "b2"):
        kind = "weight" if leaf[0] == "w" else "bias"
        return f"{stack}.{i}.ffn.w_{leaf[1]}.{kind}"
    return f"{stack}.{i}.{block}.{'weight' if leaf == 'gain' else 'bias'}"


def sample_batch(vocab, generator):
    src = torch.randint(4, vocab, (4, 9), generator=generator)
    tgt = torch.randint(4, vocab, (4, 8), generator=generator)
    src[1, 6:] = ref.PAD
    src[3, 4:] = ref.PAD
    tgt[:, 0] = ref.BOS
    tgt[2, 5:] = ref.PAD
    return src, tgt


def check_variant(name, model_cls):
    torch.manual_seed(0)
    generated = model_cls().double().eval()
    reference = ref.Transformer(generated.config, generated.config["vocab_size"])
    reference = reference.double().eval()
    ref_params = dict(reference.named_parameters())
    mapping = {n: reference_name(n) for n in generated.params}
    assert sorted(mapping.values()) == sorted(ref_params), f"{name}: parameter names"
    with torch.no_grad():
        for gen_name, ref_name in mapping.items():
            assert ref_params[ref_name].shape == generated.params[gen_name].shape
            ref_params[ref_name].copy_(generated.params[gen_name])

    src, tgt = sample_batch(
        generated.config["vocab_size"], torch.Generator().manual_seed(1)
    )
    with torch.no_grad():
        gen_logits = logits_for(generated, src, tgt[:, :-1])
        ref_logits = reference(src, tgt[:, :-1])
        gen_loss = generated.loss(gen_logits, tgt[:, 1:])
        ref_loss = F.cross_entropy(
            ref_logits.reshape(-1, ref_logits.shape[-1]),
            tgt[:, 1:].reshape(-1),
            ignore_index=ref.PAD,
            label_smoothing=generated.config["eps_ls"],
        )
    gen_tokens = greedy(generated, src, max_extra=6)
    ref_tokens = reference.greedy(src, max_extra=6)
    result = {
        "params": sum(p.numel() for p in generated.parameters()),
        "max |Δ logits|": (gen_logits - ref_logits).abs().max().item(),
        "|Δ loss|": (gen_loss - ref_loss).abs().item(),
        "greedy tokens equal": torch.equal(gen_tokens, ref_tokens),
    }
    ok = (
        result["max |Δ logits|"] < 1e-9
        and result["|Δ loss|"] < 1e-9
        and result["greedy tokens equal"]
        and result["params"] == sum(p.numel() for p in reference.parameters())
    )
    return ok, result


@torch.no_grad()
def check_probe():
    generated = ProbeAttention().double()
    reference = ref.MultiHeadAttention(PROBE_D_MODEL, 2, 4, 2).double()
    for salt, (gen_name, linear) in enumerate(
        zip(
            ["probe_wq", "probe_wk", "probe_wv", "probe_wo"],
            [reference.w_q, reference.w_k, reference.w_v, reference.w_o],
        ),
        1,
    ):
        rows, cols = linear.weight.shape
        w = torch.tensor(
            [[probe_weight(r, c, salt) for c in range(cols)] for r in range(rows)],
            dtype=torch.float64,
        )
        linear.weight.copy_(w)
        generated.params[gen_name].copy_(w)
    x = torch.tensor(
        [
            [
                [probe_input(t, c) for c in range(PROBE_D_MODEL)]
                for t in range(PROBE_LENGTH)
            ]
        ],
        dtype=torch.float64,
    )
    mask = ref.causal_mask(PROBE_LENGTH, x.device)[None, None]
    diff = max(
        (generated.unmasked(x) - reference(x, x, None)).abs().max().item(),
        (generated.masked(x) - reference(x, x, mask)).abs().max().item(),
    )
    return diff < 1e-12, {"max |Δ probe|": diff}


def main():
    failures = 0
    for name, model_cls in MODELS.items():
        ok, result = check_variant(name, model_cls)
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}: {result}")
    ok, result = check_probe()
    failures += not ok
    print(f"{'OK  ' if ok else 'FAIL'} probe: {result}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
