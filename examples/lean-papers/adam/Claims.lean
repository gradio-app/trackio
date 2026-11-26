import AdamRuns
import Spec

/-!
# Section 6 of the Adam paper, checked against our rerun

`AdamRuns.lean` is `trackio export` of the runs `train_optimizers.py` logged on Hugging
Face Jobs: every optimizer on a learning-rate grid (seed 0), then the best rate on seeds
1 and 2, for logistic regression and an MLP on MNIST and a CNN on CIFAR-10. Runs are
selected by their logged config, not by name. Each claim of Section 6 is stated as a
decidable predicate on the logged training costs, and each theorem says whether our
rerun supports it (`= some true`) or contradicts it (`= some false`).

Our rerun is smaller than the paper's (20 epochs instead of 45 for logistic regression,
20 instead of 200 for the MLP, 15 instead of 45 for the CNN, per-channel standardization
instead of whitening for CIFAR-10), so a contradiction here says the claim does not
hold in this setting, not that the paper's own runs were misreported.
-/

open Trackio AdamRuns

namespace Claims

def isTask (task opt : String) (r : Run) : Bool :=
  cfgStr r .task == some task && cfgStr r .optimizer == some opt

/-- The learning rate the grid picked: the rate of the optimizer's `final` runs. -/
def bestLr (task opt : String) : Option Q :=
  (runs.find? fun r => isTask task opt r && cfgStr r .phase == some "final").bind (cfg · .lr)

/-- The three runs at the chosen rate: seed 0 from the grid, seeds 1 and 2. -/
def best (task opt : String) : List Run :=
  match bestLr task opt with
  | some lr => runs.filter fun r => isTask task opt r && (cfg r .lr).map (fun x => decide (x ≈ lr)) == some true
  | none => []

/-- Training cost after `epoch` epochs (the cost is logged once per epoch). -/
def costAt (r : Run) (epoch : Nat) : Option Q := ((series r .train_cost).map (·.2))[epoch - 1]?

def gridRuns (task opt : String) : List Run :=
  runs.filter fun r => isTask task opt r && cfgStr r .phase == some "grid"

def gridLrs (task opt : String) : List Q := (gridRuns task opt).filterMap (cfg · .lr)

/-- The grid run with the lowest final training cost picked the rate the final runs used. -/
def selectionFollowsGrid (task opt : String) : Option Bool := do
  let lr ← bestLr task opt
  let costs ← (gridRuns task opt).mapM fun r => do return ((← cfg r .lr), (← final r .train_cost))
  let best ← costs.foldl (fun acc c => match acc with
    | none => some c
    | some b => if decide (c.2 < b.2) then some c else some b) none
  return decide (best.1 ≈ lr)

/-- The chosen rate is not at either end of the grid, so a wider grid would not change it
in the obvious direction. -/
def interior (task opt : String) : Option Bool := do
  let lr ← bestLr task opt
  let lrs := gridLrs task opt
  return lrs.any (fun x => decide (x < lr)) && lrs.any (fun x => decide (lr < x))

def meanCostAt (rs : List Run) (epoch : Nat) : Option Q := do
  if rs.length != 3 then none
  Stats.mean? (← rs.mapM (costAt · epoch))

def epochs (task : String) : Option Nat := do
  let r ← (best task "adam").head?
  (cfg r .epochs).bind Q.toNat?

/-- Optimizer `a` has lower mean training cost than `b` at every epoch. -/
def lowerEveryEpoch (task a b : String) : Option Bool := do
  let n ← epochs task
  allOf ((List.range n).map (· + 1)) fun e => do
    return decide ((← meanCostAt (best task a) e) < (← meanCostAt (best task b) e))

/-- ... at the last epoch. -/
def lowerAtEnd (task a b : String) : Option Bool := do
  let n ← epochs task
  return decide ((← meanCostAt (best task a) n) < (← meanCostAt (best task b) n))

/-- Final mean costs within a factor `1 + tol` of each other. -/
def similarAtEnd (task a b : String) (tol : Q) : Option Bool := do
  let n ← epochs task
  let x ← meanCostAt (best task a) n
  let y ← meanCostAt (best task b) n
  return decide (x ≤ (1 + tol) * y) && decide (y ≤ (1 + tol) * x)

/-- Number of epochs at which `a`'s mean cost is below `b`'s. -/
def epochsBelow (task a b : String) : Option Nat := do
  let n ← epochs task
  let below ← ((List.range n).map (· + 1)).filterM fun e => do
    return decide ((← meanCostAt (best task a) e) < (← meanCostAt (best task b) e))
  return below.length

def finalCosts (task opt : String) : Option (List Q) := do
  let n ← epochs task
  (best task opt).mapM (costAt · n)

/-- The three-seed final costs of `a` and `b` differ significantly by Welch's t-test at
`t > 2.776` (two-sided 95% with 4 degrees of freedom, the most Welch's test allows for
three seeds each). -/
def significantAtEnd (task a b : String) : Option Bool := do
  Stats.welchExceeds? (← finalCosts task a) (← finalCosts task b) 2.776

def tasks : List (String × List String) :=
  [("logreg", ["adam", "sgd_nesterov", "adagrad"]),
   ("mlp", ["adam", "sgd_nesterov", "adagrad", "rmsprop", "adadelta"]),
   ("cnn", ["adam", "sgd_nesterov", "adagrad"])]

/-- Every optimizer's rate was chosen by the rule Section 6 describes, from the interior
of its grid, and was rerun on three seeds. -/
theorem learning_rates_chosen_from_grid_interior :
    holds (allOf tasks fun (task, opts) => allOf opts fun opt => do
      return (← selectionFollowsGrid task opt) && (← interior task opt) &&
        (best task opt).length == 3) := by
  decide +kernel

/-! ## 6.1 Logistic regression on MNIST

"we found that the Adam yields similar convergence as SGD with momentum and both converge
faster than Adagrad." -/

/-- The first half holds: from the second epoch on, Adam's and SGD-Nesterov's mean costs
are within 0.5% of each other. -/
theorem logreg_adam_similar_to_sgd :
    holds (do
      let n ← epochs "logreg"
      allOf ((List.range (n - 1)).map (· + 2)) fun e => do
        let a ← meanCostAt (best "logreg" "adam") e
        let s ← meanCostAt (best "logreg" "sgd_nesterov") e
        return decide (a ≤ 1.005 * s) && decide (s ≤ 1.005 * a)) := by
  decide +kernel

/-- The second half does not: Adagrad's cost is below SGD-Nesterov's at every epoch and
below Adam's for the first three; all three end within 0.2% of each other, and the final
gap between Adam and Adagrad is not significant. -/
theorem logreg_neither_faster_than_adagrad :
    lowerEveryEpoch "logreg" "adagrad" "sgd_nesterov" = some true ∧
    epochsBelow "logreg" "adagrad" "adam" = some 3 ∧
    similarAtEnd "logreg" "adam" "adagrad" 0.002 = some true ∧
    similarAtEnd "logreg" "sgd_nesterov" "adagrad" 0.002 = some true ∧
    significantAtEnd "logreg" "adam" "adagrad" = some false := by
  decide +kernel

/-! ## 6.2 Multi-layer network with dropout on MNIST

"Adam shows better convergence than other methods." -/

/-- Adam ends below SGD-Nesterov, Adagrad and AdaDelta... -/
theorem mlp_adam_below_sgd_adagrad_adadelta :
    lowerAtEnd "mlp" "adam" "sgd_nesterov" = some true ∧
    lowerAtEnd "mlp" "adam" "adagrad" = some true ∧
    lowerAtEnd "mlp" "adam" "adadelta" = some true := by
  decide +kernel

/-- ...but not below RMSProp, which is lower at 19 of the 20 epochs, including the
last. The final difference is not significant, so the data supports "Adam and RMSProp
are tied", not "Adam is better than other methods". -/
theorem mlp_rmsprop_below_adam :
    epochsBelow "mlp" "rmsprop" "adam" = some 19 ∧
    lowerAtEnd "mlp" "rmsprop" "adam" = some true ∧
    significantAtEnd "mlp" "rmsprop" "adam" = some false := by
  decide +kernel

/-! ## 6.3 Convolutional network with dropout on CIFAR-10

"Adam and SGD eventually converge considerably faster than Adagrad ... We notice the
second moment estimate v̂_t vanishes to zeros after a few epochs and is dominated by the
ε in algorithm 1 ... Adam shows marginal improvement over SGD with momentum." -/

/-- Holds: Adam and SGD-Nesterov are below Adagrad at every epoch, and end at less than
half its cost. -/
theorem cnn_adam_and_sgd_far_below_adagrad :
    lowerEveryEpoch "cnn" "adam" "adagrad" = some true ∧
    lowerEveryEpoch "cnn" "sgd_nesterov" "adagrad" = some true ∧
    (do return decide ((← meanCostAt (best "cnn" "adam") 15) * 2 < (← meanCostAt (best "cnn" "adagrad") 15))) = some true ∧
    (do return decide ((← meanCostAt (best "cnn" "sgd_nesterov") 15) * 2 < (← meanCostAt (best "cnn" "adagrad") 15))) = some true := by
  decide +kernel

/-- "Marginal" is right, in the weakest sense: Adam ends 0.1% below SGD-Nesterov, a
difference that is not significant, after SGD-Nesterov was lower at epochs 2 through 14. -/
theorem cnn_adam_marginally_below_sgd :
    lowerAtEnd "cnn" "adam" "sgd_nesterov" = some true ∧
    similarAtEnd "cnn" "adam" "sgd_nesterov" 0.001 = some true ∧
    epochsBelow "cnn" "sgd_nesterov" "adam" = some 13 ∧
    significantAtEnd "cnn" "adam" "sgd_nesterov" = some false := by
  decide +kernel

/-- The paper's explanation fails: `√v̂` does not vanish. In every CNN run with Adam, at
every epoch, at most 6% of the coordinates have `√v̂_t < ε`; at the chosen learning rate
the median `√v̂_t` is more than 20,000 times ε. -/
theorem cnn_vhat_not_dominated_by_eps :
    let cnnAdam := runs.filter (isTask "cnn" "adam")
    cnnAdam.length = 5 ∧
    cnnAdam.all (fun r => (series r .adam_frac_sqrt_vhat_below_eps).length == 15 &&
      (series r .adam_frac_sqrt_vhat_below_eps).all (fun p => decide (p.2 ≤ 0.06))) = true ∧
    (best "cnn" "adam").all (fun r =>
      (series r .adam_sqrt_vhat_over_eps_median).all (fun p => decide (20000 < p.2))) = true := by
  decide +kernel

/-- In the first three epochs, where the paper says "both Adam and Adagrad make rapid
progress", Adagrad has the highest cost of the three at every epoch. -/
theorem cnn_adagrad_slowest_early :
    (allOf [1, 2, 3] fun e => do
      let g ← meanCostAt (best "cnn" "adagrad") e
      return decide ((← meanCostAt (best "cnn" "adam") e) < g) &&
        decide ((← meanCostAt (best "cnn" "sgd_nesterov") e) < g)) = some true := by
  decide +kernel

end Claims
