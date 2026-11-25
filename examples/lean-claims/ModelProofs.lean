import Model
import PaperTables

/-!
# Theorems about the program that trains

`generated_model.py` is produced from `Model.lean` by `lake exe codegen`, so these
are statements about the model in every run of `AttentionAblation.lean`.
-/

open Model

namespace ModelProofs

def encDec (c : Config) : List Program := [(build (encoder c)).prog, (build (decoder c)).prog]

/-- Every step of every generated method has a shape, for all four variants and
the attention probe. -/
theorem programs_typecheck :
    (variants.all fun (_, c) =>
      wellTyped (build (encoder c)) && wellTyped (build (decoder c)) && wellTyped (build (loss c))) &&
    wellTyped (probe .none) && wellTyped (probe .future) = true := by
  decide +kernel

/-- The decoder's output has shape `[batch, target length, vocabulary]`. -/
theorem decoder_output_shape :
    outShape (build (decoder base)) = some [.batch, .tgtLen, .n 8000] := by
  decide +kernel

/-- The parameter count of the program is the architecture formula of
`PaperTables` (Section 3) for every variant, so that formula is now derived from the
code rather than written next to it. -/
theorem param_count_matches_formula :
    (variants.all fun (_, c) =>
      paramCount (encDec c) == PaperTables.Arch.params ⟨c.N, c.dModel, c.dFF, c.h, c.dk, c.dv⟩ c.vocab) = true := by
  decide +kernel

/-- The logged counts in the runs: 7,568,384 for base, one head and no label
smoothing, 6,683,648 for `d_k = 8`. -/
theorem param_counts :
    variants.map (fun (n, c) => (n, paramCount (encDec c))) =
      [("base", 7568384), ("h1", 7568384), ("dk8", 6683648), ("ls0", 7568384)] := by
  decide +kernel

/-- Section 3.2.3: decoder output at position `t` of example `b` depends only on
example `b`'s source and its decoder inputs at positions `≤ t`. No future token
and no other example in the batch reaches it. Checked for batches of 2 with source
length 3 and target length 4, and for a single example with lengths 2 and 6. -/
theorem no_future_or_cross_example_leak :
    (variants.all fun (_, c) => noLeak c ⟨2, 3, 4⟩ && noLeak c ⟨1, 2, 6⟩) = true := by
  decide +kernel

/-- The property depends on the mask: with `maskFuture` removed, the same check
fails for every variant. -/
theorem leaks_without_future_mask :
    (variants.all fun (_, c) => !noLeakWithoutMask c ⟨2, 3, 4⟩) = true := by
  decide +kernel

/-- ...and it isn't vacuous: every output position depends on its own decoder
token and on every source token of its example. -/
theorem logits_use_current_token_and_source :
    (variants.all fun (_, c) => usesCurrentTokenAndSource c ⟨2, 3, 4⟩) = true := by
  decide +kernel

end ModelProofs

#print axioms ModelProofs.no_future_or_cross_example_leak
