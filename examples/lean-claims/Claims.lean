import AttentionAblation

/-!
# Table 3 claims, checked against our own logged rerun

`AttentionAblation.lean` is `trackio export` of twelve training runs on Hugging
Face Jobs: the base model and three Table 3 variations (one head, `d_k = 8`, no
label smoothing), three seeds each, trained on Multi30k EN→DE with 7.6M
parameters, about 1/9 of the paper's base model. The model in every run is
`generated_model.py`, generated from `Model.lean`. Each theorem restates one of the
paper's sentences about Table 3 and proves either it or its negation from the logs.
Results are at small scale and say nothing about the paper's scale.
-/

open Trackio AttentionAblation

namespace Claims

def base : List Run := [.base_s0, .base_s1, .base_s2]
def oneHead : List Run := [.h1_s0, .h1_s1, .h1_s2]
def smallKey : List Run := [.dk8_s0, .dk8_s1, .dk8_s2]
def noSmoothing : List Run := [.ls0_s0, .ls0_s1, .ls0_s2]

def finals (rs : List Run) (m : Metric) : Option (List Q) := rs.mapM (final · m)

def meanFinal (rs : List Run) (m : Metric) : Option Q := do
  Stats.mean? (← finals rs m)

/-- `cmp` holds between seed-matched runs of two variants, for every seed. -/
def everySeed (xs ys : List Run) (m : Metric) (cmp : Q → Q → Bool) : Option Bool :=
  allOf (xs.zip ys) fun (x, y) => do
    return cmp (← final x m) (← final y m)

/-- `cmp` holds between the two variants' means over seeds. -/
def onAverage (xs ys : List Run) (m : Metric) (cmp : Q → Q → Bool) : Option Bool := do
  return cmp (← meanFinal xs m) (← meanFinal ys m)

/-- Two-sided Welch test on final values of `m`. -/
def welch (xs ys : List Run) (m : Metric) (tcrit : Q) : Option Bool := do
  Stats.welchExceeds? (← finals xs m) (← finals ys m) tcrit

/-- t critical values (two-sided, 5%) from a t-table. With three runs per arm,
Welch's degrees of freedom lie between 2 and 4. "Significant" claims use the
strictest value (df = 2), "not significant" claims the most lenient (df = 4). -/
def tStrict : Q := 4.303
def tLenient : Q := 2.776

/-- Row (A) varies heads "keeping the amount of computation constant": one head
of size 256 has exactly the base model's parameter count. -/
theorem row_A_keeps_params_constant :
    holds (everySeed base oneHead .model_params fun a b => decide (a ≈ b)) := by
  decide

/-! ## Row (A): "single-head attention is 0.9 BLEU worse than the best setting" -/

/-- One head is worse than eight on average, in perplexity and in BLEU... -/
theorem one_head_worse_on_average :
    holds (onAverage base oneHead .dev_ppl fun b h => decide (b < h)) ∧
    holds (onAverage base oneHead .dev_bleu fun b h => decide (h < b)) := by
  decide

/-- ...by 0.1 BLEU, not 0.9... -/
theorem one_head_gap_is_0_1 :
    holds (do
      let b ← meanFinal base .dev_bleu
      let h ← meanFinal oneHead .dev_bleu
      return Q.roundsTo (b - h) 0.1 1) := by
  decide

/-- ...not on every seed, in either metric... -/
theorem one_head_not_worse_every_seed :
    ¬ holds (everySeed base oneHead .dev_ppl fun b h => decide (b < h)) ∧
    ¬ holds (everySeed base oneHead .dev_bleu fun b h => decide (h < b)) := by
  decide

/-- ...and not significantly. -/
theorem one_head_bleu_gap_not_significant :
    welch base oneHead .dev_bleu tLenient = some false := by
  decide

/-! ## Row (B): "reducing the attention key size d_k hurts model quality" -/

/-- Shrinking `d_k` from 32 to 8 is worse on every seed, in perplexity and BLEU... -/
theorem small_key_worse_every_seed :
    holds (everySeed base smallKey .dev_ppl fun b k => decide (b < k)) ∧
    holds (everySeed base smallKey .dev_bleu fun b k => decide (k < b)) := by
  decide

/-- ...by 2.0 BLEU on average... -/
theorem small_key_gap_is_2_0 :
    holds (do
      let b ← meanFinal base .dev_bleu
      let k ← meanFinal smallKey .dev_bleu
      return Q.roundsTo (b - k) 2.0 1) := by
  decide

/-- ...which clears the lenient critical value but not the strict one: with three
seeds, whether it is significant depends on the degrees of freedom. -/
theorem small_key_bleu_significance_depends_on_df :
    welch base smallKey .dev_bleu tLenient = some true ∧
    welch base smallKey .dev_bleu tStrict = some false := by
  decide

/-! ## Label smoothing: "This hurts perplexity ... but improves accuracy and BLEU score" -/

/-- The perplexity half is reversed here: removing label smoothing makes dev
perplexity worse on every seed, significantly even at the strictest critical value.
With 29K training pairs the smoothing acts as a regularizer. -/
theorem smoothing_improves_ppl :
    holds (everySeed base noSmoothing .dev_ppl fun b n => decide (b < n)) ∧
    welch base noSmoothing .dev_ppl tStrict = some true := by
  decide

/-- The BLEU half holds on average, but not on every seed and not significantly. -/
theorem smoothing_bleu_gain_is_weak :
    holds (onAverage base noSmoothing .dev_bleu fun b n => decide (n < b)) ∧
    ¬ holds (everySeed base noSmoothing .dev_bleu fun b n => decide (n < b)) ∧
    welch base noSmoothing .dev_bleu tLenient = some false := by
  decide

/-! ## How much of this is noise -/

/-- The one-head runs span 2.9 dev BLEU across seeds, more than three times the
0.9 BLEU effect Section 6.2 reports for them. -/
theorem one_head_seeds_span_over_2_9_bleu :
    holds (do
      let lo ← final .h1_s0 .dev_bleu
      let hi ← final .h1_s2 .dev_bleu
      return decide ((2.9 : Q) < hi - lo)) := by
  decide

/-- No BLEU difference in this rerun is significant at the strict critical value. -/
theorem no_bleu_effect_strictly_significant :
    welch base oneHead .dev_bleu tStrict = some false ∧
    welch base smallKey .dev_bleu tStrict = some false ∧
    welch base noSmoothing .dev_bleu tStrict = some false := by
  decide

end Claims

#print axioms Claims.smoothing_improves_ppl
