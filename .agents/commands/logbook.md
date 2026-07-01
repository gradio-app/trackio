---
description: Start (or attach to) a Trackio experiment logbook for this session
argument-hint: "[username/space] [--title \"...\"]"
---

Start a Trackio logbook so this experiment session is captured as a shareable, Hub-native lab notebook.

Run:

`trackio logbook open $ARGUMENTS`

Then:

- Confirm the active logbook back to the user (title + slug, and the target Space if one was given).
- For the rest of the session, follow the **trackio logbook** skill: append a `trackio logbook note "..."` whenever an experiment concludes, a decision is made, or a result/surprise lands — linking models, datasets, dashboards, and artifacts with `--link` / `--artifact`. Keep a high signal bar; do not log routine steps.
- Organize longer campaigns into subpages with `trackio logbook page "..."`.
- Preview anytime with `trackio logbook serve`. When the user is done, `trackio logbook publish <username/space>` deploys it to a static Space (nothing is published until then).
