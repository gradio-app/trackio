# Adam: A Method for Stochastic Optimization (Kingma & Ba, ICLR 2015)

```bash
lake build   # about 5 seconds
```

| File | What it is |
|---|---|
| `Spec.lean` | Algorithm 1 for one coordinate, in exact rational arithmetic with interval square roots, and the paper's bounds checked on concrete gradient sequences |
| `train_optimizers.py` | Section 6 rerun: logistic regression and a dropout MLP on MNIST, a dropout CNN on CIFAR-10; Adam vs SGD-Nesterov, Adagrad, RMSProp, AdaDelta; a learning-rate grid on seed 0, the best rate on seeds 1 and 2 |
| `AdamRuns.lean` | `trackio export --format lean` of the 67 runs the script logged on Hugging Face Jobs |
| `Conformance.lean` | The code that ran implements Algorithm 1 |
| `Claims.lean` | Section 6's sentences, checked against the runs |

The runs are in the bucket `abidlabs/trackio-adam-data` and on the dashboard
[abidlabs/trackio-adam-optimizers](https://huggingface.co/spaces/abidlabs/trackio-adam-optimizers).
`trackio verify --project adam-optimizers --file train_optimizers.py` checks that all 67 runs
recorded this script's hash, and that the job that logged them executed the same file.

## Results

**The math (`Spec.lean`)**

- Section 2.1's bound on the effective step, `|Δt| ≤ α(1−β₁)/√(1−β₂)` (or `≤ α`), is false:
  gradients growing by 10/9 per step exceed it at the default β's, and two gradients exceed it
  in the equality and "otherwise" cases. It holds for the paper's own worst case (a single spike).
- Section 7.1's AdaMax bound `|Δt| ≤ α` is false: two gradients give 1.0005α, and a
  geometrically shrinking sequence passes 1.009α (the limit is 111/110 α).
- Theorem 4.1 is false: on Reddi, Kale & Kumar's counterexample, which meets all of its
  assumptions, Adam's regret after 90 steps (≈127.4) exceeds the theorem's bound (≈114.8).
  The proof's step `Γ_t ≥ 0` fails at 60 of the 89 steps.

**The code (`Conformance.lean`)**

- Every one of the 19 Adam runs logged a probe: `torch.optim.Adam` on fixed gradients for ten
  steps. All 30 values agree with Lean's Algorithm 1 to within 1e-12, a tolerance that rejects
  ε inside the square root and Adam without bias correction.
- All 67 runs record one script hash and one Hugging Face Job.

**The experiments (`Claims.lean`)**

Every chosen learning rate is the grid's best and lies strictly inside its grid, and every
result is a mean over three seeds. (A first run had five optimizers' best rates at a grid
edge; this theorem is what caught it.)

| Paper says | Rerun |
|---|---|
| 6.1 Adam "yields similar convergence as SGD with momentum" | ✅ within 0.5% from epoch 2 on |
| 6.1 "both converge faster than Adagrad" | ❌ Adagrad is below SGD at every epoch and below Adam for the first 3; all three end within 0.2%, not significantly different |
| 6.2 "Adam shows better convergence than other methods" | ⚠️ better than SGD, Adagrad and AdaDelta; RMSProp is lower at 19 of 20 epochs (difference not significant) |
| 6.3 "Adam and SGD eventually converge considerably faster than Adagrad" | ✅ below Adagrad at every epoch, ending at less than half its cost |
| 6.3 "Adam shows marginal improvement over SGD with momentum" | ⚠️ 0.1% lower at the last epoch, not significant; SGD was lower at epochs 2–14 |
| 6.3 "v̂_t vanishes to zeros after a few epochs and is dominated by the ε" | ❌ at most 6% of coordinates have √v̂ < ε at any epoch; the median √v̂ is over 20,000 ε |
| 6.3 "both Adam and Adagrad make rapid progress ... in the initial stage" | ❌ Adagrad has the highest cost of the three in each of the first 3 epochs |

The rerun is smaller than the paper's (20, 20 and 15 epochs instead of 45, 200 and 45;
per-channel standardization instead of whitening for CIFAR-10), so a ❌ means the claim does
not hold in this setting, not that the paper misreported its own runs. The ε claim is the
exception: it is about the scale of gradients, which is off by four orders of magnitude.
