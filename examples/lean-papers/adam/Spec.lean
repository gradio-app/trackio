import Trackio

/-!
# "Adam: A Method for Stochastic Optimization": the algorithm and its stated bounds

Kingma & Ba, arXiv:1412.6980v9 (ICLR 2015). Algorithm 1 for one coordinate, in exact
rational arithmetic; square roots are enclosed in intervals (`Trackio.Exact.sqrt`).
Gradients are given, so every quantity below is computed, not estimated.
-/

open Trackio Exact

namespace Adam

structure Hyper where
  beta1 : Q
  beta2 : Q

def defaults : Hyper := ⟨0.9, 0.999⟩

def pow (b : Q) (t : Nat) : Q := (List.range t).foldl (fun acc _ => mul acc b) 1

/-- Algorithm 1's biased moments after the gradients `gs`:
`m_t = β₁ m_{t-1} + (1-β₁) g_t`, `v_t = β₂ v_{t-1} + (1-β₂) g_t²`. -/
def moments (h : Hyper) (gs : List Q) : Q × Q :=
  gs.foldl (fun (mv : Q × Q) g =>
    (add (mul h.beta1 mv.1) (mul (1 - h.beta1) g), add (mul h.beta2 mv.2) (mul (1 - h.beta2) (mul g g))))
    (0, 0)

/-- Bias-corrected moments `m̂_t = m_t / (1 - β₁ᵗ)`, `v̂_t = v_t / (1 - β₂ᵗ)`. -/
def corrected (h : Hyper) (gs : List Q) : Q × Q :=
  let (m, v) := moments h gs
  (div m (1 - pow h.beta1 gs.length), div v (1 - pow h.beta2 gs.length))

def geometric (r : Q) (n : Nat) : List Q := (List.range n).map (pow r)

/-- Algorithm 1 on one parameter, with ε: the iterates `θ_1 .. θ_T` after the
gradients `gs`, starting from `θ_0`, as intervals containing the exact values.
`θ_t = θ_{t-1} − α · m̂_t / (√v̂_t + ε)`. -/
def run (h : Hyper) (alpha eps theta0 : Q) (gs : List Q) : Option (List Interval) :=
  let steps := (List.range gs.length).map fun i => corrected h (gs.take (i + 1))
  let result := steps.foldlM (fun (acc : Interval × List Interval) (mv : Q × Q) => do
    let s ← sqrt mv.2
    let denom := Interval.add s (Interval.exact eps)
    let delta := Interval.divPos (Interval.exact (mul alpha mv.1)) denom
    let theta := Interval.round (Interval.sub acc.1 delta)
    return (theta, acc.2 ++ [theta])) (Interval.exact theta0, [])
  match result with
  | some (_, thetas) => some thetas
  | none => none

/-! ## Section 2.1: "The effective stepsize has two upper bounds"

With `ε = 0` the step is `Δt = α · m̂_t / √v̂_t`. The paper states
`|Δt| ≤ α (1-β₁)/√(1-β₂)` when `(1-β₁) > √(1-β₂)`, and `|Δt| ≤ α` otherwise, adding
that when `(1-β₁) = √(1-β₂)`, `|m̂_t / √v̂_t| < 1`. Squaring keeps it rational:
the bound fails exactly when `m̂² > B² v̂`. -/

def claimedBoundSq (h : Hyper) : Q :=
  let a := mul (1 - h.beta1) (1 - h.beta1)
  if decide (1 - h.beta2 < a) then div a (1 - h.beta2) else 1

def exceedsClaimedBound (h : Hyper) (gs : List Q) : Bool :=
  let (mh, vh) := corrected h gs
  decide (mul (claimedBoundSq h) vh < mul mh mh)

/-- At the defaults (β₁ = 0.9, β₂ = 0.999), the first case applies and the claimed
bound is `α · 0.1/√0.001 ≈ 3.16α`. Gradients growing by 10/9 per step break it at
step 210. -/
theorem step_bound_fails_at_defaults :
    claimedBoundSq defaults ≈ 10 ∧ exceedsClaimedBound defaults (geometric (q 10 9) 210) = true := by
  decide +kernel

/-- The equality case, β₁ = 0.9, β₂ = 0.99, where the paper says `|m̂/√v̂| < 1`: two
gradients, 1 then 10/9, already give `|Δt| > α`. -/
theorem step_bound_fails_in_equality_case :
    (1 - (0.9 : Q)) * (1 - 0.9) ≈ 1 - (0.99 : Q) ∧
    exceedsClaimedBound ⟨0.9, 0.99⟩ [1, q 10 9] = true := by
  decide +kernel

/-- The strict "otherwise" case, β₁ = 0.9, β₂ = 0.98, where `|Δt| ≤ α` is claimed. -/
theorem step_bound_fails_in_otherwise_case :
    claimedBoundSq ⟨0.9, 0.98⟩ ≈ 1 ∧ exceedsClaimedBound ⟨0.9, 0.98⟩ [1, q 10 9] = true := by
  decide +kernel

/-- The paper's own worst case, a gradient that is zero until the current step, does
satisfy the bound at the defaults (here at step 300). -/
theorem step_bound_holds_for_single_spike :
    exceedsClaimedBound defaults ((List.replicate 299 0) ++ [1]) = false := by
  decide +kernel

/-! ## Section 7.1: AdaMax, "|Δt| ≤ α"

`u_t = max(β₂ u_{t-1}, |g_t|)`, `Δt = (α / (1 - β₁ᵗ)) · m_t / u_t`. -/

def adamaxRatio (h : Hyper) (gs : List Q) : Q :=
  let (m, u) := gs.foldl (fun (mu : Q × Q) g =>
    (add (mul h.beta1 mu.1) (mul (1 - h.beta1) g), Q.max (mul h.beta2 mu.2) (Q.abs g))) (0, 0)
  div (Q.abs m) (mul (1 - pow h.beta1 gs.length) u)

/-- Two gradients, 1 then 0.999, give `|Δt| ≈ 1.0005α > α` at the defaults... -/
theorem adamax_bound_fails :
    decide (1 < adamaxRatio defaults [1, 0.999]) = true := by
  decide +kernel

/-- ...and gradients shrinking by β₂ per step push it past 1.009α (the limit is
`(1-β₁)/(1-β₁/β₂) = 111/110`). -/
theorem adamax_bound_fails_by_0_9_percent :
    decide (1.009 < adamaxRatio defaults (geometric 0.999 300)) = true := by
  decide +kernel

/-! ## Section 4: Theorem 4.1 on Reddi, Kale & Kumar's counterexample

Online convex optimization on `F = [-1, 1]` with `f_t(x) = C x` when `t mod 3 = 1` and
`f_t(x) = -x` otherwise (Reddi et al., ICLR 2018, Theorem 1), `C = 4`. Run Algorithm 1
(bias correction included, `ε = 0`) with β₁ = 0 (so β₁,t = β₁λ^(t-1) = 0 for every λ),
β₂ = 1/(1+C²) = 1/17, `α_t = α/√t`, `α = 0.87`, projecting each iterate onto F as
Reddi et al. do; Theorem 4.1 assumes the iterates are bounded, here by `D = D∞ = 2`.
Gradients are bounded by `G = G∞ = C`, and `β₁²/√β₂ = 0 < 1`: all of Theorem 4.1's
assumptions hold. -/

namespace Reddi

def C : Q := 4
def beta2 : Q := q 1 17
def alpha : Q := 0.87
def h : Hyper := ⟨0, beta2⟩

def grad (t : Nat) : Q := if t % 3 == 1 then C else -1

def grads (T : Nat) : List Q := (List.range T).map fun i => grad (i + 1)

/-- `v̂_t` for t = 1..T, exact. -/
def vhats (T : Nat) : List Q :=
  (List.range T).map fun i => (corrected h (grads (i + 1))).2

/-- One projected step: `x_{t+1} = Π_F(x_t − α g_t / √(t · v̂_t))` (with `α_t = α/√t`
and β₁ = 0, `m̂_t = g_t`). -/
def stepX (x : Interval) (t : Nat) (vh : Q) : Option Interval := do
  let s ← sqrt (mul (q (t : Int)) vh)
  let stepI := Interval.divPos (Interval.exact (mul alpha (grad t))) s
  return Interval.round (Interval.clamp (Interval.sub x stepI) (-1) 1)

def iteratesFrom : List (Nat × Q) → Interval → Option (List Interval)
  | [], _ => some []
  | (t, vh) :: rest, x => do
    let x' ← stepX x t vh
    let xs ← iteratesFrom rest x'
    return x :: xs

/-- Iterates `x_1 .. x_T` (enclosed in intervals), starting from `x_1 = 1`. -/
def iterates (T : Nat) : Option (List Interval) :=
  iteratesFrom (((List.range T).map (· + 1)).zip (vhats T)) (Interval.exact 1)

/-- Regret against the best fixed point `x* = -1` (best because the gradients sum to a
positive number): `R(T) = Σ g_t (x_t + 1)`. -/
def regret (T : Nat) : Option Interval := do
  let xs ← iterates T
  return ((grads T).zip xs).foldl (fun acc (g, x) =>
    Interval.add acc (Interval.mul (Interval.exact g) (Interval.add x (Interval.exact 1)))) (Interval.exact 0)

/-- Theorem 4.1's right-hand side with `d = 1`, `β₁ = 0` (so `γ = 0`), `D = D∞ = 2`,
`G∞ = C`, for a given λ:
`D²/(2α) √(T v̂_T) + α G∞/√(1−β₂) ‖g_{1:T}‖₂ + D∞² G∞ √(1−β₂) / (2α (1−λ)²)`. -/
def bound (T : Nat) (lam : Q) : Option Interval := do
  let vT ← (vhats T).getLast?
  let a ← sqrt (mul (q (T : Int)) vT)
  let b ← sqrt ((grads T).foldl (fun s g => add s (mul g g)) 0)
  let r ← sqrt (1 - beta2)
  let term1 := Interval.mul (Interval.exact (div 4 (mul 2 alpha))) a
  let term2 := Interval.divPos (Interval.mul (Interval.exact (mul alpha C)) b) r
  let term3 := Interval.divPos (Interval.mul (Interval.exact (mul 4 C)) r)
    (Interval.exact (mul (mul 2 alpha) (mul (1 - lam) (1 - lam))))
  return Interval.add (Interval.add term1 term2) term3

/-- After 90 steps Adam's regret exceeds the bound Theorem 4.1 guarantees (taking
λ = 0.01): the theorem, as stated, is false. -/
theorem theorem_4_1_fails :
    (do let r ← regret 90; let b ← bound 90 0.01; return Interval.lt b r) = some true := by
  decide +kernel

/-- The step Reddi et al. identify: the proof assumes
`Γ_{t+1} = √v̂_{t+1}/α_{t+1} − √v̂_t/α_t ≥ 0`. With `α_t = α/√t` that is
`(t+1) v̂_{t+1} ≥ t v̂_t`, and it fails on 60 of the steps 2..90. -/
def gammaNegativeSteps (T : Nat) : Nat :=
  let vs := vhats T
  ((List.range (T - 1)).filter fun (i : Nat) =>
    decide (mul (q ((i + 2 : Nat) : Int)) (vs.getD (i + 1) 0) < mul (q ((i + 1 : Nat) : Int)) (vs.getD i 0))).length

theorem gamma_not_positive : gammaNegativeSteps 90 = 60 := by
  decide +kernel

/-- Reddi et al.'s step size condition, `α < √(1−β₂)`, holds (not needed by Theorem 4.1). -/
theorem alpha_below_sqrt_one_minus_beta2 : decide (alpha * alpha < 1 - beta2) = true := by
  decide +kernel

end Reddi

end Adam

#print axioms Adam.Reddi.theorem_4_1_fails
