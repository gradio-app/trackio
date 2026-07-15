---
"trackio": patch
---

feat: let `logbook cell figure` embed image files directly

`trackio logbook cell figure` now accepts an image path via a new `--image`
flag, and `--html <file>` transparently embeds the file when it points at an
image. Previously the only way to add a PNG/JPG figure was to hand-encode it
into an `<img>` data-URI, and passing an image path to `--html` crashed with a
`UnicodeDecodeError` (the binary file was read as UTF-8 text). Images are
embedded as responsive base64 data URIs. The Python API `add_figure_cell` gains
a matching `image=` parameter.
