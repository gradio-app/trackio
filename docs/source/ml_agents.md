# Running ML Experiments with Agents

Trackio is designed from the ground up to support autonomous ML experimentation driven by LLM agents. This guide covers how to structure your training code, configure alerts, and wire up the feedback loop so that an agent can launch experiments, monitor them, react to problems, and iterate on hyperparameters — all without human intervention.

## Why Trackio for Agents?

Most experiment trackers assume a human is watching a dashboard. Trackio gives agents first-class programmatic access through multiple channels:

- **CLI with JSON output** — every `trackio` command supports `--json`, making it trivial to parse in any language
- **Python API** — `trackio.Api()` provides direct access to runs, metrics, and alerts
- **HTTP API / MCP** — the Trackio dashboard exposes Gradio API endpoints, and can run as an MCP server so LLMs can call tools directly
- **Alerts with webhooks** — agents can insert `trackio.alert()` calls like print statements and poll for them later
- **`since` filtering** — efficient polling for new alerts without re-reading the full history

## The Agent Feedback Loop

A typical autonomous experiment loop looks like this:

```
┌─────────────────────────────────────┐
│  1. Agent writes training script    │
│     with trackio.init(), log(),     │
│     and alert() calls               │
├─────────────────────────────────────┤
│  2. Agent launches the script       │
├─────────────────────────────────────┤
│  3. Agent polls for alerts and      │
│     metrics while training runs     │
├─────────────────────────────────────┤
│  4. Agent reads results, decides    │
│     next hyperparameters            │
├─────────────────────────────────────┤
│  5. Agent writes a new script       │
│     and repeats from step 1         │
└─────────────────────────────────────┘
```

The rest of this guide walks through each step with concrete code.

## Step 1: Structuring Training Code for Agents

The key insight is that an agent can insert `trackio.alert()` calls the same way it would insert `print()` statements for debugging. Alerts are more structured than print statements: they have a title, optional description, severity level, and are automatically persisted and queryable.

Here is a training script written the way an agent would write it, with alerts at every decision point:

```python
import trackio
import torch

trackio.init(
    project="cifar10-hparam-search",
    name="run-lr0.001-bs64",
    config={
        "learning_rate": 0.001,
        "batch_size": 64,
        "optimizer": "adamw",
        "epochs": 50,
        "weight_decay": 1e-4,
    },
)

model = build_model()
optimizer = torch.optim.AdamW(
    model.parameters(), lr=0.001, weight_decay=1e-4
)

best_val_loss = float("inf")
patience_counter = 0
patience_limit = 5

for epoch in range(50):
    train_loss = train_one_epoch(model, train_loader, optimizer)
    val_loss, val_acc = evaluate(model, val_loader)

    trackio.log({
        "train_loss": train_loss,
        "val_loss": val_loss,
        "val_accuracy": val_acc,
        "learning_rate": optimizer.param_groups[0]["lr"],
    })

    # Alert on loss divergence
    if train_loss > 10.0:
        trackio.alert(
            title="Training diverged",
            text=f"train_loss={train_loss:.4f} at epoch {epoch}. "
                 "Learning rate is likely too high.",
            level=trackio.AlertLevel.ERROR,
        )
        break

    # Alert when validation stops improving
    if val_loss < best_val_loss:
        best_val_loss = val_loss
        patience_counter = 0
        torch.save(model.state_dict(), "best_model.pt")
    else:
        patience_counter += 1
        if patience_counter >= patience_limit:
            trackio.alert(
                title="Early stopping triggered",
                text=f"No improvement for {patience_limit} epochs. "
                     f"Best val_loss={best_val_loss:.4f} at epoch "
                     f"{epoch - patience_limit}.",
                level=trackio.AlertLevel.WARN,
            )
            break

    # Alert on overfitting
    if epoch > 10 and (train_loss < 0.1 and val_loss > 1.5):
        trackio.alert(
            title="Overfitting detected",
            text=f"train_loss={train_loss:.4f} vs val_loss={val_loss:.4f}. "
                 "Consider adding regularization or reducing model capacity.",
            level=trackio.AlertLevel.WARN,
        )

    # Alert on good results
    if val_acc > 0.93:
        trackio.alert(
            title="High accuracy reached",
            text=f"val_accuracy={val_acc:.4f} at epoch {epoch}.",
            level=trackio.AlertLevel.INFO,
        )

trackio.alert(
    title="Training complete",
    text=f"Final val_loss={val_loss:.4f}, val_accuracy={val_acc:.4f}. "
         f"Best val_loss={best_val_loss:.4f}.",
    level=trackio.AlertLevel.INFO,
)
trackio.finish()
```

The alerts here are not just for humans — they are structured signals that the agent will read later to decide what to do next.

### Guidelines for Agent-Friendly Alerts

- **Use `ERROR` for conditions that should stop the run** (divergence, NaN loss, out of memory).
- **Use `WARN` for conditions that suggest the hyperparameters should change** (overfitting, early stopping, slow convergence).
- **Use `INFO` for milestones** (training complete, high accuracy reached, checkpoint saved).
- **Include numeric values in `text`** so the agent can parse them and reason about them.
- **Include actionable suggestions in `text`** (e.g., "Learning rate is likely too high") to help the agent decide what to change.

## Step 2: Launching the Script

The agent can launch the script in a subprocess or background process. In most agent frameworks, this is as simple as running a shell command:

```bash
python train.py
```

If the agent is using an MCP-connected LLM, it can also launch scripts through a shell tool.

## Step 3: Monitoring During Training

While training runs, the agent polls for alerts and metrics. The `--since` flag makes this efficient — only new alerts since the last check are returned.

### Polling via CLI

```bash
# First poll — get all alerts
trackio get alerts --project "cifar10-hparam-search" --run "run-lr0.001-bs64" --json

# Subsequent polls — only new alerts
trackio get alerts --project "cifar10-hparam-search" --since "2025-06-15T14:30:00" --json
```

### Polling via Python API

```python
import trackio
from datetime import datetime, timezone

api = trackio.Api()
last_check = None

while training_is_running():
    alerts = api.alerts(
        "cifar10-hparam-search",
        run="run-lr0.001-bs64",
        since=last_check,
    )
    if alerts:
        last_check = alerts[0]["timestamp"]  # alerts are sorted newest-first
        for a in alerts:
            print(f"[{a['level'].upper()}] {a['title']}: {a['text']}")

            if a["level"] == "error":
                # Stop the run and re-plan
                handle_error(a)

    time.sleep(30)
```

### Polling via MCP

If the Trackio dashboard is running as an MCP server, the agent can call the `get_alerts` tool directly through the MCP protocol. See [Trackio as an API and MCP Server](api_mcp_server.md) for setup instructions.

## Step 4: Reading Results and Deciding Next Steps

After a run finishes, the agent reads the full results:

```bash
# Get run summary (metrics, config, step count)
trackio get run --project "cifar10-hparam-search" --run "run-lr0.001-bs64" --json

# Get the loss curve
trackio get metric --project "cifar10-hparam-search" --run "run-lr0.001-bs64" --metric "val_loss" --json

# Get all alerts (the most useful signal for decision-making)
trackio get alerts --project "cifar10-hparam-search" --run "run-lr0.001-bs64" --json
```

The alerts provide a concise summary of what happened during training. Instead of parsing thousands of metric values, the agent can read a handful of alerts to understand:

- Did the run diverge? → Lower the learning rate
- Did it overfit? → Add regularization or reduce capacity
- Did it early-stop? → The hyperparameters are in the right ballpark but might need tuning
- Did it reach high accuracy? → This configuration is working well

## Step 5: Iterating on Hyperparameters

The agent uses the alerts from the previous run to choose new hyperparameters. Here is a concrete example of the decision logic an agent might follow:

```python
import json
import subprocess
import trackio

api = trackio.Api()

# Read alerts from the last run
alerts = api.alerts("cifar10-hparam-search", run="run-lr0.001-bs64")

# Read the config from the last run
runs = api.runs("cifar10-hparam-search")
last_run = [r for r in runs if r.name == "run-lr0.001-bs64"][0]
config = last_run.config

# Decision logic based on alerts
new_config = dict(config)
for alert in alerts:
    if "diverged" in alert["title"].lower():
        new_config["learning_rate"] = config["learning_rate"] * 0.1
    elif "overfitting" in alert["title"].lower():
        new_config["weight_decay"] = config.get("weight_decay", 1e-4) * 10
    elif "early stopping" in alert["title"].lower():
        new_config["learning_rate"] = config["learning_rate"] * 0.5
    elif "high accuracy" in alert["title"].lower():
        # This config is good — try fine-tuning
        new_config["learning_rate"] = config["learning_rate"] * 0.5
        new_config["epochs"] = config["epochs"] + 20
```

The agent then generates a new training script with the updated config and launches it, repeating the loop.

## Comparing Runs

After several iterations, the agent can compare all runs in the project:

```bash
# List all runs
trackio list runs --project "cifar10-hparam-search" --json

# Get a summary of each run
trackio get run --project "cifar10-hparam-search" --run "run-lr0.001-bs64" --json
trackio get run --project "cifar10-hparam-search" --run "run-lr0.0001-bs64" --json
```

Or in Python:

```python
api = trackio.Api()
runs = api.runs("cifar10-hparam-search")

for run in runs:
    alerts = run.alerts()
    errors = [a for a in alerts if a["level"] == "error"]
    warns = [a for a in alerts if a["level"] == "warn"]
    infos = [a for a in alerts if a["level"] == "info"]
    print(f"{run.name}: {len(errors)} errors, {len(warns)} warnings, {len(infos)} info")
```

## Sending Alerts to the Agent via Webhooks

If your agent framework has an HTTP endpoint or can receive messages from Slack/Discord, you can use webhooks to push alerts to the agent in real time instead of polling:

```python
trackio.init(
    project="cifar10-hparam-search",
    webhook_url="https://hooks.slack.com/services/T.../B.../xxx",
)
```

This way, alerts are delivered to a Slack channel the agent monitors, closing the loop without any polling. See the [Alerts guide](alerts.md) for detailed setup instructions for Slack and Discord.

## Full Example: Autonomous Hyperparameter Search

Here is a complete, self-contained example that ties everything together. This script runs a simple hyperparameter grid search with automated alert-based decisions:

```python
import trackio
import random
import time

def run_experiment(config):
    """Simulate a training run. Replace with real training code."""
    run = trackio.init(
        project="auto-hparam-search",
        config=config,
    )

    lr = config["learning_rate"]
    best_val_loss = float("inf")
    patience = 0

    for epoch in range(config["epochs"]):
        # Simulated metrics — replace with real training
        noise = random.gauss(0, lr * 10)
        train_loss = max(0.01, 1.0 / (epoch + 1) + noise)
        val_loss = train_loss + random.uniform(0, 0.3)
        val_acc = max(0, min(1, 1.0 - val_loss + random.uniform(-0.05, 0.05)))

        trackio.log({
            "train_loss": train_loss,
            "val_loss": val_loss,
            "val_accuracy": val_acc,
        })

        if train_loss > 5.0:
            trackio.alert(
                title="Training diverged",
                text=f"train_loss={train_loss:.4f}, lr={lr}",
                level=trackio.AlertLevel.ERROR,
            )
            break

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience = 0
        else:
            patience += 1
            if patience >= 5:
                trackio.alert(
                    title="Early stopping",
                    text=f"Best val_loss={best_val_loss:.4f}",
                    level=trackio.AlertLevel.WARN,
                )
                break

        time.sleep(0.05)

    trackio.alert(
        title="Run complete",
        text=f"Final val_loss={val_loss:.4f}, val_acc={val_acc:.4f}, "
             f"best_val_loss={best_val_loss:.4f}",
        level=trackio.AlertLevel.INFO,
    )
    trackio.finish()
    return run.name


def analyze_and_decide(api, project, run_name, config):
    """Read alerts from a run and suggest new hyperparameters."""
    alerts = api.alerts(project, run=run_name)

    new_config = dict(config)
    for alert in alerts:
        title = alert["title"].lower()
        if "diverged" in title:
            new_config["learning_rate"] *= 0.1
        elif "early stopping" in title:
            new_config["learning_rate"] *= 0.5
        elif "run complete" in title and "val_acc" in (alert.get("text") or ""):
            # Slight refinement
            new_config["learning_rate"] *= 0.8
            new_config["epochs"] += 10

    return new_config


api = trackio.Api()
project = "auto-hparam-search"

config = {
    "learning_rate": 0.01,
    "batch_size": 64,
    "epochs": 30,
}

for iteration in range(5):
    print(f"\n--- Iteration {iteration + 1} ---")
    print(f"Config: {config}")

    run_name = run_experiment(config)
    config = analyze_and_decide(api, project, run_name, config)
```

This example is self-contained and uses simulated metrics. Replace the `run_experiment` function body with your real training code and the pattern stays the same.

## Using Alerts with Transformers and TRL

When using `report_to="trackio"` with the Hugging Face `Trainer`, the built-in `TrackioCallback` handles `trackio.init()`, `trackio.log()`, and `trackio.finish()` automatically. Since `trackio.init()` is called before training begins, the current run is set and `trackio.alert()` works from any other callback in the same process.

To add alerts, write a small `TrainerCallback` and pass it to the Trainer via `callbacks=`:

### Transformers

```python
import trackio
from transformers import Trainer, TrainerCallback, TrainingArguments

class AlertCallback(TrainerCallback):
    def on_log(self, args, state, control, logs=None, **kwargs):
        if "trackio" not in args.report_to or logs is None:
            return
        loss = logs.get("loss")
        if loss is not None and loss > 5.0:
            trackio.alert(
                title="Training loss spike",
                text=f"loss={loss:.4f} at step {state.global_step}. "
                     "Consider lowering the learning rate.",
                level=trackio.AlertLevel.ERROR,
            )

    def on_evaluate(self, args, state, control, metrics=None, **kwargs):
        if "trackio" not in args.report_to or metrics is None:
            return
        eval_loss = metrics.get("eval_loss")
        if eval_loss is not None and eval_loss > 2.0:
            trackio.alert(
                title="High eval loss",
                text=f"eval_loss={eval_loss:.4f} at step {state.global_step}.",
                level=trackio.AlertLevel.WARN,
            )

trainer = Trainer(
    model=model,
    args=TrainingArguments(
        report_to="trackio",
        project="my-project",
        output_dir="./output",
        num_train_epochs=3,
        eval_strategy="steps",
        eval_steps=100,
    ),
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
    callbacks=[AlertCallback()],
)
trainer.train()
```

An agent generating this code only needs to define the `AlertCallback` class with the right conditions, then add it to the `callbacks` list. The pattern is the same regardless of the model or dataset.

### TRL

The same approach works with TRL trainers like `GRPOTrainer` or `SFTTrainer`. Here's an example for reinforcement learning with alerts on reward collapse and KL divergence:

```python
import trackio
from transformers import TrainerCallback

class RLAlertCallback(TrainerCallback):
    def on_log(self, args, state, control, logs=None, **kwargs):
        if "trackio" not in args.report_to or logs is None:
            return

        reward = logs.get("train/reward")
        if reward is not None and reward < -1.0:
            trackio.alert(
                title="Reward collapse",
                text=f"reward={reward:.4f} at step {state.global_step}. "
                     "Consider lowering the learning rate or checking the "
                     "reward model.",
                level=trackio.AlertLevel.ERROR,
            )

        kl = logs.get("train/kl")
        if kl is not None and kl > 10.0:
            trackio.alert(
                title="KL divergence too high",
                text=f"kl={kl:.4f} at step {state.global_step}. "
                     "The policy is drifting too far from the reference model.",
                level=trackio.AlertLevel.WARN,
            )

        completion_length = logs.get("train/completion_length")
        if completion_length is not None and completion_length < 5.0:
            trackio.alert(
                title="Completions too short",
                text=f"Mean completion length={completion_length:.1f} tokens. "
                     "The model may be collapsing to short outputs.",
                level=trackio.AlertLevel.WARN,
            )
```

Then pass it to any TRL trainer:

```python
from trl import GRPOTrainer, GRPOConfig

trainer = GRPOTrainer(
    model=model,
    config=GRPOConfig(
        report_to="trackio",
        project="rl-experiment",
        output_dir="./output",
    ),
    train_dataset=dataset,
    callbacks=[RLAlertCallback()],
)
trainer.train()
```

### Tips for Agents Writing Alert Callbacks

- **Keep conditions simple.** Each `if` block should check one metric against one threshold. This makes it easy for an agent to add, remove, or adjust conditions between runs.
- **Include the metric value and step in `text`.** This gives the agent concrete numbers to reason about when deciding the next hyperparameters.
- **Include actionable suggestions.** Text like "Consider lowering the learning rate" helps the agent decide what to change next.
- **Use `on_evaluate` for eval metrics.** Eval metrics are only available in `on_evaluate`, not in `on_log`. Training metrics like `loss` appear in `on_log`.

## Best Practices Summary

1. **Use alerts as structured signals, not just notifications.** Include numeric values and actionable suggestions in `text` so the agent can parse them and act on them.

2. **Use severity levels consistently.** `ERROR` = stop and change approach. `WARN` = tweak parameters. `INFO` = milestone reached.

3. **Poll with `since` for efficiency.** Save the timestamp of the last alert you processed and pass it as `since` on the next poll to avoid re-reading old alerts.

4. **Keep all runs in the same project.** This lets the agent compare runs side-by-side and see the full history of what was tried.

5. **Log config with every run.** Always pass `config=` to `trackio.init()` so the agent can read back which hyperparameters produced which results.

6. **Use the CLI with `--json` for agent scripts.** JSON output is reliable to parse and won't break if the human-readable format changes.

7. **Consider MCP for tight integration.** If your agent framework supports MCP, running `trackio show --mcp-server` lets the agent call Trackio tools directly without spawning subprocesses.
