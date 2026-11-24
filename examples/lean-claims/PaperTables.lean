import Trackio

/-!
# "Attention Is All You Need": the text's claims against its own tables

The numbers below are transcribed from Tables 2 and 3 of arXiv:1706.03762v7.
Nothing here is a training log; this file only checks whether the paper's
sentences and arithmetic follow from the numbers it prints. The companion file
`Claims.lean` checks the same claims against our own logged rerun.
-/

open Trackio

namespace PaperTables

/-! ## Parameter counts (Table 3, last column) -/

/-- The architecture of Section 3: `N` encoder and decoder layers, multi-head
attention with `h` heads of size `d_k`/`d_v` and no projection biases, a
position-wise FFN with biases, two (encoder) or three (decoder) LayerNorms per
layer, sinusoidal positions, and one `V × d` embedding matrix shared by both
embedding layers and the pre-softmax projection (Section 3.4). -/
structure Arch where
  N : Nat
  d : Nat
  dff : Nat
  h : Nat
  dk : Nat
  dv : Nat

def Arch.attn (a : Arch) : Nat := 2 * a.d * (a.h * a.dk) + 2 * a.d * (a.h * a.dv)
def Arch.ffn (a : Arch) : Nat := 2 * a.d * a.dff + a.dff + a.d
def Arch.norm (a : Arch) : Nat := 2 * a.d
def Arch.layers (a : Arch) : Nat :=
  a.N * ((a.attn + a.ffn + 2 * a.norm) + (2 * a.attn + a.ffn + 3 * a.norm))
def Arch.params (a : Arch) (V : Nat) : Nat := a.layers + a.d * V

/-- `p` parameters are printed as `m` in a "params × 10⁶" column. -/
def printsAs (p m : Nat) : Prop := m * 1000000 ≤ p + 500000 ∧ p + 500000 < m * 1000000 + 1000000

instance (p m : Nat) : Decidable (printsAs p m) := by unfold printsAs; infer_instance

def base : Arch := ⟨6, 512, 2048, 8, 64, 64⟩
def dk16 : Arch := ⟨6, 512, 2048, 8, 16, 64⟩
def dk32 : Arch := ⟨6, 512, 2048, 8, 32, 64⟩
def n2 : Arch := ⟨2, 512, 2048, 8, 64, 64⟩
def n4 : Arch := ⟨4, 512, 2048, 8, 64, 64⟩
def n8 : Arch := ⟨8, 512, 2048, 8, 64, 64⟩
def d256 : Arch := ⟨6, 256, 2048, 8, 32, 32⟩
def d1024 : Arch := ⟨6, 1024, 2048, 8, 128, 128⟩
def ff1024 : Arch := ⟨6, 512, 1024, 8, 64, 64⟩
def ff4096 : Arch := ⟨6, 512, 4096, 8, 64, 64⟩
def big : Arch := ⟨6, 1024, 4096, 16, 64, 64⟩

/-- Every Table 3 row except "big" prints its parameter count correctly for
vocabulary size `V`. -/
def baseSizedRowsFit (V : Nat) : Prop :=
  printsAs (base.params V) 65 ∧ printsAs (dk16.params V) 58 ∧
  printsAs (dk32.params V) 60 ∧ printsAs (n2.params V) 36 ∧
  printsAs (n4.params V) 50 ∧ printsAs (n8.params V) 80 ∧
  printsAs (d256.params V) 28 ∧ printsAs (d1024.params V) 168 ∧
  printsAs (ff1024.params V) 53 ∧ printsAs (ff4096.params V) 90

instance (V : Nat) : Decidable (baseSizedRowsFit V) := by
  unfold baseSizedRowsFit; infer_instance

/-- With the vocabulary Section 5.1 states ("about 37000 tokens") the base
model has about 63M parameters, not the 65M Table 3 reports. -/
theorem stated_vocab_gives_63M :
    printsAs (base.params 37000) 63 ∧ ¬ printsAs (base.params 37000) 65 := by
  decide

/-- The ten base-sized rows are consistent with one another: a single
vocabulary size makes all ten printed counts correct. -/
theorem base_sized_rows_agree : baseSizedRowsFit 41100 := by
  decide

/-- ... and that vocabulary is pinned to 41004–41208 tokens, about 11% more
than the stated 37000. -/
theorem base_sized_rows_pin_vocab (V : Nat) (h : baseSizedRowsFit V) :
    41004 ≤ V ∧ V ≤ 41208 := by
  simp only [baseSizedRowsFit, printsAs, Arch.params, Arch.layers, Arch.attn,
    Arch.ffn, Arch.norm, base, dk16, dk32, n2, n4, n8, d256, d1024, ff1024,
    ff4096] at h
  omega

/-- No vocabulary size makes both the base (65M) and big (213M) counts
correct, so the params column cannot all come from the architecture as
described with one vocabulary. -/
theorem no_vocab_fits_base_and_big (V : Nat) :
    ¬ (printsAs (base.params V) 65 ∧ printsAs (big.params V) 213) := by
  simp only [printsAs, Arch.params, Arch.layers, Arch.attn, Arch.ffn, Arch.norm,
    base, big]
  omega

/-! ## Table 2: training cost and headline BLEU -/

/-- Section 6.1 estimates FLOPs as time × GPUs × sustained TFLOPS, with 9.5
TFLOPS for a P100 (footnote 2). 12 hours (base) and 3.5 days (big) on 8 GPUs
give the printed 3.3·10¹⁸ and 2.3·10¹⁹. -/
theorem training_cost_arithmetic :
    Q.roundsTo (q (12 * 3600 * 8 * 95) (10 ^ 7)) 3.3 1 = true ∧
    Q.roundsTo (q (84 * 3600 * 8 * 95) (10 ^ 8)) 2.3 1 = true := by
  decide

/-- Section 5.2 also gives step times: 100K steps at 0.4 s is 11.1 hours, not
12. With 11.1 hours the base model's cost would print as 3.0·10¹⁸. -/
theorem base_cost_from_step_time :
    Q.roundsTo (q (100000 * 4 * 8 * 95) (10 ^ 8)) 3.0 1 = true := by
  decide

def bestPriorEnDe : Q := 26.36

/-- "Outperforms the best previously reported models (including ensembles) by
more than 2.0 BLEU": true for the printed 28.4 (by 0.04)... -/
theorem en_de_margin_as_printed : decide ((28.4 : Q) - bestPriorEnDe > 2.0) = true := by
  decide

/-- ...but 28.4 is itself rounded, and an unrounded score of 28.36 also prints
as 28.4 while beating 26.36 by exactly 2.0. The table alone does not establish
"more than 2.0". -/
theorem en_de_margin_not_implied_by_table :
    ∃ x : Q, Q.roundsTo x 28.4 1 = true ∧ decide (x - bestPriorEnDe > 2.0) = false :=
  ⟨28.36, by decide⟩

def priorEnFrSingle : List Q := [39.2, 39.92, 40.46, 40.56]
def priorEnFrEnsembles : List Q := [40.4, 41.16, 41.29]

/-- Section 6.1 says the big model scores 41.0 on EN-FR; Table 2 and the
abstract say 41.8. The single-model claim holds either way, but only 41.8 also
beats every prior ensemble. -/
theorem en_fr_text_vs_table :
    priorEnFrSingle.all (fun p => decide (p < (41.0 : Q))) = true ∧
    priorEnFrEnsembles.all (fun p => decide (p < (41.8 : Q))) = true ∧
    priorEnFrEnsembles.all (fun p => decide (p < (41.0 : Q))) = false := by
  decide

/-! ## Table 3: Section 6.2's summary of the variations -/

/-- "Single-head attention is 0.9 BLEU worse than the best setting." -/
theorem single_head_gap_as_printed :
    Q.roundsTo ((25.8 : Q) - 24.9) 0.9 1 = true := by
  decide

/-- "Bigger models are better" (row C) does not hold for depth in BLEU: N=8
scores below the N=6 base model. -/
theorem deeper_is_not_better_in_bleu :
    decide ((25.5 : Q) < 25.8) = true := by
  decide

/-- It does hold for depth in perplexity: 6.11 > 5.19 > 4.92 > 4.88. -/
theorem deeper_is_better_in_ppl :
    decide ((4.88 : Q) < 4.92 ∧ (4.92 : Q) < 5.19 ∧ (5.19 : Q) < 6.11) = true := by
  decide

/-- Read as "more parameters ⇒ better", it fails in both metrics: N=2 (36M)
has worse perplexity than d_model=256 (28M), and N=8 (80M) worse BLEU than
base (65M). -/
theorem more_params_not_always_better :
    decide ((6.11 : Q) > 5.75) = true ∧ decide ((25.5 : Q) < 25.8) = true := by
  decide

/-- Section 5.4: label smoothing "hurts perplexity ... but improves accuracy and
BLEU score". Row D with base (ε = 0.0, 0.1, 0.2): perplexity rises with ε, and
both ε > 0 settings beat ε = 0 in BLEU. -/
theorem label_smoothing_tradeoff :
    decide ((4.67 : Q) < 4.92 ∧ (4.92 : Q) < 5.47 ∧
      (25.3 : Q) < 25.8 ∧ (25.3 : Q) < 25.7) = true := by
  decide

end PaperTables
