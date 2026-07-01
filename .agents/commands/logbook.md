---
description: Start a Trackio experiment logbook for this session
argument-hint: "[username/space]"
---

Start a Trackio logbook — a shareable, Hub-native lab notebook for this session. The one optional argument is the HF Space to publish to.

Run (infer a short, descriptive `--title` from the project/session):

`trackio logbook open $ARGUMENTS --title "<title>"`

Then:

- If the user passed a Space id, run `trackio logbook publish` once so it goes live. After that first publish, every `note` / `task` / `page` auto-syncs to the Space in the background — no more manual publishing.
- Confirm back to the user: the title, the local `./.trackio/logbook/` path, and the Space URL if publishing.
- For the rest of the session, follow the **trackio logbook** skill: add experiments as pages (`trackio logbook page "..."`) linked from the `index.md` Experiments table, and append findings with `trackio logbook note "..."` when an experiment concludes, a decision is made, or a result/surprise lands — linking models, datasets, dashboards, and artifacts with `--link` / `--artifact`. Keep a high signal bar.
- The logbook is just files under `./.trackio/logbook/` — edit `index.md` and the styling directly as needed. Preview with `trackio logbook serve`; after a direct edit, `trackio logbook sync` pushes it.
