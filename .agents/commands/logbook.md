---
description: Start, add to, or publish a Trackio experiment logbook
argument-hint: "[username/space]  |  --note \"...\"  |  --publish [username/space]"
---

You were invoked as `/logbook $ARGUMENTS`. Interpret the arguments and act:

- **No arguments** → start/attach the logbook for this directory: run `trackio logbook open` (infer a concise `--title` from the project only if creating a new one). Then follow the **trackio logbook** skill for the rest of the session.
- **A bare `username/space`** → `trackio logbook open username/space` (clones the existing logbook from that Space if there is one, otherwise creates a new one targeting it).
- **`--publish [username/space]`** → publish the current logbook with `trackio logbook publish [username/space]` (omit the id if one is already linked). Report the Space URL back.
- **`--note <text>`** → the user is manually recording a finding that may have been missed. Run `trackio logbook note "<text>" --experiment "<the most relevant experiment>"`, choosing or creating the right experiment, and adding `--status` / `--link` / `--code` if appropriate. Confirm what you logged and to which experiment.

In every case, keep following the **trackio logbook** skill: seed the plan into the table of contents, log findings onto experiments (never the index), and keep the main page a clean table of contents.
