# How much do language models memorize? (Morris et al., arXiv:2505.24832)

```bash
lake build   # about 5 seconds
```

| File | What it is |
|---|---|
| `Paper.lean` | Tables 1–4, the Section 5 scaling law and statements in the text, transcribed from the LaTeX source of v3 and checked against each other |
| `train_capacity.py` | Section 3's capacity experiment: GPT-2 models of 1 or 2 layers and width 32 or 64, trained in bf16 on N uniformly random sequences (V = 2048, S = 64), four values of N per model |
| `MemorizationCapacity.lean` | `trackio export --format lean` of the 16 runs the script logged on Hugging Face Jobs |
| `Claims.lean` | Section 3's claims, checked against the runs |

The four models trained in four parallel jobs, one bucket each
(`abidlabs/trackio-memorization-data-{1x32,2x32,1x64,2x64}`). Their databases were merged
into one project, `abidlabs/trackio-memorization-data`, shown on the dashboard
[abidlabs/trackio-memorization-capacity](https://huggingface.co/spaces/abidlabs/trackio-memorization-capacity).
`trackio verify --project memorization-capacity --file train_capacity.py` checks that all 16
runs recorded this script's hash and that each of the four jobs executed the same file.

## Results

**The paper against itself (`Paper.lean`)**

| Paper says | Check |
|---|---|
| Table 1's parameter counts, α = capacity / params, and the means 3.83 and 3.51 | ✅ all consistent |
| 3.2 "our models consistently memorize between 3.5 and 3.6 bits per parameter" | ❌ 3 of the 16 models in Table 1 do in bf16, none in fp32; bf16 spans 2.86–3.94 |
| Figure 6: α = 3.64 ± 0.1 in half precision (Appendix A.1 uses 3.642) | ❌ Table 1's bf16 mean is 3.51, outside ± 0.1 |
| 3.2 the "8M parameter" model memorizes 3.56–3.65 × 10⁶ bits | ❌ that is at most 0.46 bits per parameter |
| Figure 5: the 6.86M-parameter model has "a capacity of 23.9 MB" | ❌ 27.9 bits per parameter as megabytes; as megabits it still disagrees with Table 1 (2.51 × 10⁷) |
| A.1 the expected columns of Tables 3 and 4 use α = 3.642 | ❌ every row matches α = 3.54, none matches 3.642 |
| Tables 3 and 4 | ❌ the same configuration (N = 4096, S = 64, V = 2048) reports 2.29 × 10⁶ and 2.39 × 10⁶ bits |
| A.1 average errors of 1.7% (scaling S) and 1.8% (scaling V) | ⚠️ 1.70% ✅; 1.48% for V |
| Table 2's second model is "GPT2-Medium" | ❌ its parameter count is GPT-2 small's (12 layers, width 768), as the text says |
| 5: the membership-inference law F₁ decays from 1 to 0.5 as the dataset grows | ❌ as printed it tends to 1.006, and at Table 2's sizes it predicts the rows in reverse order; with the capacity/data ratio inverted, one constant reproduces all of Table 2 |
| 5.2.2 at 100 tokens per parameter the law "would imply" F₁ = 0.5 | ❌ as printed, above 0.99 |
| The ICML version of the law | ❌ fixes the limit, but `c₃ = −33.14` puts σ's argument below −33 everywhere, so it predicts 0.5 for every row |
| 5.2.2 observed F₁ "generally within 1.5 points" of the target | ❌ 4 of 6 rows are not |

**The rerun (`Claims.lean`)**

The model the script built has GPT-2's parameter count for its shape, and the data's entropy
is exactly `N · 63 · 11` bits, so memorized bits are measured in the paper's units.

| Model | Params | Paper (bf16) | Rerun | Rerun α |
|---|---|---|---|---|
| 1 layer, width 32 | 80,352 | 316k | 218k | 2.71 |
| 2 layers, width 32 | 93,056 | 331k | 262k | 2.81 |
| 1 layer, width 64 | 185,280 | 693k | 560k | 3.02 |
| 2 layers, width 64 | 235,264 | 927k | 718k | 3.05 |

| Paper says | Rerun |
|---|---|
| Models memorize small datasets completely | ✅ every model memorizes more than 99.9% of the entropy of its smallest dataset |
| Memorization plateaus at capacity as the dataset grows | ✅ over a fourfold range of N, memorized bits stay within 5% while the largest dataset is at most 26% memorized |
| Capacity is roughly proportional to parameters | ✅ capacity grows with parameter count; α varies by at most 13% across a threefold range of sizes |
| Table 1's capacities; α ≈ 3.5–3.6 | ⚠️ not reached: our capacities are 69–81% of Table 1's and α is 2.71–3.05 |

The last row is not a contradiction. Memorized bits at the end of training are a lower bound
on capacity, and the paper trains for 10⁶ steps where we trained for 3 · 10⁴. A pilot with a
constant learning rate and 2 · 10⁴ steps reached 2.80 bits per parameter on the
2-layer, width-64 model; the cosine schedule at 3 · 10⁴ reached 3.05. Confirming 3.5–3.6 would take a schedule about 30 times longer than ours.
