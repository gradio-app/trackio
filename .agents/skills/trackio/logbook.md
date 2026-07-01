# Trackio Logbooks — sharing open experiments

A **logbook** is a shareable, Hub-native lab notebook for an experiment campaign, stored in `./.trackio/logbook/` (found by walking up from the cwd, like `.git`). It publishes to a static Hugging Face Space that renders a rich human view — a main page listing experiments, nested experiment pages, and unfurled links (models, datasets, dashboards, artifacts) — while a flattened `logbook.md` stays token-efficient for other agents.

The logbook is **just files you edit directly**. There are only a few CLI commands; everything else is a normal file edit.

## The few CLI commands

```bash
trackio logbook open [username/space] --title "..."   # scaffold ./.trackio/logbook/ (run once)
trackio logbook page "<Title>" [--parent SLUG]        # safe-create a page → prints its slug
trackio logbook note "<finding>" [--page SLUG] ...    # safe-append a finding to a page
trackio logbook serve                                 # preview locally
trackio logbook publish [username/space]              # first publish (public gate) → enables auto-sync
trackio logbook sync                                  # push later edits to the Space now
```

`page` and `note` **only append / create** — use them so you never clobber notes someone else wrote. Everything else is a direct edit.

## Edit these directly (your normal file tools)

- **The main page** `./.trackio/logbook/pages/index.md` — an `## Experiments` Markdown table (`| Status | Experiment |`). Add / reorder / restyle rows freely. Status renders as a badge: `planned`, `in-progress`, `done`, `blocked`.
- **Any page's content** — write prose, embed results, link things.
- **Styling / layout** — `./.trackio/logbook/logbook.css` (and `index.html`, `logbook.js`) live in the logbook and are yours to tweak per-logbook.

## Adding an experiment

1. `trackio logbook page "LR sweep"` → prints a slug, e.g. `lr-sweep`.
2. Add a row to `index.md`'s Experiments table: `| in-progress | [LR sweep](#/lr-sweep) |`. Clicking the row opens that page.
3. Log findings onto it: `trackio logbook note "3e-4 wins; 1e-3 diverges" --page lr-sweep --link ...`.

For a **sub-experiment**, create it with `--parent lr-sweep` and link `[its title](#/slug)` inline in the parent page's prose where it's relevant — don't bunch links at the bottom.

## When to `note` (high bar — signal, not noise)

An experiment **concluded** with a result; a **decision** + rationale; a **surprise / dead end**; a **baseline** worth anchoring to. Not routine commands or scratch.

- `--title`: a short, result-bearing headline ("96.4% valid — target met").
- Body: 1–3 sentences with the number and what it means.
- `--link URL`: models/datasets/Spaces/dashboards/arXiv/GitHub/images — each unfurls into a card. One per `--link`.
- `--artifact project/name:vN`: reference a tracked Trackio artifact.

## Publishing & privacy

- **Local until the first `publish`** — nothing leaves the machine, so drafts are safe. Scan for secrets/paths before that first publish; static Spaces are **public**.
- After the first `publish`, `note`/`page` auto-sync in the background. After a **direct file edit**, run `trackio logbook sync` to push it.
- The remote Space is remembered in `./.trackio/metadata.json`, so `publish`/`sync` need no argument after the first time.
