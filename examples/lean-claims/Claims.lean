import AttentionAblation
import PaperTables

/-!
# Table 3 claims, checked against our own logged rerun

`AttentionAblation.lean` is `trackio export` of eight real training runs:
the base model and three Table 3 variations (one head, `d_k = 8`, no label
smoothing), two seeds each, trained on Multi30k EN→DE with 7.6M parameters,
about 1/9 of the paper's base model (see `train_ablation.py`). Each theorem below restates one of
the paper's sentences about Table 3 and proves either it or its negation from
the logs. Results are at small scale and say nothing about the paper's scale.
-/

open Trackio AttentionAblation

namespace Claims

def base : List Run := [.base_s0, .base_s1]
def oneHead : List Run := [.h1_s0, .h1_s1]
def smallKey : List Run := [.dk8_s0, .dk8_s1]
def noSmoothing : List Run := [.ls0_s0, .ls0_s1]

def finals (rs : List Run) (m : Metric) : Option (List Q) := rs.mapM (final · m)

def meanFinal (rs : List Run) (m : Metric) : Option Q := do
  Stats.mean? (← finals rs m)

/-- `cmp` holds between seed-matched runs of two variants, for every seed. -/
def everySeed (xs ys : List Run) (m : Metric) (cmp : Q → Q → Bool) : Option Bool :=
  allOf (xs.zip ys) fun (x, y) => do
    return cmp (← final x m) (← final y m)

def nat? (r : Run) (k : Key) : Option Nat := (cfg r k).bind Q.toNat?

def arch? (r : Run) : Option PaperTables.Arch := do
  return ⟨← nat? r .N, ← nat? r .d_model, ← nat? r .d_ff, ← nat? r .h,
    ← nat? r .d_k, ← nat? r .d_v⟩

/-! ## The architecture formula matches real models -/

/-- Every trained model's logged parameter count equals `PaperTables.Arch.params`
applied to its logged config. This is the formula `PaperTables` uses to show the
paper's params column is inconsistent, now checked against eight real PyTorch
models. -/
theorem params_match_formula :
    holds (allOf runs fun r => do
      let a ← arch? r
      let v ← nat? r .vocab_size
      let p ← (final r .model_params).bind Q.toNat?
      return p == a.params v) := by
  decide

/-- Row (A) varies heads "keeping the amount of computation constant": one head
of size 256 has exactly the base model's parameter count. -/
theorem row_A_keeps_params_constant :
    holds (everySeed base oneHead .model_params fun a b => decide (a ≈ b)) := by
  decide

/-! ## Row (A): "single-head attention is 0.9 BLEU worse than the best setting" -/

/-- In perplexity, one head is worse than eight on every seed. -/
theorem one_head_worse_ppl_every_seed :
    holds (everySeed base oneHead .dev_ppl fun b h => decide (b < h)) := by
  decide

/-- In BLEU it is not: averaged over seeds, one head scores at least as well as
eight. -/
theorem one_head_not_worse_bleu :
    ¬ holds (do
      let b ← meanFinal base .dev_bleu
      let h ← meanFinal oneHead .dev_bleu
      return decide (h < b)) := by
  decide

/-! ## Row (B): "reducing the attention key size d_k hurts model quality" -/

/-- Shrinking `d_k` from 32 to 8 raises dev perplexity on every seed... -/
theorem small_key_worse_ppl_every_seed :
    holds (everySeed base smallKey .dev_ppl fun b k => decide (b < k)) := by
  decide

/-- ...but raises dev BLEU on every seed. -/
theorem small_key_better_bleu_every_seed :
    holds (everySeed base smallKey .dev_bleu fun b k => decide (b < k)) := by
  decide

/-! ## Label smoothing: "This hurts perplexity ... but improves accuracy and BLEU score" -/

/-- The perplexity half is reversed here: removing label smoothing makes dev
perplexity worse on every seed. With 29K training pairs the smoothing acts as a
regularizer. -/
theorem smoothing_improves_ppl_every_seed :
    holds (everySeed base noSmoothing .dev_ppl fun b n => decide (b < n)) := by
  decide

/-- The BLEU half holds on average... -/
theorem smoothing_improves_mean_bleu :
    holds (do
      let b ← meanFinal base .dev_bleu
      let n ← meanFinal noSmoothing .dev_bleu
      return decide (n < b)) := by
  decide

/-- ...but not on every seed. -/
theorem smoothing_bleu_gain_not_every_seed :
    ¬ holds (everySeed base noSmoothing .dev_bleu fun b n => decide (n < b)) := by
  decide

/-! ## How much of this is noise -/

/-- Two seeds of the same base config differ by more dev BLEU than the paper's
row (B) effect (25.8 → 25.4). -/
theorem seed_spread_exceeds_row_B_effect :
    holds (do
      let a ← final .base_s0 .dev_bleu
      let b ← final .base_s1 .dev_bleu
      return decide ((0.4 : Q) < Q.abs (a - b))) := by
  decide

/-- Even the largest effect measured, label smoothing on perplexity, is not
significant by a two-sided Welch test at the 5% level with two seeds per arm
(t critical value 12.706 for one degree of freedom, from a t-table). -/
theorem largest_effect_not_significant :
    (do Stats.welchExceeds? (← finals base .dev_ppl) (← finals noSmoothing .dev_ppl) 12.706)
      = some false := by
  decide

end Claims

#print axioms Claims.params_match_formula
#print axioms Claims.largest_effect_not_significant
