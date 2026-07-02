# Trackio Logbooks — sharing open experiments

A **logbook** is a shareable, Hub-native lab notebook for an experiment campaign, stored in `./.trackio/logbook/` (found by walking up from the cwd, like `.git`). It publishes to a static Hugging Face Space that renders a rich human view — a main page listing experiments, nested experiment pages, and unfurled links (models, datasets, dashboards, artifacts) — while a flattened `logbook.md` stays token-efficient for other agents.

The logbook is **just files you edit directly**. There are only a few CLI commands; everything else is a normal file edit.

## The few CLI commands

```bash
trackio logbook open [username/space]                   # scaffold ./.trackio/logbook/ (run once)
trackio logbook note "<finding>" --experiment "<Name>"  # log a finding onto an experiment (creates it if new)
trackio logbook serve                                   # preview locally
trackio logbook publish [username/space]                # first publish (public gate) → enables auto-sync
trackio logbook sync                                    # push later edits to the Space now
```

`note` **appends** — you never clobber notes someone else wrote. Everything else is a direct file edit.

## The structure

- **The main page** (`pages/index.md`) is the **table of contents only** — an `## Experiments` table of `| Status | Experiment |`, one row per experiment, each linking to that experiment's page. **Never write findings here.**
- **Each experiment has its own page** where findings accumulate.

## Start by seeding the plan into the table of contents

As soon as you have a plan for the campaign (e.g. when you'd write a to-do list or leave plan mode), **map its major steps to experiments** so the table of contents reflects the plan up front:

```bash
trackio logbook plan "Run baselines" "LoRA SFT" "Full fine-tune"
```

Each becomes a `planned` row (and a page). This is the single most important habit — the reader should see the shape of the whole campaign, not just whatever has finished. Re-run `plan` to append steps as the plan evolves. Then, as you work, advance each with `--status`:

```bash
trackio logbook note "Instruct baseline = 24.4% exec acc; target to beat." --experiment "Run baselines" --status done
```

## Logging findings — always onto an experiment

```bash
trackio logbook note "Zero-shot baseline: 41% valid; need SFT." --experiment "Baseline" --status done
trackio logbook note "3e-4 wins; 1e-3 diverges ~300 steps." --experiment "LR sweep" --status in-progress --link ...
```

`--experiment "Name"` **creates the experiment page + adds its row to the index** the first time, and appends to it thereafter. `--status` (`planned`/`in-progress`/`done`/`blocked`) sets the badge on its index row. This keeps the main page a clean TOC automatically — you never edit the index by hand for this.

## When to `note` (high bar — signal, not noise)

An experiment **concluded** with a result; a **decision** + rationale; a **surprise / dead end**; a **baseline** worth anchoring to. Not routine commands or scratch. A baseline measurement is its own experiment — log it with `--experiment "Baseline"` before moving on.

## Also editable directly (your normal file tools)

Any page's content, the index table, and the styling (`logbook.css` / `index.html` / `logbook.js`, which live inside the logbook) are plain files — edit them when the CLI verbs aren't enough. `serve` to preview and fix.

- `--title`: a short, result-bearing headline ("96.4% valid — target met").
- Body: 1–3 sentences with the number and what it means. **Tabular results** (baselines, sweeps, ablations) → write a **Markdown table** in the body, not prose — it renders as a real table.
- `--link URL`: models/datasets/Spaces/dashboards/arXiv/GitHub/images — each unfurls into a card. Pass each as a **separate `--link` flag**, never inside the body text. A URL only unfurls when it's on its own line.
- `--artifact project/name:vN`: reference a tracked Trackio artifact.
- It's just Markdown you can also edit by hand — if something renders wrong, `serve` to preview and fix the file directly.

## Publishing & privacy

- **Local until the first `publish`** — nothing leaves the machine, so drafts are safe. Scan for secrets/paths before that first publish; static Spaces are **public**.
- After the first `publish`, `note`/`page` auto-sync in the background. After a **direct file edit**, run `trackio logbook sync` to push it.
- The remote Space is remembered in `./.trackio/metadata.json`, so `publish`/`sync` need no argument after the first time.
