import AttentionAblation

/-!
# Table 3 claims, checked against our own logged rerun

`AttentionAblation.lean` is `trackio export` of twelve training runs on Hugging
Face Jobs: the base model and three Table 3 variations (one head, `d_k = 8`, no
label smoothing), three seeds each, trained on Multi30k EN→DE with 7.6M
parameters, about 1/9 of the paper's base model (see `train_ablation.py`).
`Conformance.lean` checks that the code implements the paper's method; this file
checks what the paper concludes from Table 3. Each theorem proves either the
paper's sentence or its negation from the logs. Results are at small scale and
say nothing about the paper's scale.
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

/-- One head is worse than eight on every seed, in perplexity... -/
theorem one_head_worse_ppl_every_seed :
    holds (everySeed base oneHead .dev_ppl fun b h => decide (b < h)) := by
  decide

/-- ...and in BLEU. -/
theorem one_head_worse_bleu_every_seed :
    holds (everySeed base oneHead .dev_bleu fun b h => decide (h < b)) := by
  decide

/-- But the average gap is 0.2 BLEU, not 0.9... -/
theorem one_head_gap_is_0_2 :
    holds (do
      let b ← meanFinal base .dev_bleu
      let h ← meanFinal oneHead .dev_bleu
      return Q.roundsTo (b - h) 0.2 1) := by
  decide

/-- ...and is not significant. -/
theorem one_head_bleu_gap_not_significant :
    welch base oneHead .dev_bleu tLenient = some false := by
  decide

/-! ## Row (B): "reducing the attention key size d_k hurts model quality" -/

/-- Shrinking `d_k` from 32 to 8 raises dev perplexity on every seed... -/
theorem small_key_worse_ppl_every_seed :
    holds (everySeed base smallKey .dev_ppl fun b k => decide (b < k)) := by
  decide

/-- ...and lowers mean dev BLEU... -/
theorem small_key_worse_mean_bleu :
    holds (do
      let b ← meanFinal base .dev_bleu
      let k ← meanFinal smallKey .dev_bleu
      return decide (k < b)) := by
  decide

/-- ...but not on every seed. -/
theorem small_key_bleu_drop_not_every_seed :
    ¬ holds (everySeed base smallKey .dev_bleu fun b k => decide (k < b)) := by
  decide

/-! ## Label smoothing: "This hurts perplexity ... but improves accuracy and BLEU score" -/

/-- The perplexity half is reversed here: removing label smoothing makes dev
perplexity worse on every seed. With 29K training pairs the smoothing acts as a
regularizer. -/
theorem smoothing_improves_ppl_every_seed :
    holds (everySeed base noSmoothing .dev_ppl fun b n => decide (b < n)) := by
  decide

/-- The reversal is significant even at the strictest critical value. -/
theorem smoothing_ppl_effect_significant :
    welch base noSmoothing .dev_ppl tStrict = some true := by
  decide

/-- The BLEU half holds on average... -/
theorem smoothing_improves_mean_bleu :
    holds (do
      let b ← meanFinal base .dev_bleu
      let n ← meanFinal noSmoothing .dev_bleu
      return decide (n < b)) := by
  decide

/-- ...but not on every seed, and not significantly. -/
theorem smoothing_bleu_gain_not_every_seed :
    ¬ holds (everySeed base noSmoothing .dev_bleu fun b n => decide (n < b)) := by
  decide

theorem smoothing_bleu_gain_not_significant :
    welch base noSmoothing .dev_bleu tLenient = some false := by
  decide

/-! ## How much of this is noise -/

/-- Three seeds of the same base config span more than 2 dev BLEU, more than
twice the largest effect Section 6.2 reports for rows (A) and (B) (0.9). -/
theorem base_seeds_span_over_2_bleu :
    holds (do
      let lo ← final .base_s0 .dev_bleu
      let hi ← final .base_s2 .dev_bleu
      return decide ((2 : Q) < hi - lo)) := by
  decide

/-- No BLEU difference in this rerun is significant, even at the most lenient
critical value. -/
theorem no_bleu_effect_significant :
    welch base oneHead .dev_bleu tLenient = some false ∧
    welch base smallKey .dev_bleu tLenient = some false ∧
    welch base noSmoothing .dev_bleu tLenient = some false := by
  decide

end Claims

#print axioms Claims.smoothing_ppl_effect_significant
