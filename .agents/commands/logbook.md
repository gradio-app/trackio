---
description: Start, add to, or publish a Trackio experiment logbook
argument-hint: "  |  --cell \"...\"  |  --publish [username/space]"
---

You were invoked as `/logbook $ARGUMENTS`. Interpret the arguments and act:

- **No arguments** → `trackio logbook open` and follow the **trackio logbook** skill for the rest of the session.
- **`--publish [username/space]`** → publish the current logbook with `trackio logbook publish [username/space]` (omit the id if one is already linked). Report the Space URL back.
- **`--cell <text>`** → the user is manually recording a finding that may have been missed. Run `trackio logbook cell markdown "<text>"`, adding `--page` / `--link` / `--code` if appropriate. Confirm what you logged and to which page.

In every case, keep following the **trackio logbook** skill: add pages to the table of contents as they become relevant, log findings onto pages (never the index), and keep the main page a clean table of contents.
