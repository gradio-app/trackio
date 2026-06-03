# Trackio Reports

Trackio Reports are static, agent-friendly experiment reports that can be
published to Hugging Face Spaces. They are useful when you want a narrative layer
around runs: Markdown notes, images, generated files, model artifacts, and
embedded Trackio dashboards.

The first version is read-only in the browser. Agents and humans publish from a
local checkout with the Trackio CLI.

## Initialize a report

```sh
trackio report init \
  --space-id username/my-report \
  --bucket-id username/my-report-bucket
```

This creates:

```text
REPORTS.md
.trackio/config.toml
.trackio/reports.schema.json
reports/index.md
```

`REPORTS.md` is the canonical instruction file for agents. A fresh coding agent
can read it, learn the report layout, and use the CLI commands below without
needing prior context.

## Publish an experiment entry

```sh
trackio report publish \
  --page reports/experiments/lora.md \
  --title "Run 003" \
  --body notes.md \
  --artifact outputs/confusion_matrix.png \
  --artifact outputs/checkpoint/
```

Artifacts are uploaded to the configured HF Bucket, and Markdown shortcodes are
appended to the selected page.

## Report pages

Reports are Markdown files in the `reports/` directory. Folder structure defines
nesting. The deployed report renders `index.md` as the main article page, while
nested Markdown files become separate static pages. Linked page cards navigate
between pages, and nested pages include breadcrumbs back to the main report.

```text
reports/
  index.md
  experiments/
    index.md
    data-mixtures.md
  followups/
    next-runs.md
```

Each page may include frontmatter:

```md
---
title: Data mixture experiments
---
```

## Embeds

Use shortcodes for artifacts and dashboards:

```md
{{ artifact path="reports/artifacts/run/chart.png" data="reports/artifacts/run/chart.json" caption="Evaluation chart" }}
{{ file path="reports/artifacts/run/model.safetensors" caption="Model weights" }}
{{ trackio url="https://username-space.static.hf.space/?project=my-project&sidebar=hidden" }}
```

Static report Spaces are public, so embedded dashboards and artifact URLs must be
publicly readable.

Trackio embeds are designed to be parseable by agents. The generated HTML
includes `data-trackio-url`, `data-trackio-project`, and `data-trackio-metrics`
attributes, and `dist/report.json` includes each dashboard URL, project, metric
filters, and suggested `trackio` CLI commands.

Image artifacts can include a `data=` attribute that points to the raw results
behind the figure. The generated HTML keeps the image for human readers, while
`dist/report.json`, `dist/agent.md`, and `dist/llms.txt` expose the raw data URL
for agents.

The build also writes `dist/agent.md`, a compact report contract for coding
agents. Static report Spaces serve browser HTML at `/`; agents should fetch
`/agent.md`, `/llms.txt`, or `/report.json` directly. The HTML also advertises
`agent.md` with `<link rel="alternate" type="text/markdown">`.

## Build and deploy

```sh
trackio report validate
trackio report build
trackio report deploy
```

`trackio report build` writes a static site to `dist/`. `trackio report deploy`
creates or updates the configured static Space.
