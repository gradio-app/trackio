import Trackio

/-!
# "How much do language models memorize?" against its own numbers

Numbers transcribed from the LaTeX source of arXiv:2505.24832v3 (Morris et al.,
2025): Table 1 (`table05_mem_precision.tex`), Tables 3 and 4
(`table02_memorization_pred.tex`), Table 2 (`table04_scaling_datasets.tex`), and
the text of Sections 3.2, 5.2 and Appendix A.1. Nothing here uses our own training
runs; `Claims.lean` does that.
-/

open Trackio Exact

namespace Paper

/-- Parameters of a GPT-2 model with tied input and output embeddings, learned
positions, biases, and layer norms: `V·d + S·d + L·(12d² + 13d) + 2d`. -/
def gpt2Params (L d V S : Nat) : Nat := V * d + S * d + L * (12 * d * d + 13 * d) + 2 * d

/-! ## Table 1: capacity of 16 models in fp32 and bf16 -/

structure Row1 where
  L : Nat
  d : Nat
  params : Int × Int
  capFp32 : Int × Int
  capBf16 : Int × Int
  alphaFp32 : Nat
  alphaBf16 : Nat

/-- Each printed value is a 3-digit mantissa and the power of ten of its last digit:
`(804, 2)` is 8.04 × 10⁴. Alphas are in hundredths. -/
def table1 : List Row1 :=
  [⟨1, 32, (804, 2), (339, 3), (316, 3), 423, 393⟩, ⟨1, 64, (185, 3), (727, 3), (693, 3), 392, 374⟩,
   ⟨1, 128, (469, 3), (171, 4), (169, 4), 365, 361⟩, ⟨1, 256, (133, 4), (415, 4), (383, 4), 312, 288⟩,
   ⟨2, 32, (931, 2), (387, 3), (331, 3), 416, 356⟩, ⟨2, 64, (235, 3), (960, 3), (927, 3), 408, 394⟩,
   ⟨2, 128, (667, 3), (266, 4), (260, 4), 399, 389⟩, ⟨2, 256, (212, 4), (849, 4), (776, 4), 401, 366⟩,
   ⟨4, 32, (118, 3), (465, 3), (399, 3), 392, 337⟩, ⟨4, 64, (335, 3), (134, 4), (114, 4), 398, 339⟩,
   ⟨4, 128, (106, 4), (402, 4), (375, 4), 378, 353⟩, ⟨4, 256, (370, 4), (136, 5), (130, 5), 368, 351⟩,
   ⟨8, 32, (169, 3), (512, 3), (485, 3), 302, 286⟩, ⟨8, 64, (535, 3), (205, 4), (171, 4), 383, 319⟩,
   ⟨8, 128, (186, 4), (723, 4), (649, 4), 389, 349⟩, ⟨8, 256, (686, 4), (271, 5), (251, 5), 396, 365⟩]

def val (p : Int × Int) : Q := sci p.1 p.2

/-- The printed parameter counts are GPT-2's, counting embeddings, with V = 2048 and
S = 64. -/
theorem table1_params_are_gpt2 :
    table1.all (fun r => printsAs (q (gpt2Params r.L r.d 2048 64)) r.params.1 r.params.2) = true := by
  decide +kernel

/-- `α` printed to two decimals is consistent with capacity / params for some
capacity and parameter count that print as the table shows. -/
def alphaConsistent (cap params : Int × Int) (alpha : Nat) : Bool :=
  let half := fun (p : Int × Int) => sci 1 p.2 * q 1 2
  let lo := (val cap - half cap) * Exact.inv (val params + half params)
  let hi := (val cap + half cap) * Exact.inv (val params - half params)
  decide (lo - q 1 200 ≤ q alpha 100) && decide (q alpha 100 ≤ hi + q 1 200)

theorem table1_alpha_is_capacity_over_params :
    table1.all (fun r => alphaConsistent r.capFp32 r.params r.alphaFp32 &&
      alphaConsistent r.capBf16 r.params r.alphaBf16) = true := by
  decide +kernel

/-- The table's means, 3.83 (fp32) and 3.51 (bf16), are the means of its rows. -/
theorem table1_means :
    Q.roundsTo (q (((table1.map (·.alphaFp32)).foldl (· + ·) 0 : Nat) : Int) 1600) 3.83 2 = true ∧
    Q.roundsTo (q (((table1.map (·.alphaBf16)).foldl (· + ·) 0 : Nat) : Int) 1600) 3.51 2 = true := by
  decide +kernel

/-- Section 3.2: "our models consistently memorize between 3.5 and 3.6 bits per
parameter". In bf16, the precision of the main experiments, 3 of the 16 models in
Table 1 do; in fp32, none do. -/
theorem table1_rarely_between_3_5_and_3_6 :
    (table1.filter fun r => 350 ≤ r.alphaBf16 && r.alphaBf16 ≤ 360).length = 3 ∧
    (table1.filter fun r => 350 ≤ r.alphaFp32 && r.alphaFp32 ≤ 360).length = 0 := by
  decide +kernel

/-- bf16 values span 2.86 to 3.94 bits per parameter. -/
theorem table1_bf16_range :
    (table1.map (·.alphaBf16)).foldl min 1000 = 286 ∧ (table1.map (·.alphaBf16)).foldl max 0 = 394 := by
  decide +kernel

/-- Figure 6 reports `α = 3.64` for half precision, and Appendix A.1 uses 3.642; the
half-precision mean of Table 1 is 3.51, outside the table's stated `± 0.1`. -/
theorem figure6_alpha_vs_table1_mean : decide ((3.51 : Q) + 0.1 < 3.64) = true := by decide +kernel

/-! ## Tables 3 and 4: predicted memorization when scaling S and V (Appendix A.1)

Both use 4096 sequences, 2 layers and `d = 128`, and predict memorization as
`min(capacity, H)` with `H = N·S·log₂V` and capacity `α · params`; the text says
`α = 3.642`. -/

structure Row34 where
  S : Nat
  V : Nat
  log2V : Nat
  params : Int × Int
  memorized : Int × Int
  expected : Int × Int
  errorPct : Nat

def table3 : List Row34 :=
  [⟨4, 2048, 11, (659, 3), (173, 3), (180, 3), 419⟩, ⟨8, 2048, 11, (660, 3), (354, 3), (360, 3), 180⟩,
   ⟨16, 2048, 11, (661, 3), (715, 3), (721, 3), 84⟩, ⟨32, 2048, 11, (663, 3), (144, 4), (144, 4), 41⟩,
   ⟨64, 2048, 11, (667, 3), (229, 4), (236, 4), 297⟩, ⟨128, 2048, 11, (675, 3), (236, 4), (239, 4), 124⟩,
   ⟨256, 2048, 11, (692, 3), (244, 4), (245, 4), 44⟩]

def table4 : List Row34 :=
  [⟨64, 128, 7, (421, 3), (149, 4), (149, 4), 36⟩, ⟨64, 512, 9, (471, 3), (171, 4), (167, 4), 278⟩,
   ⟨64, 1024, 10, (536, 3), (195, 4), (190, 4), 270⟩, ⟨64, 2048, 11, (667, 3), (239, 4), (236, 4), 111⟩,
   ⟨64, 4096, 12, (929, 3), (313, 4), (315, 4), 47⟩]

theorem tables34_params_are_gpt2 :
    (table3 ++ table4).all (fun r => printsAs (q (gpt2Params 2 128 r.V r.S)) r.params.1 r.params.2) = true := by
  decide +kernel

def expectedWith (alpha : Q) (r : Row34) : Q :=
  Q.min (q (4096 * r.S * r.log2V)) (alpha * q (gpt2Params 2 128 r.V r.S))

/-- The "Expected" columns are `min(α · params, N·S·log₂V)` with `α = 3.54`, for every
row of both tables... -/
theorem tables34_expected_use_alpha_3_54 :
    (table3 ++ table4).all (fun r => printsAs (expectedWith 3.54 r) r.expected.1 r.expected.2) = true := by
  decide +kernel

/-- ...not with the `α = 3.642` the text says it substituted: then S = 64 would read
2.43 × 10⁶, not 2.36 × 10⁶. -/
theorem tables34_expected_not_alpha_3_642 :
    (table3 ++ table4).any (fun r => !printsAs (expectedWith 3.642 r) r.expected.1 r.expected.2) = true ∧
    printsAs (expectedWith 3.642 ⟨64, 2048, 11, (667, 3), (229, 4), (236, 4), 297⟩) 243 4 = true := by
  decide +kernel

/-- Table 3's S = 64 row and Table 4's V = 2048 row are the same experiment (N = 4096,
S = 64, V = 2048, 2 layers, d = 128, same parameters and expectation) but report
different memorization: 2.29 × 10⁶ and 2.39 × 10⁶ bits, which can't round from the
same value. -/
theorem tables34_same_config_different_result :
    (table3.find? (·.S == 64)).map (·.memorized) = some (229, 4) ∧
    (table4.find? (·.V == 2048)).map (·.memorized) = some (239, 4) ∧
    decide (sci 2295 3 < sci 2385 3) = true := by
  decide +kernel

/-- Each listed error is `|memorized − expected| / expected` for some values that
print as the table shows. -/
def errorConsistent (r : Row34) : Bool :=
  let half := fun (p : Int × Int) => sci 1 p.2 * q 1 2
  let m := val r.memorized
  let e := val r.expected
  let maxErr := (Q.abs (m - e) + half r.memorized + half r.expected) * Exact.inv (e - half r.expected)
  let minErr := Q.max 0 ((Q.abs (m - e) - half r.memorized - half r.expected) * Exact.inv (e + half r.expected))
  decide (minErr - q 1 20000 ≤ q r.errorPct 10000) && decide (q r.errorPct 10000 ≤ maxErr + q 1 20000)

theorem tables34_errors_consistent : (table3 ++ table4).all errorConsistent = true := by
  decide +kernel

/-- Appendix A.1 reports average errors of 1.7% (scaling S) and 1.8% (scaling V).
Table 3's errors average 1.70%; Table 4's average 1.48%. -/
theorem average_errors :
    Q.roundsTo (q (((table3.map (·.errorPct)).foldl (· + ·) 0 : Nat) : Int) 700) 1.7 1 = true ∧
    Q.roundsTo (q (((table4.map (·.errorPct)).foldl (· + ·) 0 : Nat) : Int) 500) 1.5 1 = true ∧
    Q.roundsTo (q (((table4.map (·.errorPct)).foldl (· + ·) 0 : Nat) : Int) 500) 1.8 1 = false := by
  decide +kernel

/-! ## Statements in the text -/

/-- Section 3.2: the "8M parameter language model" memorizes "3.56–3.65 × 10⁶ bits" on
datasets from 16,000 to 4M samples. That is at most 0.46 bits per parameter, not
3.5–3.6. -/
theorem eight_million_param_model : decide (sci 365 4 * q 1 8000000 < 0.46) = true := by decide +kernel

/-- Figure 5's caption gives the 6.86M-parameter model "a capacity of 23.9 MB". As
megabytes that is 27.9 bits per parameter, seven times Table 1's largest α; and as
megabits (23.9 × 10⁶ bits) it still disagrees with Table 1's bf16 capacity for the same
model, 2.51 × 10⁷ bits. -/
theorem figure5_capacity_units :
    Q.roundsTo (sci 239 5 * 8 * Exact.inv (sci 686 4)) 27.9 1 = true ∧
    decide (sci 2395 4 < sci 2505 4) = true := by
  decide +kernel

/-! ## Section 5: the membership-inference scaling law

`F₁(θ, D) = ½ · (1 + c₁ σ(c₂ (Capacity(θ)/|D| + c₃)))` with `c₁ = 1.34`,
`c₂ = −0.034`, `c₃ = −33.14`. The text says F₁ "begin[s] at 1" for small datasets and
decays to 0.5 as `|D| → ∞`. -/

def c1 : Q := 1.34
def c2 : Q := -0.034
def c3 : Q := -33.14

def f1 (x : Q) : Interval :=
  let s := sigmoid (c2 * (x + c3))
  ⟨q 1 2 * (1 + c1 * s.lo), q 1 2 * (1 + c1 * s.hi)⟩

/-- Table 2: model size, dataset size, and the F1 the law predicts for it. -/
def table2 : List (Nat × Nat × Q) :=
  [(1556075200, 170654583, 0.55), (1556075200, 76795021, 0.75), (1556075200, 18851574, 0.95),
   (123702528, 13566442, 0.55), (123702528, 6104935, 0.75), (123702528, 1498634, 0.95)]

/-- Table 2's parameter counts are GPT-2's with 64 positions. The second model has
GPT-2 small's shape (12 layers, width 768) although the table names it
"GPT2-Medium"; the text says GPT-2 small. -/
theorem table2_params :
    gpt2Params 48 1600 50257 64 = 1556075200 ∧ gpt2Params 12 768 50257 64 = 123702528 := by
  decide +kernel

/-- As printed, the law gives F₁ → 1.006 as `|D| → ∞` (an F1 above 1), not 0.5. -/
theorem law_as_printed_limit : (f1 0).lo > 1 := by decide +kernel

/-- Evaluated at Table 2's own dataset sizes, with capacity 3.642 bits per parameter,
the printed law predicts F1 of 0.83, 0.63 and 0.50 for the rows Table 2 lists as 0.55,
0.75 and 0.95: the order is reversed. -/
theorem law_as_printed_reverses_table2 :
    table2.map (fun (θ, D, _) => let i := f1 (3.642 * q θ * Exact.inv (q D)); (Q.roundsTo i.lo 0.83 2 || Q.roundsTo i.lo 0.63 2 || Q.roundsTo i.lo 0.50 2)) =
      [true, true, true, true, true, true] ∧
    (let i := f1 (3.642 * q 1556075200 * Exact.inv (q 170654583)); Q.roundsTo i.lo 0.83 2) = true ∧
    (let i := f1 (3.642 * q 1556075200 * Exact.inv (q 18851574)); Q.roundsTo i.hi 0.50 2) = true := by
  decide +kernel

/-- Counting `|D|` in tokens (64 per example) instead, the printed law predicts an F1
above 1 for the two smaller-F1 rows of each model. -/
theorem law_as_printed_tokens_exceeds_one :
    (table2.filter fun (_, _, f) => decide (f < 0.9)).all
      (fun (θ, D, _) => decide (1 < (f1 (3.642 * q θ * Exact.inv (q (64 * D)))).lo)) = true := by
  decide +kernel

/-- With the ratio inverted, `x = 980 · |D| / params`, one constant reproduces every
predicted F1 in Table 2 to two decimals. -/
theorem law_inverted_reproduces_table2 :
    table2.all (fun (θ, D, target) =>
      let i := f1 (980 * q D * Exact.inv (q θ))
      Q.roundsTo i.lo target 2 && Q.roundsTo i.hi target 2) = true := by
  decide +kernel

/-- Section 5.2.2: at a tokens-per-parameter ratio of 100 the law "would imply
membership inference score of 0.5". As printed (capacity 3.642 bits per parameter,
64-token examples) it gives F1 above 0.99 there. -/
theorem law_as_printed_at_100_tokens_per_param :
    decide (0.99 < (f1 (3.642 * 64 * q 1 100)).lo) = true := by
  decide +kernel

/-- The ICML 2026 version ("How much can language models memorize?", PMLR v306)
prints the law as `F₁ = ½ (1 + c₁ σ(c₂ · Capacity/|D| + c₃))` with the same
constants. That fixes the limit (F₁ → 0.5 as `|D| → ∞`), but since `c₂ < 0` and
`c₃ = −33.14` the argument of σ is below −33 for every dataset, so the law predicts
F₁ within 10⁻¹⁴ of 0.5 everywhere, including every row of Table 2. -/
def f1Icml (x : Q) : Interval :=
  let s := sigmoid (c2 * x + c3)
  ⟨q 1 2 * (1 + c1 * s.lo), q 1 2 * (1 + c1 * s.hi)⟩

theorem law_icml_is_flat_on_table2 :
    table2.all (fun (θ, D, _) =>
      decide ((f1Icml (3.642 * q θ * Exact.inv (q D))).hi < 0.5 + sci 1 (-14)) &&
      decide ((f1Icml (3.642 * q θ * Exact.inv (q (64 * D)))).hi < 0.5 + sci 1 (-14))) = true ∧
    decide ((f1Icml 0).hi < 0.5 + sci 1 (-14)) = true := by
  decide +kernel

/-- Table 2's observed F1 is "generally within 1.5 points" of the target (Section
5.2.2); four of the six rows are not. -/
theorem table2_observed_within_1_5_points :
    (List.filter (fun (p : Q × Q) => decide (1.5 < Q.abs (p.2 - 100 * p.1)))
      [(0.55, 54.61), (0.75, 71.08), (0.95, 95.85), (0.55, 53.44), (0.75, 65.69), (0.95, 97.98)]).length = 4 := by
  decide +kernel

end Paper

#print axioms Paper.law_inverted_reproduces_table2
