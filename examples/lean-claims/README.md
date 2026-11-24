# Checking "Attention Is All You Need" with Trackio and Lean

Two Lean files, built together with `lake build`:

| File | Checks | Data |
| --- | --- | --- |
| `PaperTables.lean` | The paper's text and arithmetic against its own Tables 2–3 | Numbers transcribed from arXiv:1706.03762v7 |
| `Claims.lean` | The paper's Table 3 sentences against a real rerun | `AttentionAblation.lean`, exported from Trackio |

If a claim doesn't follow from its data, the build fails.

## Reproduce

```bash
pip install torch sacrebleu datasets tokenizers
python examples/lean-claims/train_ablation.py --variants base h1 dk8 ls0 --seeds 0 1
trackio export --project attention-ablation --format lean \
    --metrics model/params,dev/bleu,dev/ppl,test/bleu \
    --output examples/lean-claims/AttentionAblation.lean
cd examples/lean-claims && lake build
```

Training logs to `examples/lean-claims/.trackio/`; set `TRACKIO_DIR` to override.
Each run is the paper's architecture, implemented from scratch (post-LN encoder-decoder,
sinusoidal positions, one shared embedding/softmax matrix, Adam with β₂ = 0.98 and
inverse-sqrt warmup, label smoothing). It uses N = 3, d_model = 256 and d_ff = 1024,
trained for 10 epochs on Multi30k EN→DE. That's about 8 minutes per run on an Apple
M5. Each run logs training loss, learning rate, throughput, dev loss and perplexity
every epoch, dev BLEU every 5 epochs, test BLEU, and the parameter count. The learning
rate was tuned on the base config only, in a separate `attention-ablation-lr-pilot`
project.

## What the proofs found

**In the paper itself** (`PaperTables.lean`):

- No vocabulary size makes Table 3's params column consistent with the architecture
  in Section 3. The ten base-sized rows agree with each other only for V between 41004
  and 41208 (the text says "about 37000"). The big model's 213M needs V of about 36K.
  The proof is over all `V : Nat`. The same formula reproduces all eight real models'
  parameter counts exactly (`Claims.params_match_formula`).
- "More than 2.0 BLEU" over the best prior EN-DE result rests on 28.4 − 26.36 = 2.04.
  An unrounded 28.36 would print as 28.4 and give exactly 2.0.
- Section 6.1 gives EN-FR big as 41.0; Table 2 and the abstract give 41.8.
- "Bigger models are better" (row C) fails for depth in BLEU (N = 8 scores below N = 6).
  Read as "more parameters is better", it also fails in perplexity.
- The FLOPs in Table 2 follow from the stated formula with 12 h and 3.5 days. The
  0.4 s step time in Section 5.2 implies 11.1 h, which would print as 3.0·10¹⁸.

**In the rerun** (`Claims.lean`, 2 seeds per variant):

| Paper's sentence | Perplexity | BLEU |
| --- | --- | --- |
| One head is worse than the best | holds, every seed | does not hold on average |
| Reducing d_k hurts | holds, every seed | reversed, every seed |
| Label smoothing hurts perplexity, helps BLEU | reversed, every seed | holds on average, not every seed |

The two base seeds differ by 0.47 dev BLEU, more than the paper's row (B) effect
(0.4). None of the differences, including the largest, is significant with two seeds.
Table 3 reports one run per configuration.

## How a claim reads

```lean
theorem small_key_better_bleu_every_seed :
    holds (everySeed base smallKey .dev_bleu fun b k => decide (b < k)) := by
  decide
```

- Logged floats become exact rationals (the shortest decimal that round-trips to the
  float64, or its exact binary value with `--exact`). No floating-point slack.
- A missing run, metric or config key makes the computation `none`, and `holds none` is
  false. Missing data can't make a claim succeed.
- `decide` evaluates the claim in the Lean kernel. `#print axioms` shows only Lean's
  standard axioms: no `sorry` and no `native_decide`.
- `digest` ties the module to the logs. Re-export and compare it to confirm the module
  wasn't edited.

## What this does not establish

Lean proves claims follow from logged numbers. It doesn't prove the numbers came from
the training the config describes. It doesn't check that a test-statistic critical
value (taken from a t-table) is right. And it doesn't make small-scale results speak
for the paper's scale.
