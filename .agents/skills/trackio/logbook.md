# Trackio Logbooks — sharing open experiments

A **logbook** is a shareable, Hub-native lab notebook for an experiment campaign. You (the agent) write short findings as you run experiments; they publish to a static Hugging Face Space that renders a rich human view and unfurls every linked artifact, model, dataset, and dashboard — while staying token-efficient for other agents that read it.

The **human** owns creation (via the `/logbook` slash command or `trackio logbook open`). **You** own the cadence: log findings when they happen.

## Lifecycle

```bash
trackio logbook open [username/space] --title "..."   # start / attach (usually run by the user)
trackio logbook note "<finding>" [options]            # append a finding  ← your main job
trackio logbook page "<Title>" [--parent SLUG]        # create a subpage
trackio logbook status                                # show the tree
trackio logbook serve                                 # preview locally
trackio logbook publish [username/space]              # deploy to a static Space
trackio logbook close [username/space]                # publish + clear active
```

## When to log a `note` (high bar — signal, not noise)

Log when something is **worth another human or agent knowing later**:

- An experiment **concluded** with a result ("lr=3e-4 → 96.4% valid, target met").
- A **decision** and its rationale ("chose QLoRA r=16 to fit under 10GB").
- A **surprise / dead end** ("lr=1e-3 diverged after 300 steps").
- A **baseline** or metric worth anchoring to.

Do **not** log routine commands, intermediate scratch, or every step. One good finding per real result.

## Writing good notes

- `--title` a short, result-bearing headline ("96.4% valid — target met"), not "update".
- Body: 1–3 sentences. State the number and what it means.
- `--link URL` for anything with a URL — HF models/datasets/Spaces, trackio dashboards, arXiv, GitHub, image URLs. These unfurl into rich cards; put each on its own `--link`. Never paste long content the reader can reach by link.
- `--artifact project/name:vN` to reference a tracked Trackio artifact (checkpoints, adapters).
- `--page SLUG` to file the note under a subpage. Organize a campaign into pages: setup, sweeps, final results.

## Example session

```bash
trackio logbook note "Zero-shot baseline is rough: 41% schema-valid." --title "Baseline: 41%" --page setup \
  --link https://huggingface.co/google/gemma-2-2b-it
trackio logbook note "lr=3e-4 wins; 1e-3 diverges." --title "LR sweep" --page lr-sweep \
  --link runs/lr_sweep.png --artifact myproj/lora:v3
```

## Notes

- Everything is **local until `publish`** — nothing leaves the machine, so drafts are safe. Scan a note for secrets/paths before it goes into a published logbook.
- Static Spaces are public; do not publish private data.
- The raw markdown (`logbook.md`) is the agent-facing view — terse text + URLs. Fetch that, not the HTML, when reading someone else's logbook.
