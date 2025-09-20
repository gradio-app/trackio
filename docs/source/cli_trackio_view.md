# CLI trackio-view

The `trackio-view` command provides a lightweight, terminal-based dashboard for monitoring TrackIO experiments in real-time. This is perfect for monitoring training progress on remote servers or in terminal-only environments where you don't have access to a web browser.

![TrackIO View Demo](../../trackio/assets/trackio-view-demo-01.png)

## Rationale

While the web-based TrackIO dashboard (`trackio show`) provides a rich, interactive experience, there are many scenarios where a terminal-based viewer is more practical:

- **Remote server monitoring**: When training on remote GPU clusters or cloud instances, opening web browsers and port forwarding can be cumbersome
- **Lightweight monitoring**: Terminal UIs consume minimal resources compared to web dashboards
- **SSH-friendly**: Works seamlessly over SSH connections without requiring X11 forwarding or port tunneling
- **Always accessible**: No need to wait for a web server to start or worry about port conflicts
- **Scriptable**: Can be easily integrated into tmux/screen sessions or monitoring scripts

The design is inspired by the [gputop project](https://github.com/mcgrof/gputop), bringing elegant terminal-based monitoring to ML experiment tracking.

## Installation

The `trackio-view` command is included when you install TrackIO:

```bash
pip install trackio
```

For the best experience, also install the optional rich library for enhanced terminal graphics:

```bash
pip install rich
```

## Basic Usage

### Monitor all projects

```bash
trackio-view
```

This will automatically detect and display metrics from all TrackIO projects in your default data location (`~/.cache/huggingface/trackio/`).

### Monitor a specific project

```bash
trackio-view --project my-experiment
```

### Display metrics once (no live updates)

```bash
trackio-view --once
```

### Start with a specific zoom level

```bash
# Start showing only the last 200 iterations
trackio-view --zoom 2

# Display once with zoom to last 100 iterations
trackio-view --once --zoom 3
```

### Adjust update interval

```bash
trackio-view --interval 5  # Update every 5 seconds
```

## Features

### Real-time Metrics Display

The dashboard shows:
- Current step/iteration
- Loss values with color-coding (green for low, yellow for medium, red for high)
- Accuracy metrics (if logged)
- Learning rate
- Custom metrics from your training loop

### ASCII Graphs

Visual representation of metrics over time using ASCII art:
- Loss trend graphs with gradient coloring
- Auto-scaling to fit your data range
- Smooth interpolation between data points

### Color-Coded Feedback

Metrics are color-coded for quick visual feedback:
- **Green**: Good performance (low loss, high accuracy)
- **Yellow**: Medium performance
- **Red**: Poor performance or potential issues
- **Blue/Purple**: Learning rate indicators

### Terminal-Responsive Layout

The dashboard automatically adjusts to your terminal size, ensuring optimal display whether you're using a small SSH window or a full-screen terminal.

### Interactive Zoom Controls

The viewer supports interactive zooming to focus on different portions of your training history:

- **Press `+`** to zoom in (shows more recent iterations)
- **Press `-`** to zoom out (shows more training history)
- **Press `q`** to quit

By default, the graph displays your entire training history. You can progressively zoom in to focus on recent iterations:

#### Default View - All Training Data
![TrackIO View Demo](../../trackio/assets/trackio-view-demo-01.png)

#### Zoomed Once - Last 500 Iterations
Press `+` once to zoom in to the last 500 iterations:

![TrackIO View Zoom Level 1](../../trackio/assets/trackio-view-zoom.png)

#### Zoomed Twice - Last 200 Iterations
Press `+` again to zoom in further to the last 200 iterations:

![TrackIO View Zoom Level 2](../../trackio/assets/trackio-view-zoom-x2.png)

The zoom levels cycle through:
1. **All data** (default) - Complete training history
2. **Last 500** iterations
3. **Last 200** iterations
4. **Last 100** iterations
5. **Last 50** iterations

The current zoom level is displayed below the graph. This feature is particularly useful for:
- Getting an overview of the entire training progression
- Examining recent training dynamics in detail
- Identifying patterns or anomalies at different scales
- Monitoring convergence behavior

## Example Workflow

### During Training

Start your training script with TrackIO logging:

```python
import trackio

trackio.init(project="my-model-training")

for epoch in range(num_epochs):
    for batch in dataloader:
        loss = train_step(batch)
        trackio.log({"loss": loss, "epoch": epoch})

trackio.finish()
```

In another terminal (or tmux pane), monitor the training:

```bash
trackio-view --project my-model-training
```

### Quick Status Check

Use `--once` to get a quick snapshot of your training metrics without entering live monitoring mode:

```console
$ trackio-view --once
============================================================
TrackIO Dashboard - Project: tracking-e97b5
View: All data
============================================================

Latest Iteration: 9990
Latest Loss: 3.7359
Loss Change: -7.0930 (from 10.8289)
Min Loss: 3.7003
Max Loss: 10.8289
Learning Rate: 6.00e-05
Sparsity: 0.5%

Loss Trend (Iterations 10 to 9990):
  10.83 |*
  10.04 |
   9.24 |
   8.45 |
   7.66 |
   6.87 | **
   6.08 |   ********
   5.28 |           ****
   4.49 |               ***********************************
   3.70 |
        +--------------------------------------------------
```

### Zoomed View for Recent Iterations

Focus on the last 50 iterations to see fine-grained training dynamics:

```console
$ trackio-view --once --zoom 4
============================================================
TrackIO Dashboard - Project: tracking-e97b5
View: Last 50
============================================================

Latest Iteration: 9990
Latest Loss: 3.7359
Loss Change: +0.0157 (from 3.7202)
Min Loss: 3.7003
Max Loss: 3.7484
Learning Rate: 6.00e-05
Sparsity: 0.5%

Loss Trend (Iterations 9500 to 9990):
   3.75 |     * *  *                                 *
   3.74 | *                     *     *       *        **
   3.74 |         * *                  *  *      *        *
   3.73 |   *  *     *  * *      *      *   *     *      *
   3.73 |  *     *    **   * *       *     * *     *
   3.72 |*   *           *  * **  * *    *      *   *
   3.72 |                                             *
   3.71 |                                      *
   3.71 |
   3.70 |                          *
        +--------------------------------------------------
```

Notice how the zoomed view shows:
- More granular loss changes (+0.0157 vs -7.0930)
- Tighter Y-axis range (3.70-3.75 vs 3.70-10.83)
- Specific iteration range (9500-9990 vs 10-9990)

### Remote Monitoring

When training on a remote server:

```bash
# SSH into your server
ssh user@gpu-server

# Quick check of training progress
trackio-view --once

# Or monitor live with initial zoom to recent data
trackio-view --zoom 2

# In a screen/tmux session for persistent monitoring
screen -S monitor
trackio-view --project my-training

# You can now disconnect and reconnect to check progress anytime
```

## Command Line Options

```
trackio-view [OPTIONS]

Options:
  -p, --project TEXT     Project name to monitor (shows all if not specified)
  -i, --interval INT     Update interval in seconds (default: 2)
  --once                 Display once and exit (no live monitoring)
  -z, --zoom {0,1,2,3,4} Initial zoom level (default: 0)
                         0 = All data
                         1 = Last 500 iterations
                         2 = Last 200 iterations
                         3 = Last 100 iterations
                         4 = Last 50 iterations
  -h, --help            Show this help message and exit
```

## Tips and Tricks

1. **Use with tmux/screen**: The terminal UI works great in persistent terminal sessions
2. **Pipe to file**: Use `--once` to capture snapshots: `trackio-view --once > metrics.txt`
3. **Multiple projects**: Leave out `--project` to cycle through all active experiments
4. **Color terminals**: For best results, use a terminal that supports 256 colors or true color

## Troubleshooting

### No data found

If you see "No TrackIO data found", ensure:
- You have run training with TrackIO logging enabled
- The data is stored in the expected location (`~/.cache/huggingface/trackio/`)
- You're specifying the correct project name

### Colors not displaying

Some terminals may not support colors. Try:
- Using a modern terminal emulator (iTerm2, Windows Terminal, etc.)
- Setting `TERM=xterm-256color` in your environment
- Installing the `rich` library for better compatibility

### Performance issues

If the dashboard is slow:
- Increase the update interval with `--interval 10`
- Use `--once` for single snapshots instead of live monitoring
- Check if your TrackIO database has grown very large

## Using --once for Scripts and Automation

The `--once` flag outputs clean text without terminal control codes, perfect for scripting:

### Logging Training Progress

```bash
# Append current metrics to a log file
trackio-view --once >> training_progress.log

# Check metrics every hour and save to timestamped files
while true; do
  trackio-view --once > "metrics_$(date +%Y%m%d_%H%M%S).txt"
  sleep 3600
done
```

### Extract Specific Metrics

```bash
# Get just the current loss value
trackio-view --once | grep "Latest Loss:" | awk '{print $3}'

# Check if training has converged (loss change small)
change=$(trackio-view --once --zoom 3 | grep "Loss Change:" | awk '{print $3}')
if (( $(echo "$change < 0.001 && $change > -0.001" | bc -l) )); then
  echo "Training has converged"
fi
```

### Integration with CI/CD

```bash
# Check if loss is below threshold
trackio-view --project my-model --once | grep "Latest Loss:" | awk '{print $3}' | \
  awk '{if ($1 < 0.5) exit 0; else exit 1}'

# Send metrics to monitoring system
metrics=$(trackio-view --once)
iter=$(echo "$metrics" | grep "Latest Iteration:" | awk '{print $3}')
loss=$(echo "$metrics" | grep "Latest Loss:" | awk '{print $3}')
curl -X POST https://metrics.example.com/api/v1/datapoints \
  -d "series=training.loss&value=$loss&tags=iteration:$iter"
```

## See Also

- [trackio show](launch.md) - Web-based dashboard
- [trackio CLI](manage.md) - Other CLI commands
- [API Reference](api.md) - Python API documentation