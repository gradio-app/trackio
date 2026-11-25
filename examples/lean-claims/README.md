# Verifying "Attention Is All You Need" with Trackio and Lean

Claims in an empirical paper rest on three things. This example checks each one:

| Layer | Question | How it's checked |
| --- | --- | --- |
| Method | Does the code implement the paper? | `Spec.lean` encodes Sections 3 and 5.3. The code logs facts about itself to Trackio, and `Conformance.lean` proves they match the spec. |
| Provenance | Did that code produce these logs? | `trackio.init` records the script's SHA-256 and the HF Job. `trackio verify` matches it against the repo and against the script HF Jobs ran. |
| Conclusions | Do the paper's sentences follow from the results? | `Claims.lean` proves each Table 3 sentence, or its negation, from the logs exported by `trackio export --format lean`. |

`PaperTables.lean` also checks the paper's text against its own tables. `lake build`
checks all of it in about 3 seconds with Lean 4.36 and no Mathlib. A false claim, a
changed number, or non-conforming code fails the build.

## Reproduce

```bash
# Train on HF Jobs (12 runs, ~11 minutes on an A10G)
uv build --wheel -o dist
python examples/lean-claims/run_on_hf_jobs.py --trackio-wheel dist/trackio-*.whl \
    --bucket <user>/attention-ablation-data --space <user>/attention-ablation

# Fetch the logs, check provenance, export, prove
python -c "from trackio.bucket_storage import download_bucket_to_trackio_dir as d; d('<user>/attention-ablation-data')"
trackio verify --project attention-ablation --file examples/lean-claims/train_ablation.py
trackio export --project attention-ablation --format lean \
    --metrics "model/params,dev/*,test/bleu,train/lr,probe/*" \
    --output examples/lean-claims/AttentionAblation.lean
cd examples/lean-claims && lake build
```

`train_ablation.py` also runs locally: `python examples/lean-claims/train_ablation.py
--variants base h1 dk8 ls0 --seeds 0 1 2`.

## Method: conformance to the spec (`Spec.lean`, `Conformance.lean`)

- **Learning rate (Section 5.3).** Every logged learning rate matches
  `d_model^-0.5 · min(n^-0.5, n · warmup^-1.5)` to 10⁻⁹. The check is done on the
  squared schedule, so it's exact rational arithmetic.
- **Attention (Section 3.2).** Each run passes its real `MultiHeadAttention` (and the
  decoder's causal mask) through a fixed probe with exactly representable weights and
  logs the 24 outputs. `Spec.lean` computes the paper's `softmax(QKᵀ/√d_k)V`,
  multi-head concat and projection in exact rationals, enclosing `exp` in proven
  bounds (a Taylor sum plus a Lagrange remainder). All logged outputs are within 10⁻⁶.
- **Parameters.** Every model's logged count equals the architecture formula.

Planted bugs, each run for real, fail the matching theorem:

| Bug | Caught by |
| --- | --- |
| Scale by 1/d_k instead of 1/√d_k | `attention_matches_paper` |
| Concatenate heads without the transpose | `attention_matches_paper` |
| Drop the decoder's causal mask (dev perplexity *improves*, 23 vs ~105) | `attention_matches_paper` |
| Warmup exponent −1.25 instead of −1.5 | `lr_schedule_matches_paper` |

These are tests on the probe, not proofs about the code for every input.

## Provenance (`trackio verify`)

```
OK   base-s0: train_ablation.py sha256:9df1c0b71099  local file matches; job 6b062a43d0582cfbbefd4b26 (COMPLETED) ran this code
```

Trackio downloads the script HF Jobs executed from the job's `jobs-artifacts` bucket,
independently of what the run recorded. This trusts HF Jobs' records, and only the job
owner can read that bucket.

## Conclusions (`Claims.lean`, 3 seeds, Multi30k, 7.6M parameters)

| Paper's sentence | Perplexity | BLEU |
| --- | --- | --- |
| One head is 0.9 BLEU worse | worse on every seed | worse on every seed, but by 0.2, not significant |
| Reducing d_k hurts | worse on every seed | worse on average, not every seed |
| Label smoothing hurts perplexity, helps BLEU | **reversed**: helps perplexity on every seed, significant | helps on average, not every seed, not significant |

The three base seeds span 2.2 dev BLEU, more than twice the largest row (A)/(B) effect
the paper reports. Table 3 has one run per configuration.

## The paper against itself (`PaperTables.lean`)

- No vocabulary size makes Table 3's parameter column consistent with Section 3's
  architecture. The base-sized rows need 41,004–41,208 tokens; the big model needs
  about 36K; the text says about 37K. The proof covers every `V : Nat`.
- "More than 2.0 BLEU" (Section 6.1) isn't implied by the rounded table.
- Section 6.1 says 41.0 BLEU on EN-FR; Table 2 says 41.8.
- "Bigger models are better" fails for depth in BLEU.

## What is still trusted

1. The translation of the paper's text into `Spec.lean` and the claim statements,
   which people review.
2. HF Jobs' record of what it ran.
3. That conformance on the probe reflects the code's behavior in training.
4. The t-table critical values.

`#print axioms` shows no `sorry` and no `native_decide`. Kernel checks use
`decide +kernel`; when one is false, Lean reports it as "application type mismatch" on
that theorem.
