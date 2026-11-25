/-!
# The Transformer as a Lean program

The model in `train_ablation.py` is not written by hand. It is this file's
`transformer` program, turned into PyTorch by `Codegen.lean`
(`lake exe codegen`), so theorems about the program are theorems about the code
that trains.

A program is a list of primitive operations in single-assignment form: each
operation refers to earlier results by index. Every operation has three meanings:

- `shapeOf`: the shape it produces (a program type-checks when every step has one),
- `Deps.step`: which input tokens each output position can depend on,
- `Codegen.pythonOf`: the PyTorch expression it becomes.

Only the generated PyTorch computes numbers. The dependency semantics is an
over-approximation: an output may depend on fewer inputs than it says, never more.
-/

namespace Model

/-- A tensor axis: the batch, the source or target length, or a fixed size. -/
inductive Dim where
  | batch
  | srcLen
  | tgtLen
  | n (k : Nat)
  deriving DecidableEq, Repr

abbrev Shape := List Dim

inductive Init where
  | embedding
  | linearWeight
  | linearBias (fanIn : Nat)
  | ones
  | zeros
  deriving DecidableEq, Repr

/-- One primitive operation. `Nat` arguments are indices of earlier steps. -/
inductive Op where
  | srcTokens
  | tgtTokens
  | targets
  | memory (d : Nat)
  | input (len : Dim) (d : Nat)
  | param (name : String) (shape : List Nat) (init : Init)
  | embed (table ids : Nat)
  | scaleSqrt (k x : Nat)
  | addPositions (x : Nat)
  | dropout (x : Nat)
  | linear (w x : Nat)
  | linearBias (w b x : Nat)
  | add (x y : Nat)
  | relu (x : Nat)
  | layerNorm (g b x : Nat)
  | splitHeads (h x : Nat)
  | mergeHeads (x : Nat)
  | scores (q k : Nat)
  | scaleInvSqrt (k x : Nat)
  | maskFuture (x : Nat)
  | maskPadKeys (ids x : Nat)
  | softmax (x : Nat)
  | weighted (p v : Nat)
  | tiedLogits (x table : Nat)
  | crossEntropy (logits targets : Nat) (epsNum epsDen : Nat)
  deriving Repr

abbrev Program := Array Op

/-! ## Building programs -/

abbrev Build := StateM Program

def emit (op : Op) : Build Nat := modifyGet fun p => (p.size, p.push op)

/-- Model hyperparameters, named as in Table 3. -/
structure Config where
  N : Nat
  dModel : Nat
  dFF : Nat
  h : Nat
  dk : Nat
  dv : Nat
  vocab : Nat
  pDrop : String
  epsNum : Nat
  epsDen : Nat
  deriving Repr

inductive Mask where
  | none
  | future
  | padKeys (ids : Nat)

def linearW (name : String) (outD inD : Nat) : Build Nat :=
  emit (.param name [outD, inD] .linearWeight)

/-- Equation 1, per head: `softmax(Q Kᵀ / √d_k) V`, with an optional mask on the
scores before the softmax (Section 3.2.3). -/
def scaledDotProductAttention (q k v dk : Nat) (mask : Mask) : Build Nat := do
  let s ← emit (.scores q k)
  let s ← emit (.scaleInvSqrt dk s)
  let s ← match mask with
    | .none => pure s
    | .future => emit (.maskFuture s)
    | .padKeys ids => emit (.maskPadKeys ids s)
  let p ← emit (.softmax s)
  emit (.weighted p v)

/-- Section 3.2.2: `MultiHead(Q, K, V) = Concat(head₁, …, head_h) W^O` with
`head_i = Attention(Q W_i^Q, K W_i^K, V W_i^V)`. -/
def multiHead (c : Config) (pre : String) (xq xkv : Nat) (mask : Mask) : Build Nat := do
  let wq ← linearW s!"{pre}_wq" (c.h * c.dk) c.dModel
  let wk ← linearW s!"{pre}_wk" (c.h * c.dk) c.dModel
  let wv ← linearW s!"{pre}_wv" (c.h * c.dv) c.dModel
  let wo ← linearW s!"{pre}_wo" c.dModel (c.h * c.dv)
  let q ← emit (.splitHeads c.h (← emit (.linear wq xq)))
  let k ← emit (.splitHeads c.h (← emit (.linear wk xkv)))
  let v ← emit (.splitHeads c.h (← emit (.linear wv xkv)))
  let heads ← scaledDotProductAttention q k v c.dk mask
  emit (.linear wo (← emit (.mergeHeads heads)))

/-- Section 3.3: `FFN(x) = max(0, x W₁ + b₁) W₂ + b₂`. -/
def feedForward (c : Config) (pre : String) (x : Nat) : Build Nat := do
  let w1 ← linearW s!"{pre}_w1" c.dFF c.dModel
  let b1 ← emit (.param s!"{pre}_b1" [c.dFF] (.linearBias c.dModel))
  let w2 ← linearW s!"{pre}_w2" c.dModel c.dFF
  let b2 ← emit (.param s!"{pre}_b2" [c.dModel] (.linearBias c.dFF))
  let hdn ← emit (.relu (← emit (.linearBias w1 b1 x)))
  emit (.linearBias w2 b2 hdn)

/-- Section 3.1: `LayerNorm(x + Dropout(Sublayer(x)))` (dropout from Section 5.4). -/
def residualNorm (c : Config) (pre : String) (x sub : Nat) : Build Nat := do
  let g ← emit (.param s!"{pre}_gain" [c.dModel] .ones)
  let b ← emit (.param s!"{pre}_bias" [c.dModel] .zeros)
  let y ← emit (.add x (← emit (.dropout sub)))
  emit (.layerNorm g b y)

/-- Section 3.4: one embedding matrix, scaled by `√d_model`, plus positional
encodings (Section 3.5), with dropout on the sum (Section 5.4). -/
def embedTokens (c : Config) (ids : Nat) : Build Nat := do
  let table ← emit (.param "embedding" [c.vocab, c.dModel] .embedding)
  let x ← emit (.scaleSqrt c.dModel (← emit (.embed table ids)))
  emit (.dropout (← emit (.addPositions x)))

def encoderLayer (c : Config) (src : Nat) (i x : Nat) : Build Nat := do
  let a ← multiHead c s!"enc{i}_attn" x x (.padKeys src)
  let x ← residualNorm c s!"enc{i}_norm1" x a
  let f ← feedForward c s!"enc{i}_ffn" x
  residualNorm c s!"enc{i}_norm2" x f

def decoderLayer (c : Config) (src mem : Nat) (i y : Nat) : Build Nat := do
  let a ← multiHead c s!"dec{i}_self" y y .future
  let y ← residualNorm c s!"dec{i}_norm1" y a
  let a ← multiHead c s!"dec{i}_cross" y mem (.padKeys src)
  let y ← residualNorm c s!"dec{i}_norm2" y a
  let f ← feedForward c s!"dec{i}_ffn" y
  residualNorm c s!"dec{i}_norm3" y f

def stack (n : Nat) (layer : Nat → Nat → Build Nat) (x : Nat) : Build Nat :=
  (List.range n).foldlM (fun acc i => layer i acc) x

def encoder (c : Config) : Build Nat := do
  let src ← emit .srcTokens
  let x ← embedTokens c src
  stack c.N (encoderLayer c src) x

def decoder (c : Config) : Build Nat := do
  let src ← emit .srcTokens
  let mem ← emit (.memory c.dModel)
  let tgt ← emit .tgtTokens
  let y ← embedTokens c tgt
  let y ← stack c.N (decoderLayer c src mem) y
  let table ← emit (.param "embedding" [c.vocab, c.dModel] .embedding)
  emit (.tiedLogits y table)

/-- Label-smoothed cross-entropy (Section 5.4) on the decoder's logits. -/
def loss (c : Config) : Build Nat := do
  let logits ← emit (.input .tgtLen c.vocab)
  let t ← emit .targets
  emit (.crossEntropy logits t c.epsNum c.epsDen)

/-- A program and the index of its result. -/
structure Built where
  prog : Program
  out : Nat

def build (b : Build Nat) : Built :=
  let (out, prog) := b.run #[]
  ⟨prog, out⟩

/-! ## Configurations trained in `train_ablation.py` -/

def base : Config :=
  { N := 3, dModel := 256, dFF := 1024, h := 8, dk := 32, dv := 32, vocab := 8000,
    pDrop := "0.1", epsNum := 1, epsDen := 10 }

def variants : List (String × Config) :=
  [("base", base),
   ("h1", { base with h := 1, dk := 256, dv := 256 }),
   ("dk8", { base with dk := 8 }),
   ("ls0", { base with epsNum := 0 })]

/-- The attention probe: `multiHead` at a tiny size, unmasked and masked. -/
def probeConfig : Config :=
  { base with dModel := 4, h := 2, dk := 4, dv := 2 }

def probe (mask : Mask) : Built := build do
  let x ← emit (.input (.n 3) probeConfig.dModel)
  multiHead probeConfig "probe" x x mask

/-! ## Shapes -/

def shapeAt (shapes : Array (Option Shape)) (i : Nat) : Option Shape :=
  (shapes[i]?).bind id

def dimsOf : List Nat → Shape := List.map Dim.n

def shapeOf (shapes : Array (Option Shape)) : Op → Option Shape
  | .srcTokens => some [.batch, .srcLen]
  | .tgtTokens => some [.batch, .tgtLen]
  | .targets => some [.batch, .tgtLen]
  | .memory d => some [.batch, .srcLen, .n d]
  | .input len d => some [.batch, len, .n d]
  | .param _ s _ => some (dimsOf s)
  | .embed t ids => do
      let [.n _, .n d] ← shapeAt shapes t | none
      let [b, l] ← shapeAt shapes ids | none
      return [b, l, .n d]
  | .scaleSqrt _ x | .dropout x | .relu x | .softmax x => shapeAt shapes x
  | .scaleInvSqrt _ x => shapeAt shapes x
  | .addPositions x => do
      let s ← shapeAt shapes x
      if s.length == 3 then some s else none
  | .linear w x => do
      let [.n o, .n i] ← shapeAt shapes w | none
      let s ← shapeAt shapes x
      if s.getLast? == some (.n i) then some (s.dropLast ++ [.n o]) else none
  | .linearBias w b x => do
      let [.n o, .n i] ← shapeAt shapes w | none
      let [.n o'] ← shapeAt shapes b | none
      let s ← shapeAt shapes x
      if o == o' && s.getLast? == some (.n i) then some (s.dropLast ++ [.n o]) else none
  | .add x y => do
      let a ← shapeAt shapes x
      let b ← shapeAt shapes y
      if a == b then some a else none
  | .layerNorm g b x => do
      let [.n d] ← shapeAt shapes g | none
      let [.n d'] ← shapeAt shapes b | none
      let s ← shapeAt shapes x
      if d == d' && s.getLast? == some (.n d) then some s else none
  | .splitHeads h x => do
      let [b, l, .n m] ← shapeAt shapes x | none
      if h > 0 && m % h == 0 then some [b, .n h, l, .n (m / h)] else none
  | .mergeHeads x => do
      let [b, .n h, l, .n k] ← shapeAt shapes x | none
      return [b, l, .n (h * k)]
  | .scores q k => do
      let [b, h, l, d] ← shapeAt shapes q | none
      let [b', h', l', d'] ← shapeAt shapes k | none
      if b == b' && h == h' && d == d' then some [b, h, l, l'] else none
  | .maskFuture x => do
      let s ← shapeAt shapes x
      let [_, _, l, l'] := s | none
      if l == l' then some s else none
  | .maskPadKeys ids x => do
      let [b, l'] ← shapeAt shapes ids | none
      let s ← shapeAt shapes x
      let [b', _, _, l''] := s | none
      if b == b' && l' == l'' then some s else none
  | .weighted p v => do
      let [b, h, l, l'] ← shapeAt shapes p | none
      let [b', h', l'', k] ← shapeAt shapes v | none
      if b == b' && h == h' && l' == l'' then some [b, h, l, k] else none
  | .tiedLogits x t => do
      let [b, l, .n d] ← shapeAt shapes x | none
      let [.n vocab, .n d'] ← shapeAt shapes t | none
      if d == d' then some [b, l, .n vocab] else none
  | .crossEntropy lg t _ _ => do
      let [b, l, .n _] ← shapeAt shapes lg | none
      let [b', l'] ← shapeAt shapes t | none
      if b == b' && l == l' then some [] else none

def shapes (p : Program) : Array (Option Shape) :=
  p.foldl (fun acc op => acc.push (shapeOf acc op)) #[]

/-- Every step of the program has a shape. -/
def wellTyped (b : Built) : Bool :=
  (shapes b.prog).all Option.isSome

def outShape (b : Built) : Option Shape := shapeAt (shapes b.prog) b.out

/-! ## Parameters -/

/-- Each distinct parameter once (the embedding is shared by name). -/
def params (progs : List Program) : List (String × List Nat) :=
  progs.foldl (fun acc p => p.foldl (fun acc op => match op with
    | .param name s _ => if acc.any (·.1 == name) then acc else acc ++ [(name, s)]
    | _ => acc) acc) []

def paramCount (progs : List Program) : Nat :=
  (params progs).foldl (fun n p => n + p.2.foldl (· * ·) 1) 0

/-! ## Dependencies

An input atom names one token: its stream (source 0, decoder input 1, target 2),
example `b` and position `t`. Each value records, per example and position, the
atoms it may depend on; feature axes are folded in, since every operation may
mix features within a position.
-/

abbrev Deps := List Nat

def atom (stream b t : Nat) : Nat := stream * 1000000 + b * 1000 + t

def union (a b : Deps) : Deps := b.foldl (fun acc x => if acc.contains x then acc else acc ++ [x]) a

def unionAll (ds : List Deps) : Deps := ds.foldl union []

/-- An attention score is either masked to `-∞` (a constant) or live. -/
inductive Elem where
  | masked
  | live (d : Deps)

def Elem.deps : Elem → Deps
  | .masked => []
  | .live d => d

/-- Abstract values: constants (parameters), per-position values `[b][t]`,
per-head values `[b][h][t]`, attention scores `[b][h][t][t']`, or a scalar. -/
inductive AV where
  | const
  | seq (v : List (List Deps))
  | heads (v : List (List (List Deps)))
  | att (v : List (List (List (List Elem))))
  | scalar (d : Deps)

structure Sizes where
  batch : Nat
  src : Nat
  tgt : Nat

def Sizes.len (z : Sizes) : Dim → Nat
  | .srcLen => z.src
  | .tgtLen => z.tgt
  | .batch => z.batch
  | .n k => k

def tokens (z : Sizes) (stream len : Nat) : AV :=
  .seq ((List.range z.batch).map fun b => (List.range len).map fun t => [atom stream b t])

def get (vs : Array AV) (i : Nat) : AV := (vs[i]?).getD .const

def zip2 {α β γ : Type} (f : α → β → γ) (a : List α) (b : List β) : List γ := List.zipWith f a b

def seqUnion : AV → AV → Option AV
  | .seq a, .seq b => some (.seq (zip2 (zip2 union) a b))
  | .seq a, .const => some (.seq a)
  | .const, .seq b => some (.seq b)
  | .const, .const => some .const
  | _, _ => none

def step (z : Sizes) (mem : AV) (vs : Array AV) : Op → Option AV
  | .srcTokens => some (tokens z 0 z.src)
  | .tgtTokens => some (tokens z 1 z.tgt)
  | .targets => some (tokens z 2 z.tgt)
  | .memory _ => some mem
  | .input len _ => some (.seq ((List.range z.batch).map fun _ => (List.range (z.len len)).map fun _ => []))
  | .param _ _ _ => some .const
  | .embed _ ids => some (get vs ids)
  | .scaleSqrt _ x | .addPositions x | .dropout x | .relu x => some (get vs x)
  | .linear _ x | .linearBias _ _ x | .layerNorm _ _ x | .tiedLogits x _ => some (get vs x)
  | .add x y => seqUnion (get vs x) (get vs y)
  | .scaleInvSqrt _ x => some (get vs x)
  | .splitHeads h x => match get vs x with
      | .seq v => some (.heads (v.map fun row => List.replicate h row))
      | _ => none
  | .mergeHeads x => match get vs x with
      | .heads v => some (.seq (v.map fun hs => (List.range ((hs.head?.getD []).length)).map fun t =>
          unionAll (hs.map fun row => row.getD t [])))
      | _ => none
  | .scores q k => match get vs q, get vs k with
      | .heads qv, .heads kv => some (.att (zip2 (zip2 fun qr kr =>
          qr.map fun qd => kr.map fun kd => Elem.live (union qd kd)) qv kv))
      | _, _ => none
  | .maskFuture x => match get vs x with
      | .att v => some (.att (v.map fun hs => hs.map fun rows =>
          (rows.zip (List.range rows.length)).map fun (row, t) =>
            (row.zip (List.range row.length)).map fun (e, t') => if t' > t then Elem.masked else e))
      | _ => none
  | .maskPadKeys ids x => match get vs ids, get vs x with
      | .seq iv, .att v => some (.att (zip2 (fun idRow hs => hs.map fun rows => rows.map fun row =>
          zip2 (fun e d => match e with | .masked => Elem.masked | .live d' => Elem.live (union d' d)) row idRow)
          iv v))
      | _, _ => none
  | .softmax x => match get vs x with
      | .att v => some (.att (v.map fun hs => hs.map fun rows => rows.map fun row =>
          let d := unionAll (row.map Elem.deps)
          row.map fun e => match e with | .masked => Elem.masked | .live _ => Elem.live d))
      | _ => none
  | .weighted p v => match get vs p, get vs v with
      | .att pv, .heads vv => some (.heads (zip2 (zip2 fun rows vrow =>
          rows.map fun row => unionAll (zip2 (fun e d => match e with
            | .masked => []
            | .live d' => union d' d) row vrow)) pv vv))
      | _, _ => none
  | .crossEntropy lg t _ _ => match get vs lg, get vs t with
      | .seq a, .seq b => some (.scalar (unionAll ((a ++ b).map unionAll)))
      | _, _ => none

def deps (z : Sizes) (mem : AV) (b : Built) : Option AV :=
  (b.prog.foldlM (fun acc op => do return acc.push (← step z mem acc op)) #[]).map (get · b.out)

/-- Logits at example `b`, position `t` may depend on example `b`'s source and on
its decoder inputs at positions `≤ t`, and on nothing else. -/
def allowed (b t a : Nat) : Bool :=
  let stream := a / 1000000
  let ex := (a % 1000000) / 1000
  let pos := a % 1000
  ex == b && (stream == 0 || (stream == 1 && pos ≤ t))

/-- The full model: the encoder's output feeds the decoder as `memory`. -/
def logitDeps (c : Config) (z : Sizes) : Option AV := do
  let mem ← deps z .const (build (encoder c))
  deps z mem (build (decoder c))

def noLeak (c : Config) (z : Sizes) : Bool :=
  match logitDeps c z with
  | some (.seq v) => (v.zip (List.range v.length)).all fun (row, b) =>
      (row.zip (List.range row.length)).all fun (d, t) => d.all (allowed b t)
  | _ => false

/-- The same property with the future mask removed from every step (a control). -/
def withoutFutureMask (b : Built) : Built :=
  { b with prog := b.prog.map fun op => match op with
    | .maskFuture x => .dropout x
    | op => op }

def noLeakWithoutMask (c : Config) (z : Sizes) : Bool :=
  match (do
    let mem ← deps z .const (build (encoder c))
    deps z mem (withoutFutureMask (build (decoder c)))) with
  | some (.seq v) => (v.zip (List.range v.length)).all fun (row, b) =>
      (row.zip (List.range row.length)).all fun (d, t) => d.all (allowed b t)
  | _ => false

/-- Logits do depend on the current decoder token and on the source: the
dependency semantics is not trivially empty. -/
def usesCurrentTokenAndSource (c : Config) (z : Sizes) : Bool :=
  match logitDeps c z with
  | some (.seq v) => (v.zip (List.range v.length)).all fun (row, b) =>
      (row.zip (List.range row.length)).all fun (d, t) =>
        d.contains (atom 1 b t) && (List.range z.src).all fun s => d.contains (atom 0 b s)
  | _ => false

end Model
