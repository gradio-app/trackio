---
"trackio": minor
---

feat: Mount the local Trackio dashboard as a subpath of `logbook serve` (no more separate port/discovery hop), push auto-captured artifacts to an HF Bucket on publish (preserving their relative path, reusing the same bucket across publishes), add a `hide_empty_tabs` dashboard query param, remove logbook page nesting, and polish the logbook viewer (smaller body/heading text, muted section marks in the sidebar, tighter spacing).
