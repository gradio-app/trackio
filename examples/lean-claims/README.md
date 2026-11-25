# Verifying "Attention Is All You Need" with Trackio and Lean

Claims in an empirical paper rest on four things. This example checks each one:

| Layer | Question | How it's checked |
| --- | --- | --- |
| Model | Is the model the paper's architecture? | The model is a Lean program (`Model.lean`). `lake exe codegen` turns it into the PyTorch that trains (`generated_model.py`), and `ModelProofs.lean` proves properties of it. |
| Method | Does the code that ran behave like the paper's equations? | `Spec.lean` encodes Sections 3.2 and 5.3. Runs log facts about themselves to Trackio, and `Conformance.lean` proves they match the spec. |
| Provenance | Did that code produce these logs? | `trackio.init` records the SHA-256 of the script and of every local module it imports (here, `generated_model.py`), plus the HF Job. `trackio verify` matches them against local files and against what HF Jobs ran. |
| Conclusions | Do the paper's sentences follow from the results? | `Claims.lean` proves each Table 3 sentence, or its negation, from the logs exported by `trackio export --format lean`. |

`PaperTables.lean` also checks the paper's text against its own tables. `lake build`
checks everything with Lean 4.36 and no Mathlib, in about 80 seconds (most of it is the
no-leak theorem). A false claim, a changed number, non-conforming code, or a model
that leaks fails the build. `lake exe check` evaluates the model properties in under a
second and names any that fail; use it while editing `Model.lean`, because Lean's
kernel is slow to reject a false property (see "Findings").

## Reproduce

```bash
cd examples/lean-claims
lake exe codegen                       # Model.lean -> generated_model.py
lake exe check                         # model properties, fast
python check_generated.py              # generated model vs. the hand-written one
cd ../..

# Train on HF Jobs (12 runs, ~11 minutes on an A10G)
uv build --wheel -o dist
python examples/lean-claims/run_on_hf_jobs.py --trackio-wheel dist/trackio-*.whl \
    --bucket <user>/attention-ablation-data --space <user>/attention-ablation

# Fetch the logs, check provenance, export, prove
python -c "from trackio.bucket_storage import download_bucket_to_trackio_dir as d; d('<user>/attention-ablation-data')"
trackio verify --project attention-ablation \
    --file examples/lean-claims/train_ablation.py --file examples/lean-claims/generated_model.py
trackio export --project attention-ablation --format lean \
    --metrics "model/params,dev/*,test/bleu,train/lr,probe/*" \
    --output examples/lean-claims/AttentionAblation.lean
cd examples/lean-claims && lake build
```

## Model: a Lean program that becomes PyTorch (`Model.lean`, `Codegen.lean`, `ModelProofs.lean`)

The Transformer is written once, as a Lean program of 24 primitive operations
(embedding, linear, split/merge heads, `QKᵀ`, `/√d_k`, masks, softmax, layer norm,
dropout, tied output projection, label-smoothed cross-entropy). Section 3.2's
attention reads like Equation 1:

```lean
def scaledDotProductAttention (q k v dk : Nat) (mask : Mask) : Build Nat := do
  let s ← emit (.scores q k)
  let s ← emit (.scaleInvSqrt dk s)
  let s ← match mask with ...
  let p ← emit (.softmax s)
  emit (.weighted p v)
```

Each operation has three meanings: its shape, which input tokens each output position
can depend on, and the one PyTorch line it becomes. `lake exe codegen` writes
`generated_model.py` (about 2,000 lines, one per operation). `train_ablation.py`
defines no model of its own; it trains the generated classes and logs their `config`.

Proven about that program, for all four variants:

- `programs_typecheck`, `decoder_output_shape`: every step has a shape; logits are
  `[batch, target length, 8000]`.
- `param_count_matches_formula`, `param_counts`: the parameter count derived from the
  program equals `PaperTables`' architecture formula and the counts the runs logged
  (7,568,384 and 6,683,648).
- `no_future_or_cross_example_leak`: the decoder's output at position `t` of example
  `b` depends only on example `b`'s source and its decoder inputs at positions `≤ t`.
  This is checked by running the program on a dependency semantics, for batches of 2 with
  source length 3 and target length 4, and for one example with lengths 2 and 6.
- `leaks_without_future_mask`, `logits_use_current_token_and_source`: removing the
  mask breaks the property, and the property isn't vacuous.

`check_generated.py` tests the code generator against the hand-written model it
replaced (`reference_model.py`): with the same weights, logits agree to 7×10⁻¹⁵ in
float64, losses are identical, and greedy translations match, for every variant.

Planted bugs:

| Bug | Caught by |
| --- | --- |
| Decoder self-attention without the future mask (in `Model.lean`) | `no_future_or_cross_example_leak` (and `lake exe check`) |
| `merge_heads` without the transpose (in the code generator) | `check_generated.py` (logits off by 3.2) and `attention_matches_paper` (probe off by 0.21) |

## Method: conformance to the spec (`Spec.lean`, `Conformance.lean`)

- **Attention (Section 3.2).** Each run passes the generated `ProbeAttention` through
  a fixed probe with exactly representable weights and logs the 24 outputs. `Spec.lean`
  computes `softmax(QKᵀ/√d_k)V`, multi-head concat and projection in exact rationals,
  enclosing `exp` in proven bounds. All logged outputs are within 10⁻⁶.
- **Learning rate (Section 5.3).** Every logged learning rate matches
  `d_model^-0.5 · min(n^-0.5, n · warmup^-1.5)` to 10⁻⁹.
- **Parameters and code.** Every model's logged count equals the formula, and every run
  imported the same `generated_model.py`.

## Provenance (`trackio verify`)

```
OK   base-s0: train_ablation.py sha256:9ae927d688b6  2 files recorded; local files match; job 6b07537bb6a90bbe997e8250 (COMPLETED) ran this code
```

The two files are `train_ablation.py` and `generated_model.py`. Running
`lake exe codegen` again reproduces `generated_model.py` byte for byte (SHA-256
`a46a73df…`), so the chain runs from `Model.lean` to the code each run executed.

Trackio downloads the files HF Jobs executed from the job's `jobs-artifacts` bucket,
independently of what the run recorded. This trusts HF Jobs' records, and only the job
owner can read that bucket.

## Conclusions (`Claims.lean`, 3 seeds, Multi30k, 7.6M parameters)

| Paper's sentence | Perplexity | BLEU |
| --- | --- | --- |
| One head is 0.9 BLEU worse | worse on average, not on every seed | worse on average by 0.1, not on every seed, not significant |
| Reducing d_k hurts | worse on every seed | worse on every seed, by 2.0; significant only at the lenient critical value |
| Label smoothing hurts perplexity, helps BLEU | **reversed**: helps perplexity on every seed, significant | helps on average, not on every seed, not significant |

The one-head runs span 2.9 dev BLEU across seeds, more than three times the effect the
paper reports for them. Table 3 has one run per configuration.

## The paper against itself (`PaperTables.lean`)

- No vocabulary size makes Table 3's parameter column consistent with Section 3's
  architecture. The base-sized rows need 41,004–41,208 tokens; the big model needs
  about 36K; the text says about 37K. The proof covers every `V : Nat`.
- "More than 2.0 BLEU" (Section 6.1) isn't implied by the rounded table.
- Section 6.1 says 41.0 BLEU on EN-FR; Table 2 says 41.8.
- "Bigger models are better" fails for depth in BLEU.

## Findings from building this

- **Seed-level conclusions don't survive a rerun.** The previous rerun used a
  hand-written model that computes the same function as the generated one (to 10⁻¹⁵),
  but initializes parameters in a different order and uses PyTorch's fused attention,
  so its seeds are effectively different. Between the two reruns, "one head is worse on
  every seed" flipped from true to false in both metrics, "smaller d_k is worse in BLEU
  on every seed" flipped from false to true, and the base seeds' BLEU spread went from
  2.2 to 0.4. What held in both: label smoothing improves perplexity (significantly),
  smaller d_k hurts perplexity on every seed, and no BLEU effect is significant at the
  strict critical value.
- **Lean's kernel is fast to accept and slow to reject.** With a bug planted in the
  model, proving the true statement (`noLeak … = false`) takes 3 seconds and 1.7 GB;
  the false one (`= true`) ran for 2 minutes and 17 GB and was killed inside a full
  build. `lake exe check` names the failing property in under a second.
- **A one-head variant can't detect head-merging bugs.** With `merge_heads` missing its
  transpose, the h=1 variant's logits were unchanged and greedy translations matched
  for every variant at initialization. The logits comparison in `check_generated.py`
  and the attention probe caught it.
- **Generated code must already be in its final format.** Ruff rewrites
  `-256 ** -0.5` as `-(256**-0.5)` (same value). Reformatting the generated file would
  change its hash and break provenance, so the generator emits ruff-clean code.
- **Recording local modules exposed a provenance bug.** One of PyTorch's modules
  reports a relative `__file__` (`_ops.py`), which resolved to a missing file next to
  the script and silently discarded the whole `_Code` record. Fixed, with a test.
- **The no-leak proof costs build time.** `lake build` went from about 3 seconds to
  about 80, nearly all of it the dependency theorems. It holds for the stated batch and
  sequence sizes, not for all lengths; that, and the soundness of the dependency
  semantics, would need Mathlib.

## What is still trusted

1. That `Model.lean`, `Spec.lean` and the claim statements say what the paper says
   (people review these; the model is about 150 lines).
2. The code generator's one-line translation of each operation, which
   `check_generated.py` and the attention probe test but don't prove.
3. PyTorch's kernels, and float32 versus the exact semantics.
4. That the dependency semantics is a sound over-approximation of each operation
   (argued per operation, not proven against real-valued semantics, which needs Mathlib).
5. HF Jobs' record of what it ran, and the t-table critical values.

`#print axioms` shows no `sorry` and no `native_decide`.
