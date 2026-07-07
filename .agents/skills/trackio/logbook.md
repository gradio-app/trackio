# Trackio Logbooks — sharing open experiments

A **logbook** is a shareable, Hub-native lab notebook for an experiment campaign, stored in `./.trackio/logbook/` (found by walking up from the cwd, like `.git`). It publishes to a static Hugging Face Space that renders a rich human view — a main page listing experiments, nested experiment pages, and unfurled links (models, datasets, dashboards, artifacts) — while a flattened `logbook.md` remains available for other agents.

The logbook is **just files you edit directly**. There are only a few CLI commands; everything else is a normal file edit.

## The few CLI commands

```bash
trackio logbook open [username/space]                   # scaffold ./.trackio/logbook/ (run once)
trackio logbook page "..."                              # add/select a page as the default target
trackio logbook cell markdown "..." --page "..."        # log a finding onto a page (creates it if new)
trackio logbook cell code --page "..." --code train.py --output "..."
trackio logbook run --page "..." -- python train.py --lr 3e-4  # run + capture command, scripts, output
trackio logbook read pages                              # list pages
trackio logbook read page "..."                         # read only cell ids + titles for a page
trackio logbook read cell cell_<id>                     # read one full cell
trackio logbook serve                                   # preview locally
trackio logbook publish [username/space]                # first publish (public gate) → enables auto-sync
trackio logbook sync                                    # push later edits to the Space now
```

`cell markdown` **appends** a markdown cell — you never clobber findings someone else wrote. Use `cell code` when the entry has code plus output. Every cell has a stable id and title; pass `--title` when you know the best label, otherwise Trackio derives one. Models, datasets, Spaces, jobs, buckets, and images are detected from URLs in the markdown/output and rendered richly by the viewer. Trackio-tagged Spaces render as Trackio dashboards. Everything else is a direct file edit.

`run` is the preferred way to execute experiments from the terminal: it tees output live, stores the exact command, attaches any script/config argv tokens it can see, records exit code and duration, and captures truncated output in one code cell.

## The structure

- **The main page** (`pages/index.md`) is the **table of contents only** — an `## Experiments` table of `| Status | Experiment |`, one row per experiment, each linking to that experiment's page. **Never write findings here.**
- **Each experiment has its own page** where findings accumulate.

## Add pages as they become relevant

When you know the next page, add it directly:

```bash
trackio logbook page "Run baselines"
```

This creates a `planned` row in the table of contents, creates the page if needed, and makes it the default target for later `cell` and `run` commands. Add pages one at a time as the campaign takes shape; the reader still sees the same clean table of contents without requiring an upfront planning step.

Edit the table directly if you want to change status labels or add extra columns.

## Log onto an experiment

```bash
trackio logbook cell markdown "Zero-shot baseline: 41% valid; need SFT." --page "Baseline"
trackio logbook cell markdown "3e-4 wins; 1e-3 diverges ~300 steps." --page "LR sweep" --link ...
```

`--page "Name"` **creates the page + adds its row to the index** the first time, and appends to it thereafter. This keeps the main page a clean TOC automatically.

After a page has been updated once, `cell` and `run` can omit `--page`; they append to the most recently updated page.

## Read efficiently as an agent

Start with outlines, not full page bodies:

```bash
trackio logbook read pages --json
trackio logbook read page "Baseline" --json
trackio logbook read cell cell_ab12cd34ef56 --json
```

`read page` returns only page metadata plus cell ids, types, titles, and timestamps. Use `read cell` for the full Markdown/code/output only when the cell title is relevant to your task. The generated `logbook.md` is also compact: it indexes pages and cells rather than expanding every cell body.

## Also editable directly (your normal file tools)

Any page's content, the index table, and the styling (`logbook.css` / `index.html` / `logbook.js`, which live inside the logbook) are plain files — edit them when the CLI verbs aren't enough. `serve` to preview and fix.

- `--title`: an optional short title for the cell; if omitted, Trackio derives one.
- Body: normal Markdown. Use paragraphs, bullets, headings, and tables as appropriate for the material.
- `--link URL`: each unfurls into a rich card. Pass each as a **separate `--link` flag**, never inside the body text. Supported: HF models / datasets / **Spaces & Trackio dashboards (embedded live)** / **Jobs** (`huggingface.co/jobs/...`) / **Buckets** (`huggingface.co/buckets/...`), arXiv, GitHub, and image URLs.
- `--code PATH`: attach the exact script/config you ran (repeatable). It renders as a collapsible, syntax-highlighted accordion — the key to reproducibility. Attach the training script, eval harness, config, etc.
- `--artifact project/name:vN`: reference a tracked Trackio artifact.
- It's just Markdown you can also edit by hand — if something renders wrong, `serve` to preview and fix the file directly.

## Prefer typed cells when the shape is clear

```bash
trackio logbook cell code --page "Eval" --title "Eval output" --code eval.py --output "exact_match: 0.41"
trackio logbook cell code --page "Samples" --code generate.py --output "Generated grid: https://huggingface.co/buckets/user/run/grid.png" --attachment "sample_grid|image|https://huggingface.co/buckets/user/run/grid.png|https://huggingface.co/buckets/user/run/grid.json|Raw prompts, seeds, outputs, and scores"
trackio logbook run --page "Eval" -- python eval.py --checkpoint ckpt.safetensors
```

Typed cells still live in the same Markdown files. Keep the persisted cell types simple: markdown and code. If an image or plot has raw data, add it as a hidden `--attachment` so humans see the clean output while agents can read the raw data URL from `logbook.md`.

## Make it reproducible

For each experiment, capture enough that someone could re-run it:

- The **exact code**: `--code train.py --code configs/sft.yaml`.
- **Where it ran**: link the HF **Job** URL (`--link https://huggingface.co/jobs/<owner>/<id>`) so a reader can open its logs/status.
- **What it produced**: dump generated images/plots and their **raw data** to an HF **Bucket**, and link both — the image (unfurls as a preview) and the underlying data file (so results can be re-plotted or checked), plus the Trackio dashboard for live metrics.

## Automatic capture from trackio

If a logbook exists in the working directory, trackio **auto-captures itself** — no manual cell needed for these:

- `trackio.finish()` records the run + its dashboard under an experiment named after the trackio **project** (one cell per run; re-runs update in place).
- `trackio.log_artifact(...)` records the artifact.

Local runs/artifacts are marked as local until you publish (see below). Set `TRACKIO_LOGBOOK_AUTONOTE=0` to disable (e.g. during large sweeps).

## Publishing & privacy

- **Local until the first `publish`** — nothing leaves the machine, so drafts are safe. Scan for secrets/paths before that first publish; static Spaces are **public**.
- After the first `publish`, `cell`/`run`/`page` auto-sync in the background. After a **direct file edit**, run `trackio logbook sync` to push it.
- The remote Space is remembered in `./.trackio/metadata.json`, so `publish`/`sync` need no argument after the first time.
- **Publishing promotes local resources**: `publish` deploys any local trackio dashboards it captured as Spaces under the logbook's namespace and pushes local artifacts to a Bucket, then rewrites the links. Add `--private` to make the logbook, dashboards, and bucket all private (for team/internal logbooks); default is public.
