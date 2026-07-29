# Logbooks

Trackio logbooks are shareable experiment notebooks for recording the reasoning,
commands, results, figures, artifacts, and agent traces behind an experiment.
A logbook is stored locally in the `.trackio/logbook` directory of a workspace
and can be previewed locally or published as a static Hugging Face Space.

## Create and preview a logbook

From an experiment workspace, create a logbook and open its local preview:

```sh
trackio logbook open --title "Learning-rate sweep"
```

Use `--no-serve` when you only want to create or attach to the local logbook.
Use `--no-browser` to start the preview without opening a browser, or pass
`--port` to select a different port.

Opening a workspace that already contains a logbook attaches to it. The
logbook is made up of pages; create or select a page with:

```sh
trackio logbook page "Baseline"
```

## Add experiment content

Add Markdown, code, figures, artifacts, or an embedded Trackio dashboard:

```sh
trackio logbook cell markdown "Baseline accuracy: 82.4%" --page "Baseline"
trackio logbook cell code --page "Baseline" --code-text "print(metrics)" --language python
trackio logbook cell figure --page "Baseline" --image plots/baseline.png
trackio logbook cell artifact "my-project/model:v1" --page "Baseline" --type model
trackio logbook cell dashboard my-project --page "Baseline"
```

To run an experiment command and capture its command, output, scripts, and
output files in one step:

```sh
trackio logbook run --page "Sweep" -- python train.py --learning-rate 0.001
```

Output model and data files are recorded as artifact cells by default. Pass
`--no-artifacts` to disable that capture.

## Read a logbook programmatically

`trackio logbook read` produces a compact, agent-friendly view. It can read a
local workspace, a published Space ID, or a logbook URL:

```sh
trackio logbook read
trackio logbook read pages
trackio logbook read page "Baseline"
trackio logbook read --json
```

Use `trackio logbook read cell <cell-id> --full` when a cell needs to be
inspected in full. The JSON form is useful for automation and coding agents.

Agent session traces can be attached explicitly:

```sh
trackio logbook attach trace session.jsonl --title "Agent run"
```

By default, secrets are scrubbed from attached traces. Use `--no-scrub` only
when the source is known to contain no sensitive data.

## Publish a logbook

Publish the current logbook to a Hugging Face Space:

```sh
trackio logbook publish username/learning-rate-logbook
```

Published logbooks are static and read-only. The Space stores references to
trace datasets and artifact buckets by default; use `--public` only when those
referenced resources should also be public. Use `--private` to make the Space
private.

## Keep a logbook current

Regenerate the derived site files after editing page sources directly:

```sh
trackio logbook sync
```

Use `trackio logbook pin <cell-id>` to surface an important cell on the
logbook introduction, and `trackio logbook remove trace <session-id>` or
`trackio logbook cell remove <cell-id>` to remove attached content.

The Python API exposes the same building blocks through `trackio.logbook`,
including `create_logbook`, `ensure_page`, `add_markdown_cell`,
`add_code_cell`, `add_figure_cell`, `add_artifact_cell`, `attach_trace`, and
`publish`.
