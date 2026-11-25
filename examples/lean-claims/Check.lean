import Model
import PaperTables

/-!
# Fast diagnostics for `ModelProofs.lean`

`lake exe check` evaluates the properties `ModelProofs.lean` proves, as compiled code,
and prints which hold. It takes about a second. Use it after editing `Model.lean`:
the kernel checks `decide +kernel` quickly when a property holds, but when one fails
it can spend minutes and many gigabytes before reporting it. The theorems in
`ModelProofs.lean` remain the guarantee; this only says which one will fail.
-/

open Model

def checks : List (String × Bool) :=
  let encDec := fun (c : Config) => [(build (encoder c)).prog, (build (decoder c)).prog]
  [("programs_typecheck",
      (variants.all fun (_, c) =>
        wellTyped (build (encoder c)) && wellTyped (build (decoder c)) && wellTyped (build (loss c))) &&
      wellTyped (probe .none) && wellTyped (probe .future)),
   ("param_count_matches_formula", variants.all fun (_, c) =>
      paramCount (encDec c) == PaperTables.Arch.params ⟨c.N, c.dModel, c.dFF, c.h, c.dk, c.dv⟩ c.vocab),
   ("no_future_or_cross_example_leak", variants.all fun (_, c) =>
      noLeak c ⟨2, 3, 4⟩ && noLeak c ⟨1, 2, 6⟩),
   ("leaks_without_future_mask", variants.all fun (_, c) => !noLeakWithoutMask c ⟨2, 3, 4⟩),
   ("logits_use_current_token_and_source", variants.all fun (_, c) =>
      usesCurrentTokenAndSource c ⟨2, 3, 4⟩)]

def main : IO UInt32 := do
  for (name, ok) in checks do
    IO.println s!"{if ok then "OK  " else "FAIL"} {name}"
  return if checks.all (·.2) then 0 else 1
