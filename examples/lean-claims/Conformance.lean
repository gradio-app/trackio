import AttentionAblation
import PaperTables
import Spec

/-!
# Does the training code implement the paper's method?

Each theorem checks facts the training code logged about itself against
`Spec.lean`, which encodes the method section of the paper. These are tests,
not proofs of the code: they show that on the logged inputs, the code did what
the spec says.
-/

open Trackio AttentionAblation

namespace Conformance

def nat? (r : Run) (k : Key) : Option Nat := (cfg r k).bind Q.toNat?

/-- Section 5.3. Every learning rate each run logged is the paper's schedule,
`d_model^-0.5 · min(n^-0.5, n · warmup^-1.5)` (times `lr_factor`), to a relative
error of 10⁻⁹. The value logged at step `k` is the rate for update `k + 1`. -/
theorem lr_schedule_matches_paper :
    holds (allOf runs fun r => do
      let f ← cfg r .lr_factor
      let d ← nat? r .d_model
      let w ← nat? r .warmup
      let points := series r .train_lr
      if points.isEmpty then none
      return points.all fun (k, x) =>
        let want := Spec.lrSquared f d w (k + 1)
        decide (Q.abs (x * x - want) ≤ q 1 1000000000 * want)) := by
  decide +kernel

def probeMetric : Bool → Nat → Nat → Option Metric
  | false, 0, 0 => some .probe_self_t0_c0
  | false, 0, 1 => some .probe_self_t0_c1
  | false, 0, 2 => some .probe_self_t0_c2
  | false, 0, 3 => some .probe_self_t0_c3
  | false, 1, 0 => some .probe_self_t1_c0
  | false, 1, 1 => some .probe_self_t1_c1
  | false, 1, 2 => some .probe_self_t1_c2
  | false, 1, 3 => some .probe_self_t1_c3
  | false, 2, 0 => some .probe_self_t2_c0
  | false, 2, 1 => some .probe_self_t2_c1
  | false, 2, 2 => some .probe_self_t2_c2
  | false, 2, 3 => some .probe_self_t2_c3
  | true, 0, 0 => some .probe_causal_t0_c0
  | true, 0, 1 => some .probe_causal_t0_c1
  | true, 0, 2 => some .probe_causal_t0_c2
  | true, 0, 3 => some .probe_causal_t0_c3
  | true, 1, 0 => some .probe_causal_t1_c0
  | true, 1, 1 => some .probe_causal_t1_c1
  | true, 1, 2 => some .probe_causal_t1_c2
  | true, 1, 3 => some .probe_causal_t1_c3
  | true, 2, 0 => some .probe_causal_t2_c0
  | true, 2, 1 => some .probe_causal_t2_c1
  | true, 2, 2 => some .probe_causal_t2_c2
  | true, 2, 3 => some .probe_causal_t2_c3
  | _, _, _ => none

/-- Section 3.2. On the probe, every run's `MultiHeadAttention` produced
`softmax(QKᵀ/√d_k)V` per head, concatenated and projected, with and without the
decoder's causal mask: all 24 logged outputs are within 10⁻⁶ of the exact
values. -/
theorem attention_matches_paper :
    holds (do
      let unmaskedRef ← Spec.probeReference false
      let maskedRef ← Spec.probeReference true
      allOf runs fun r => allOf [false, true] fun masked =>
        allOf (List.range Spec.probeLength) fun t => allOf (List.range 4) fun c => do
          let ref := if masked then maskedRef else unmaskedRef
          let expected ← (ref.getD t [])[c]?
          let x ← final r (← probeMetric masked t c)
          return expected.contains x (q 1 1000000)) := by
  decide +kernel

/-- Section 3. Every model's parameter count is the architecture formula of
`PaperTables` applied to its logged config. -/
theorem params_match_architecture :
    holds (allOf runs fun r => do
      let a : PaperTables.Arch :=
        ⟨← nat? r .N, ← nat? r .d_model, ← nat? r .d_ff, ← nat? r .h, ← nat? r .d_k, ← nat? r .d_v⟩
      let v ← nat? r .vocab_size
      let p ← (final r .model_params).bind Q.toNat?
      return p == a.params v) := by
  decide

/-- Every run was produced by the same script. `trackio verify` checks this
hash against the script in this directory and against the script HF Jobs ran. -/
theorem one_script :
    holds (do
      let h ← codeSha256 .base_s0
      allOf runs fun r => do return (← codeSha256 r) == h) := by
  decide

/-- Every run imported the same `generated_model.py`, the model `lake exe codegen`
writes from `Model.lean`. `trackio verify` matches this hash against a freshly
generated file and against the copy HF Jobs ran. -/
theorem one_generated_model :
    holds (do
      let h ← (codeFiles .base_s0).lookup "generated_model.py"
      allOf runs fun r => do return (← (codeFiles r).lookup "generated_model.py") == h) := by
  decide

end Conformance

#print axioms Conformance.attention_matches_paper
#print axioms Conformance.lr_schedule_matches_paper
