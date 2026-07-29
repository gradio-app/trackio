# Logbooks

Trackio logbooks are shareable experiment notebooks for recording the reasoning,
commands, results, figures, artifacts (checkpoints, datasets, etc.), and agent traces behind an experiment.
A logbook is stored locally in the `.trackio/logbook` directory of a workspace
and can be previewed locally or published as a static Hugging Face Space.

**Recommended for coding agents**: The easiest way to use Logbooks with coding agents (e.g. Codex, Claude Code, Pi, OpenCode) is to just give your coding agent these instructions:

```txt
trackio skills add
trackio logbook open
trackio logbook attach trace <path to current trace>

Work in this workspace's Trackio logbook. Before running any experiment or
script, create or select the relevant page with `trackio logbook page "..."`. Run every experiment command with `trackio logbook run -- <command>` ratherthan invoking it directly, which will log the code and its outputs into the logbook. 
```

For more specifics and fine-grained control, keep reading!

## Start an agent session with a logbook

The easiest way to use a logbook is to create it before the agent starts making
changes or running experiments:

```sh
trackio logbook open --title "Learning-rate sweep"
```

This creates the local logbook and opens its preview. Use `--no-serve` when
you only want to create or attach to the local logbook. Use `--no-browser` to
start the preview without opening a browser, or pass `--port` to select a
different port.

### Give the agent the Trackio skill

Install the Trackio skill for the coding agent you are using. For Codex:

```sh
trackio skills add --codex
```

The command installs the skill in the project and links it for Codex. Start a
new Codex session after installation when necessary so it can load the skill.
For another supported agent, replace `--codex` with its flag, such as
`--claude`, `--cursor`, `--opencode`, or `--pi`.

The skill tells the agent to run code with `trackio logbook run -- ...` rather
than invoking an experiment command directly. That wrapper records the exact
command, detected scripts and configuration files, output, exit code, duration,
and supported output artifacts. For example:

```sh
trackio logbook page "Baseline"
trackio logbook run -- python train.py --learning-rate 0.001
```

The training script should still use `trackio.init()`, `trackio.log()`, and
`trackio.finish()` normally. With a logbook in the workspace, `trackio.init()`
can also add a live dashboard cell for the active Trackio project.

### Attach the active session trace

Attach the current coding-agent transcript near the beginning of the session:

```sh
trackio logbook attach trace /absolute/path/to/current-session.jsonl --title "Agent session"
```

The agent runtime determines where its transcript is stored. Find the JSON or
JSONL file for the active conversation using that runtime's session directory,
then attach the file whose timestamps and metadata match the session. An active
JSONL file can be attached before the session ends; Trackio refreshes it while
the local preview is open. Attaching also establishes the Workspace baseline,
so later supported model and data files can be associated with the session.

Trackio scrubs common secrets from an attached trace by default. Review traces
before publishing because they can still contain prompts, tool inputs, command
output, paths, or personal data. Use `--no-scrub` only for an already-sanitized
source.

### Create pages as the work develops

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

## Publish a logbook

Publish the current logbook to a Hugging Face Space:

```sh
trackio logbook publish username/learning-rate-logbook
```

Published logbooks are static and read-only. The Space stores references to
trace datasets and artifact buckets by default; use `--public` only when those referenced resources should also be public. Use `--private` to make the Space private.

