#!/usr/bin/env python3
"""
TrackIO View - Terminal-based metrics viewer for TrackIO projects.

This provides a console UI for viewing TrackIO metrics in real-time without needing a web browser.
Perfect for monitoring training progress on remote servers or in terminal-only environments.

Inspired by the gputop project (https://github.com/mcgrof/gputop) for its elegant
terminal-based monitoring interface design.
"""

import argparse
import json
import os
import sys
import time
import signal
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from collections import deque
import sqlite3

# Try to import termios for raw keyboard input (Unix/Linux/Mac)
try:
    import termios
    import tty

    TERMIOS_AVAILABLE = True
except ImportError:
    TERMIOS_AVAILABLE = False

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.live import Live
    from rich.progress import (
        Progress,
        SpinnerColumn,
        TextColumn,
        BarColumn,
        TimeRemainingColumn,
    )
    from rich.text import Text
    from rich import box
    from rich.columns import Columns

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class Term:
    """Terminal control codes and variables"""

    width: int = 80
    height: int = 24
    resized: bool = True
    _w: int = 0
    _h: int = 0

    hide_cursor = "\033[?25l"
    show_cursor = "\033[?25h"
    alt_screen = "\033[?1049h"
    normal_screen = "\033[?1049l"
    clear = "\033[2J\033[0;0f"
    normal = "\033[0m"
    bold = "\033[1m"
    dim = "\033[2m"
    underline = "\033[4m"

    @classmethod
    def refresh(cls):
        """Get terminal dimensions"""
        try:
            cls._w, cls._h = os.get_terminal_size()
        except:
            cls._w, cls._h = 80, 24

        if cls._w != cls.width or cls._h != cls.height:
            cls.width = cls._w
            cls.height = cls._h
            cls.resized = True


class Color:
    """Color management for terminal output"""

    @staticmethod
    def fg(r: int, g: int, b: int) -> str:
        return f"\033[38;2;{r};{g};{b}m"

    @staticmethod
    def bg(r: int, g: int, b: int) -> str:
        return f"\033[48;2;{r};{g};{b}m"

    @staticmethod
    def gradient(value: float, colors: List[Tuple[int, int, int]]) -> str:
        """Generate color based on value (0.0-1.0) across gradient"""
        if value <= 0:
            return Color.fg(*colors[0])
        if value >= 1:
            return Color.fg(*colors[-1])

        segment_size = 1.0 / (len(colors) - 1)
        segment = int(value / segment_size)
        segment_pos = (value % segment_size) / segment_size

        if segment >= len(colors) - 1:
            return Color.fg(*colors[-1])

        c1 = colors[segment]
        c2 = colors[segment + 1]

        r = int(c1[0] + (c2[0] - c1[0]) * segment_pos)
        g = int(c1[1] + (c2[1] - c1[1]) * segment_pos)
        b = int(c1[2] + (c2[2] - c1[2]) * segment_pos)

        return Color.fg(r, g, b)


class Theme:
    """Color theme definitions"""

    # Loss gradient (blue -> green -> yellow -> red)
    loss_gradient = [
        (0, 100, 200),  # Blue (low loss)
        (0, 200, 100),  # Green
        (200, 200, 0),  # Yellow
        (255, 100, 0),  # Orange
        (255, 0, 0),  # Red (high loss)
    ]

    # Learning rate gradient
    lr_gradient = [
        (100, 100, 255),  # Light blue
        (200, 100, 255),  # Purple
        (255, 100, 200),  # Pink
    ]

    # Sparsity gradient (red -> yellow -> green)
    sparsity_gradient = [
        (255, 0, 0),  # Red (0% sparse)
        (255, 200, 0),  # Orange
        (255, 255, 0),  # Yellow
        (100, 255, 0),  # Light green
        (0, 255, 0),  # Green (100% sparse)
    ]

    main_fg = Color.fg(200, 200, 200)
    title = Color.fg(255, 255, 255)
    border = Color.fg(100, 100, 100)
    text = Color.fg(180, 180, 180)
    success = Color.fg(0, 255, 100)
    warning = Color.fg(255, 200, 0)
    error = Color.fg(255, 50, 50)


class Graph:
    """Enhanced graph with gradient colors and smooth rendering"""

    def __init__(
        self, width: int, height: int, min_value: float = 0, max_value: float = 100
    ):
        self.width = width
        self.height = height
        self.min_value = min_value
        self.max_value = max_value
        self.data = []  # Store all data points, not limited by width
        self.markers = []  # For marking special points

    def add_value(self, value: float):
        """Add a new value to the graph"""
        self.data.append(value)

    def add_marker(self, position: int, label: str):
        """Add a marker at a specific position"""
        self.markers.append((position, label))

    def draw(
        self, gradient: List[Tuple[int, int, int]], show_values: bool = True
    ) -> List[str]:
        """Draw the graph with gradient colors"""
        lines = []

        if not self.data:
            return [" " * self.width] * self.height

        # Sample or compress data to fit display width
        data_list = list(self.data)

        if len(data_list) > self.width:
            # Downsample data to fit in display width
            step = len(data_list) / self.width
            sampled_data = []
            for i in range(self.width):
                idx = int(i * step)
                sampled_data.append(data_list[idx])
            data_list = sampled_data
        elif len(data_list) < self.width:
            # Pad with the first value if we have less data than width
            # This keeps the graph left-aligned
            while len(data_list) < self.width:
                data_list.insert(0, data_list[0] if data_list else self.min_value)

        # Don't auto-adjust range - use the provided min/max from initialization
        # This ensures we see the full scale of all data, not just visible portion

        range_val = self.max_value - self.min_value
        if range_val == 0:
            range_val = 1

        # Create graph matrix
        matrix = [[" " for _ in range(self.width)] for _ in range(self.height)]

        # Plot data points with smoothing
        for col in range(len(data_list)):
            value = data_list[col]
            norm_value = (value - self.min_value) / range_val
            row = int((1 - norm_value) * (self.height - 1))

            if 0 <= row < self.height:
                # Use different characters for visual variety
                if col > 0:
                    prev_value = data_list[col - 1]
                    prev_norm = (prev_value - self.min_value) / range_val
                    prev_row = int((1 - prev_norm) * (self.height - 1))

                    # Draw connecting lines for smooth graph
                    if abs(prev_row - row) > 1:
                        step = 1 if row > prev_row else -1
                        for r in range(prev_row, row, step):
                            if 0 <= r < self.height:
                                matrix[r][col] = "│"

                # Use dots for actual data points
                matrix[row][col] = (
                    "●" if norm_value > 0.8 else "○" if norm_value > 0.5 else "·"
                )

        # Render with colors
        for row in range(self.height):
            line_chars = []
            for col in range(self.width):
                if matrix[row][col] != " ":
                    # Calculate color based on height position
                    height_ratio = 1 - (row / (self.height - 1))
                    color = Color.gradient(height_ratio, gradient)
                    line_chars.append(color + matrix[row][col] + Term.normal)
                else:
                    line_chars.append(" ")
            lines.append("".join(line_chars))

        # Add scale on the left if requested
        if show_values:
            for i, line in enumerate(lines):
                scale_val = self.max_value - (i / (self.height - 1)) * range_val
                scale_str = f"{scale_val:7.2f} "
                lines[i] = scale_str + line

        return lines


class MultiLineGraph:
    """Graph supporting multiple overlaid metrics"""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.metrics = {}  # Dict of metric_name: Graph
        self.colors = {}

    def add_metric(
        self,
        name: str,
        color: Tuple[int, int, int],
        min_val: float = 0,
        max_val: float = 100,
    ):
        """Add a metric to track"""
        self.metrics[name] = Graph(self.width, self.height, min_val, max_val)
        self.colors[name] = color

    def add_value(self, name: str, value: float):
        """Add value to specific metric"""
        if name in self.metrics:
            self.metrics[name].add_value(value)

    def draw(self) -> List[str]:
        """Draw all metrics overlaid"""
        lines = [" " * self.width for _ in range(self.height)]

        # Draw each metric with its own color
        for name, graph in self.metrics.items():
            if not graph.data:
                continue

            color = self.colors[name]
            color_str = Color.fg(*color)

            data_list = list(graph.data)
            while len(data_list) < self.width:
                data_list.insert(0, graph.min_value)

            range_val = graph.max_value - graph.min_value
            if range_val == 0:
                range_val = 1

            for col, value in enumerate(data_list):
                norm_value = (value - graph.min_value) / range_val
                row = int((1 - norm_value) * (self.height - 1))

                if 0 <= row < self.height and col < self.width:
                    # Only draw if position is empty or we're overlaying
                    char = "·" if len(self.metrics) > 1 else "●"
                    line_list = list(lines[row])
                    line_list[col] = char
                    lines[row] = "".join(line_list)

        # Add colors to final output
        colored_lines = []
        for line in lines:
            colored_line = ""
            for char in line:
                if char != " ":
                    # Use first metric's color for now
                    first_color = next(iter(self.colors.values()))
                    colored_line += Color.fg(*first_color) + char + Term.normal
                else:
                    colored_line += char
            colored_lines.append(colored_line)

        return colored_lines


# Import the dedicated GPU dashboard
try:
    from trackio.gpu_dashboard_gputop import GPUTop as GPUDashboard
except ImportError:
    # Fallback for when running directly
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from gpu_dashboard_gputop import GPUTop as GPUDashboard

# The GPUDashboard class is now imported from gpu_dashboard.py
# It provides the full gputop-like experience with graphs and colors


class TrackIOViewer:
    """Console viewer for TrackIO metrics."""

    def __init__(self, project: str):
        self.project = project
        self.console = Console() if RICH_AVAILABLE else None
        self.graphs = {}
        self.multi_graph = None
        self.use_advanced_ui = True  # Use advanced terminal UI by default
        self.zoom_level = (
            0  # 0 = show all, 1 = last 500, 2 = last 200, 3 = last 100, 4 = last 50
        )

        # Find TrackIO data location - check both directory and .db file formats
        self.trackio_dirs = [
            Path.home() / ".trackio" / project,
            Path.home() / ".cache" / "trackio" / project,
            Path.home() / ".cache" / "huggingface" / "trackio" / project,
            Path.home()
            / ".cache"
            / "huggingface"
            / "trackio"
            / f"{project}.db",  # Added: project.db format
            Path.cwd() / ".trackio" / project,
            Path.cwd() / f"trackio_{project}.db",
        ]

        self.data_dir = None
        self.db_path = None

        for path in self.trackio_dirs:
            if path.exists():
                if path.suffix == ".db":
                    self.db_path = path
                else:
                    self.data_dir = path
                break

    def find_latest_metrics(self) -> Optional[Dict[str, Any]]:
        """Find and load the latest metrics from TrackIO storage."""
        if self.db_path and self.db_path.exists():
            return self._read_from_db()
        elif self.data_dir and self.data_dir.exists():
            return self._read_from_json()
        return None

    def _read_from_db(self) -> Optional[Dict[str, Any]]:
        """Read metrics from SQLite database."""
        try:
            import json

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Try to find metrics table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [t[0] for t in cursor.fetchall()]

            metrics = {}
            if "metrics" in tables:
                # Get recent metrics with proper JSON parsing
                # Include id column since it's the first column in the schema
                # Get ALL metrics, not just recent ones
                cursor.execute(
                    "SELECT id, timestamp, run_name, step, metrics FROM metrics ORDER BY timestamp DESC"
                )
                rows = cursor.fetchall()
                if rows:
                    parsed_data = []
                    for id, timestamp, run_name, step, metrics_json in rows:
                        try:
                            # Parse the JSON metrics data
                            metrics_data = (
                                json.loads(metrics_json) if metrics_json else {}
                            )

                            # Create a flattened entry for display
                            entry = {
                                "timestamp": timestamp,
                                "run_name": run_name,
                                "step": step,
                                **metrics_data,  # Unpack the JSON metrics
                            }
                            parsed_data.append(entry)
                        except json.JSONDecodeError:
                            # Skip malformed JSON entries
                            continue

                    metrics["data"] = parsed_data

            conn.close()
            return metrics
        except Exception as e:
            print(f"Error reading database: {e}")
            return None

    def _read_from_json(self) -> Optional[Dict[str, Any]]:
        """Read metrics from JSON files."""
        metrics = {}

        # Find all run directories
        run_dirs = sorted([d for d in self.data_dir.iterdir() if d.is_dir()])

        if not run_dirs:
            return None

        # Get latest run
        latest_run = run_dirs[-1]
        metrics_file = latest_run / "metrics.json"

        if metrics_file.exists():
            with open(metrics_file) as f:
                data = json.load(f)
                metrics["run_name"] = latest_run.name
                metrics["data"] = data

        return metrics

    def parse_training_log(self, log_path: Path) -> Dict[str, Any]:
        """Parse a training output.log file for metrics."""
        metrics = {
            "iterations": [],
            "losses": [],
            "perplexities": [],
            "learning_rates": [],
            "sparsities": [],
            "times": [],
        }

        if not log_path.exists():
            return metrics

        with open(log_path) as f:
            for line in f:
                if "Iter" in line and "loss" in line and "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 5:
                        try:
                            metrics["iterations"].append(int(parts[0].split()[-1]))
                            metrics["losses"].append(float(parts[1].split()[-1]))
                            metrics["perplexities"].append(float(parts[2].split()[-1]))

                            lr_str = parts[3].split()[-1]
                            # Convert scientific notation
                            if "e" in lr_str:
                                metrics["learning_rates"].append(float(lr_str))
                            else:
                                metrics["learning_rates"].append(float(lr_str))

                            sparsity_str = parts[4].split()[1].rstrip("%")
                            metrics["sparsities"].append(float(sparsity_str))

                            # Extract time if present
                            if "ms/iter" in parts[-1]:
                                time_str = parts[-1].split()[-1].replace("ms/iter", "")
                                metrics["times"].append(float(time_str))
                        except (ValueError, IndexError):
                            continue

        return metrics

    def create_ascii_graph(
        self, values: List[float], width: int = 50, height: int = 10, title: str = ""
    ) -> str:
        """Create an ASCII graph of values with gradient coloring."""
        if not values:
            return "No data"

        min_val = min(values)
        max_val = max(values)

        # Use the enhanced Graph class
        graph = Graph(width, height, min_val, max_val)

        # Sample if too many values
        if len(values) > width:
            step = len(values) // width
            sampled_values = values[::step]
        else:
            sampled_values = values

        # Add all values to graph
        for v in sampled_values:
            graph.add_value(v)

        # Draw with gradient colors
        lines = graph.draw(Theme.loss_gradient, show_values=True)

        if title:
            lines.insert(0, "")
            lines.insert(0, f"  {Theme.title}{title}{Term.normal}")

        # Add x-axis
        lines.append(f"{'':7s} +{'-' * width}")

        return "\n".join(lines)

    def display_simple(self, metrics: Dict[str, Any], once_mode: bool = False):
        """Display metrics in simple ASCII format (no rich library)."""
        if not once_mode:
            print(f"{Term.clear}{Term.hide_cursor}")

        # Header with colors
        print(f"{Theme.border}" + "═" * 60 + f"{Term.normal}")
        print(
            f"  {Theme.title}TrackIO Console Dashboard - Project: {self.project}{Term.normal}"
        )
        print(f"{Theme.border}" + "═" * 60 + f"{Term.normal}")

        if not metrics:
            print("\n  No metrics found. Is training running?")
            return

        # If we have parsed training metrics
        if "iterations" in metrics and metrics["iterations"]:
            iters = metrics["iterations"]
            losses = metrics["losses"]

            # Color code the metrics
            print(
                f"\n  {Theme.text}Latest Iteration: {Theme.success}{iters[-1]}{Term.normal}"
            )

            # Color code loss based on value
            loss_color = (
                Theme.success
                if losses[-1] < 2
                else Theme.warning if losses[-1] < 4 else Theme.error
            )
            print(
                f"  {Theme.text}Latest Loss: {loss_color}{losses[-1]:.4f}{Term.normal}"
            )

            if len(losses) > 1:
                change = losses[-1] - losses[0]
                change_color = Theme.success if change < 0 else Theme.error
                print(
                    f"  {Theme.text}Loss Change: {change_color}{change:+.4f}{Term.normal}"
                )

            # ASCII graph of loss
            if len(losses) > 5:
                print(
                    "\n"
                    + self.create_ascii_graph(
                        losses[-50:] if len(losses) > 50 else losses,
                        width=50,
                        height=8,
                        title="Loss Trend",
                    )
                )

            # Show learning rate if available with color
            if "learning_rates" in metrics and metrics["learning_rates"]:
                lr = metrics["learning_rates"][-1]
                lr_color = Color.gradient(lr / 1e-2, Theme.lr_gradient)
                print(f"\n  {Theme.text}Learning Rate: {lr_color}{lr:.2e}{Term.normal}")

            # Show sparsity if available with gradient color
            if "sparsities" in metrics and metrics["sparsities"]:
                sparsity = metrics["sparsities"][-1]
                sparsity_color = Color.gradient(sparsity / 100, Theme.sparsity_gradient)
                print(
                    f"  {Theme.text}Sparsity: {sparsity_color}{sparsity:.1f}%{Term.normal}"
                )

            # Estimate time remaining
            if "times" in metrics and metrics["times"] and len(metrics["times"]) > 1:
                avg_time = sum(metrics["times"][-10:]) / len(metrics["times"][-10:])
                if iters[-1] < 500:  # Assume 500 iterations total
                    remaining = (500 - iters[-1]) * avg_time / 1000 / 60
                    print(f"\n  Estimated time remaining: {remaining:.1f} minutes")

    def display_stdout(self, metrics: Dict[str, Any]):
        """Display metrics for stdout output (--once mode)."""
        # Convert database format if needed
        if metrics and "data" in metrics and metrics["data"]:
            metrics = self._convert_db_to_display_format(metrics["data"])

        if not metrics or "iterations" not in metrics or not metrics["iterations"]:
            print(f"No metrics found for project: {self.project}")
            return

        # Apply zoom level if specified
        iters = metrics["iterations"]
        losses = metrics["losses"]

        zoom_windows = [0, 500, 200, 100, 50]  # 0 means show all
        zoom_labels = ["All data", "Last 500", "Last 200", "Last 100", "Last 50"]

        if self.zoom_level > 0 and len(iters) > zoom_windows[self.zoom_level]:
            window_size = zoom_windows[self.zoom_level]
            iters = iters[-window_size:]
            losses = losses[-window_size:]
            # Also slice other metrics if they exist
            if "learning_rates" in metrics:
                metrics["learning_rates"] = metrics["learning_rates"][-window_size:]
            if "sparsities" in metrics:
                metrics["sparsities"] = metrics["sparsities"][-window_size:]
            if "perplexities" in metrics:
                metrics["perplexities"] = metrics["perplexities"][-window_size:]

        print("=" * 60)
        print(f"TrackIO Dashboard - Project: {self.project}")
        print(f"View: {zoom_labels[self.zoom_level]}")
        print("=" * 60)
        print()
        print(f"Latest Iteration: {iters[-1]}")
        print(f"Latest Loss: {losses[-1]:.4f}")

        if len(losses) > 1:
            change = losses[-1] - losses[0]
            print(f"Loss Change: {change:+.4f} (from {losses[0]:.4f})")
            print(f"Min Loss: {min(losses):.4f}")
            print(f"Max Loss: {max(losses):.4f}")

        # Show other metrics if available
        if "learning_rates" in metrics and metrics["learning_rates"]:
            lr = metrics["learning_rates"][-1]
            print(f"Learning Rate: {lr:.2e}")

        if "sparsities" in metrics and metrics["sparsities"]:
            sparsity = metrics["sparsities"][-1]
            print(f"Sparsity: {sparsity:.1f}%")

        # Create a simple ASCII graph without colors
        if len(losses) > 5:
            # Show the graph title based on the data range
            if len(iters) > 0:
                graph_title = f"\nLoss Trend (Iterations {iters[0]} to {iters[-1]}):"
            else:
                graph_title = "\nLoss Trend:"
            print(graph_title)

            # Use all available data for the graph (already filtered by zoom)
            print(
                self.create_simple_ascii_graph(
                    losses,
                    width=min(
                        50, len(losses)
                    ),  # Don't make graph wider than data points
                    height=10,
                )
            )

    def create_simple_ascii_graph(
        self, values: List[float], width: int = 50, height: int = 10
    ) -> str:
        """Create a simple ASCII graph without terminal colors."""
        if not values:
            return "No data"

        min_val = min(values)
        max_val = max(values)
        range_val = max_val - min_val
        if range_val == 0:
            range_val = 1

        # Sample if too many values
        if len(values) > width:
            step = len(values) // width
            sampled_values = values[::step][:width]
        else:
            sampled_values = values

        # Create the graph
        lines = []
        for row in range(height):
            line = []
            y_val = max_val - (row * range_val / (height - 1))
            line.append(f"{y_val:7.2f} |")

            for col, val in enumerate(sampled_values):
                # Calculate if this point should be plotted
                point_row = int((max_val - val) * (height - 1) / range_val)
                if point_row == row:
                    line.append("*")
                else:
                    line.append(" ")
            lines.append("".join(line))

        # Add x-axis
        lines.append("        +" + "-" * len(sampled_values))

        return "\n".join(lines)

    def display_gpu_metrics_from_db(self, metrics: Dict[str, Any]):
        """Display GPU metrics that were logged to the database."""
        if not metrics or "data" not in metrics:
            print(f"No GPU metrics found for project: {self.project}")
            return

        data = metrics["data"]
        if not data:
            print(f"No GPU metrics found for project: {self.project}")
            return

        # Extract GPU metrics from database
        gpu_data = {}
        for entry in data:
            # Look for GPU-related keys
            for key, value in entry.items():
                if key.startswith('gpu/') or key.startswith('gpu_'):
                    if key not in gpu_data:
                        gpu_data[key] = []
                    gpu_data[key].append({
                        'step': entry.get('step', 0),
                        'timestamp': entry.get('timestamp', ''),
                        'value': value
                    })

        if not gpu_data:
            print(f"No GPU metrics found in database for project: {self.project}")
            return

        print("="*80)
        print(f"GPU Metrics from Database - Project: {self.project}")
        print("="*80)

        # Group metrics by type
        utilization_data = gpu_data.get('gpu/utilization', [])
        memory_used_data = gpu_data.get('gpu/memory_used_gb', [])
        memory_percent_data = gpu_data.get('gpu/memory_percent', [])
        temperature_data = gpu_data.get('gpu/temperature_c', [])
        power_data = gpu_data.get('gpu/power_w', [])

        # Show current (latest) values
        if utilization_data:
            latest = utilization_data[-1]
            print(f"\nLatest GPU Status (Step {latest['step']}):")
            print(f"  GPU Utilization: {latest['value']:.1f}%")

        if memory_used_data and memory_percent_data:
            mem_used = memory_used_data[-1]['value']
            mem_percent = memory_percent_data[-1]['value']
            print(f"  Memory Usage: {mem_used:.1f} GB ({mem_percent:.1f}%)")

        if temperature_data:
            temp = temperature_data[-1]['value']
            print(f"  Temperature: {temp:.0f}°C")

        if power_data:
            power = power_data[-1]['value']
            print(f"  Power: {power:.0f}W")

        # Show clock frequencies if available
        clock_keys = [k for k in gpu_data.keys() if 'clock_' in k]
        if clock_keys:
            print(f"  Clock Frequencies:")
            for clock_key in sorted(clock_keys):
                clock_name = clock_key.replace('gpu/', '').replace('_mhz', '').replace('clock_', '')
                latest_clock = gpu_data[clock_key][-1]['value']
                print(f"    {clock_name.title()}: {latest_clock:.0f} MHz")

        # Show historical trends if we have multiple data points
        print(f"\nHistorical Data ({len(data)} logged entries):")

        if utilization_data and len(utilization_data) > 1:
            utils = [d['value'] for d in utilization_data]
            print(f"  GPU Utilization: {min(utils):.1f}% - {max(utils):.1f}% (avg: {sum(utils)/len(utils):.1f}%)")

        if temperature_data and len(temperature_data) > 1:
            temps = [d['value'] for d in temperature_data]
            print(f"  Temperature: {min(temps):.0f}°C - {max(temps):.0f}°C (avg: {sum(temps)/len(temps):.0f}°C)")

        if power_data and len(power_data) > 1:
            powers = [d['value'] for d in power_data]
            print(f"  Power: {min(powers):.0f}W - {max(powers):.0f}W (avg: {sum(powers)/len(powers):.0f}W)")

        # Show step range
        all_steps = []
        for metric_data in gpu_data.values():
            all_steps.extend([d['step'] for d in metric_data])

        if all_steps:
            print(f"\nData Range: Steps {min(all_steps)} - {max(all_steps)}")

        # Show available metrics summary
        print(f"\nAvailable GPU Metrics:")
        for key in sorted(gpu_data.keys()):
            metric_name = key.replace('gpu/', '').replace('gpu_', '')
            print(f"  - {metric_name} ({len(gpu_data[key])} data points)")

    def display_rich(self, metrics: Dict[str, Any]):
        """Display metrics with rich formatting."""
        if not RICH_AVAILABLE:
            return self.display_simple(metrics)

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )

        # Header
        header_text = Text(
            f"TrackIO Console Dashboard - {self.project}", justify="center"
        )
        header_text.stylize("bold magenta")
        layout["header"].update(Panel(header_text))

        # Body content
        if not metrics:
            layout["body"].update(Panel("No metrics found. Is training running?"))
        else:
            body_layout = Layout()
            body_layout.split_row(
                Layout(name="metrics", ratio=1), Layout(name="graph", ratio=2)
            )

            # Metrics table
            table = Table(box=box.ROUNDED)
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="green")

            if "iterations" in metrics and metrics["iterations"]:
                table.add_row("Iteration", str(metrics["iterations"][-1]))
                table.add_row("Loss", f"{metrics['losses'][-1]:.4f}")

                if "perplexities" in metrics:
                    table.add_row("Perplexity", f"{metrics['perplexities'][-1]:.1f}")
                if "learning_rates" in metrics:
                    table.add_row(
                        "Learning Rate", f"{metrics['learning_rates'][-1]:.2e}"
                    )
                if "sparsities" in metrics:
                    table.add_row("Sparsity", f"{metrics['sparsities'][-1]:.1f}%")

            body_layout["metrics"].update(Panel(table, title="Current Metrics"))

            # Graph
            if "losses" in metrics and len(metrics["losses"]) > 1:
                graph_text = self.create_ascii_graph(
                    (
                        metrics["losses"][-50:]
                        if len(metrics["losses"]) > 50
                        else metrics["losses"]
                    ),
                    width=40,
                    height=10,
                    title="Loss",
                )
                body_layout["graph"].update(
                    Panel(graph_text, title="Training Progress")
                )

            layout["body"].update(body_layout)

        # Footer
        layout["footer"].update(
            Panel(
                Text("Press Ctrl+C to exit | Updates every 2 seconds", justify="center")
            )
        )

        self.console.print(layout)

    def monitor_live(self, log_path: Optional[Path] = None, interval: int = 2):
        """Monitor metrics live with updates."""
        # Set up terminal
        print(f"{Term.alt_screen}{Term.hide_cursor}")

        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            print(f"{Term.normal_screen}{Term.show_cursor}")
            print("\n\nDashboard closed.")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)

        # Handle terminal resize (if supported)
        try:

            def resize_handler(sig, frame):
                Term.resized = True

            signal.signal(signal.SIGWINCH, resize_handler)
        except (AttributeError, ValueError):
            # SIGWINCH not available on this platform
            pass

        # Set terminal to raw mode for immediate keyboard input
        old_settings = None
        if TERMIOS_AVAILABLE and sys.stdin.isatty():
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())

        try:
            # Try to import select for keyboard input (Unix/Linux)
            try:
                import select

                has_select = True
            except ImportError:
                has_select = False

            iteration = 0
            last_update = time.time()

            while True:
                Term.refresh()

                if log_path and log_path.exists():
                    metrics = self.parse_training_log(log_path)
                else:
                    metrics = self.find_latest_metrics()

                # Check for keyboard input (non-blocking) if select is available
                if has_select and sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    key = sys.stdin.read(1)
                    if key == "+":
                        self.zoom_level = min(4, self.zoom_level + 1)
                        last_update = 0  # Force immediate redraw
                    elif key == "-":
                        self.zoom_level = max(0, self.zoom_level - 1)
                        last_update = 0  # Force immediate redraw
                    elif key.lower() == "q":
                        raise KeyboardInterrupt

                # Only update display if interval has passed or zoom changed
                current_time = time.time()
                if current_time - last_update >= interval:
                    if RICH_AVAILABLE and not self.use_advanced_ui:
                        self.display_rich(metrics)
                    else:
                        self.display_advanced(metrics, iteration)
                    last_update = current_time
                    iteration += 1

                time.sleep(
                    0.1 if has_select else interval
                )  # Adjust sleep based on keyboard support

        except KeyboardInterrupt:
            pass
        finally:
            # Always restore terminal settings
            if old_settings:
                termios.tcsetattr(sys.stdin, termios.TCSANOW, old_settings)
            print(f"{Term.normal_screen}{Term.show_cursor}")
            print("\n\nDashboard closed.")

    def display_advanced(self, metrics: Dict[str, Any], iteration: int):
        """Display with advanced terminal UI features."""
        print(Term.clear)

        # Draw border box
        self._draw_box(
            1, 1, Term.width - 2, Term.height - 2, f"TrackIO Dashboard - {self.project}"
        )

        if not metrics:
            self._center_text(
                Term.height // 2,
                "No metrics found. Is training running?",
                Theme.warning,
            )
            return

        # If we have data from database
        if "data" in metrics and metrics["data"]:
            # Convert database format to display format
            display_metrics = self._convert_db_to_display_format(metrics["data"])
            self._display_training_metrics(display_metrics)
        # If we have parsed training metrics
        elif "iterations" in metrics and metrics["iterations"]:
            self._display_training_metrics(metrics)

    def _convert_db_to_display_format(self, data: list) -> Dict[str, Any]:
        """Convert database format to display format."""
        # Data comes in reverse chronological order, so reverse it for proper display
        data_reversed = list(reversed(data))

        # Extract iterations, losses, and other metrics
        # Use a dict to handle duplicates - keep only the latest value for each iteration
        metrics_by_iter = {}

        for entry in data_reversed:
            # Use 'iteration' if available, otherwise use 'step'
            iter_num = None
            if "iteration" in entry:
                iter_num = entry["iteration"]
            elif "step" in entry:
                iter_num = entry["step"]

            if iter_num is not None:
                # Store or update the metrics for this iteration
                if iter_num not in metrics_by_iter:
                    metrics_by_iter[iter_num] = {}
                if "train_loss" in entry:
                    metrics_by_iter[iter_num]["train_loss"] = entry["train_loss"]
                if "learning_rate" in entry:
                    metrics_by_iter[iter_num]["learning_rate"] = entry["learning_rate"]
                if "sparsity" in entry:
                    metrics_by_iter[iter_num]["sparsity"] = entry["sparsity"]

        # Now convert to lists, sorted by iteration
        sorted_iters = sorted(metrics_by_iter.keys())

        # Filter out initialization artifacts (iteration 0 with very low loss)
        # Real training typically starts with higher loss
        if len(sorted_iters) > 1 and 0 in sorted_iters:
            if "train_loss" in metrics_by_iter[0]:
                first_loss = metrics_by_iter[0]["train_loss"]
                second_loss = (
                    metrics_by_iter[sorted_iters[1]]["train_loss"]
                    if "train_loss" in metrics_by_iter[sorted_iters[1]]
                    else 0
                )
                # If iteration 0 has suspiciously low loss compared to iteration 1/2, skip it
                if first_loss < 2.0 and second_loss > 5.0:
                    sorted_iters = sorted_iters[1:]  # Skip iteration 0

        iterations = []
        losses = []
        learning_rates = []
        sparsities = []

        for iter_num in sorted_iters:
            iterations.append(iter_num)
            if "train_loss" in metrics_by_iter[iter_num]:
                losses.append(metrics_by_iter[iter_num]["train_loss"])
            if "learning_rate" in metrics_by_iter[iter_num]:
                learning_rates.append(metrics_by_iter[iter_num]["learning_rate"])
            if "sparsity" in metrics_by_iter[iter_num]:
                sparsities.append(metrics_by_iter[iter_num]["sparsity"])

        # Ensure we have data to display
        if not iterations or not losses:
            return {}

        # Return in expected format
        result = {
            "iterations": iterations,
            "losses": losses,
        }

        if learning_rates:
            result["learning_rates"] = learning_rates
        if sparsities:
            result["sparsities"] = sparsities

        # Add latest values for display (from original data[0] which is most recent)
        if data:
            latest = data[0]  # Most recent entry
            result["current_iter"] = latest.get("iteration", 0)
            result["current_loss"] = latest.get("train_loss", 0)
            result["current_lr"] = latest.get("learning_rate", 0)
            result["current_sparsity"] = latest.get("sparsity", 0)

        return result

    def _draw_box(self, x: int, y: int, w: int, h: int, title: str = ""):
        """Draw a box with optional title."""
        print(f"\033[{y};{x}f{Theme.border}┌", end="")
        if title:
            title_str = f"─┤ {Theme.title}{title}{Theme.border} ├"
            print(title_str, end="")
            remaining = w - len(title) - 6
            print("─" * remaining, end="")
        else:
            print("─" * (w - 2), end="")
        print("┐")

        for i in range(1, h - 1):
            print(f"\033[{y + i};{x}f│", end="")
            print(f"\033[{y + i};{x + w - 1}f│")

        print(f"\033[{y + h - 1};{x}f└" + "─" * (w - 2) + f"┘{Term.normal}")

    def _center_text(self, y: int, text: str, color: str = ""):
        """Center text on a line."""
        x = (Term.width - len(text)) // 2
        print(f"\033[{y};{x}f{color}{text}{Term.normal}")

    def _display_training_metrics(self, metrics: Dict[str, Any]):
        """Display training metrics with graphs."""
        iters = metrics["iterations"]
        losses = metrics["losses"]

        # Apply zoom level to determine how much data to show
        zoom_windows = [0, 500, 200, 100, 50]  # 0 means show all
        if self.zoom_level > 0 and len(iters) > zoom_windows[self.zoom_level]:
            window_size = zoom_windows[self.zoom_level]
            iters = iters[-window_size:]
            losses = losses[-window_size:]
            # Also slice other metrics if they exist
            if "learning_rates" in metrics:
                metrics["learning_rates"] = metrics["learning_rates"][-window_size:]
            if "sparsities" in metrics:
                metrics["sparsities"] = metrics["sparsities"][-window_size:]
            if "perplexities" in metrics:
                metrics["perplexities"] = metrics["perplexities"][-window_size:]

        # Stats panel
        stats_y = 3
        stats_x = 3

        print(f"\033[{stats_y};{stats_x}f{Theme.text}Current Statistics:{Term.normal}")
        stats_y += 2

        # Iteration
        print(
            f"\033[{stats_y};{stats_x}f{Theme.text}Iteration: {Theme.success}{iters[-1]}{Term.normal}"
        )
        stats_y += 1

        # Loss with color coding
        loss_color = (
            Theme.success
            if losses[-1] < 2
            else Theme.warning if losses[-1] < 4 else Theme.error
        )
        print(
            f"\033[{stats_y};{stats_x}f{Theme.text}Loss: {loss_color}{losses[-1]:.4f}{Term.normal}"
        )
        stats_y += 1

        # Loss change
        if len(losses) > 1:
            change = losses[-1] - losses[0]
            change_color = Theme.success if change < 0 else Theme.error
            print(
                f"\033[{stats_y};{stats_x}f{Theme.text}Change: {change_color}{change:+.4f}{Term.normal}"
            )
            stats_y += 1

        # Additional metrics
        if "perplexities" in metrics and metrics["perplexities"]:
            ppl = metrics["perplexities"][-1]
            ppl_color = (
                Theme.success
                if ppl < 100
                else Theme.warning if ppl < 200 else Theme.error
            )
            print(
                f"\033[{stats_y};{stats_x}f{Theme.text}Perplexity: {ppl_color}{ppl:.1f}{Term.normal}"
            )
            stats_y += 1

        if "learning_rates" in metrics and metrics["learning_rates"]:
            lr = metrics["learning_rates"][-1]
            print(
                f"\033[{stats_y};{stats_x}f{Theme.text}LR: {Theme.warning}{lr:.2e}{Term.normal}"
            )
            stats_y += 1

        if "sparsities" in metrics and metrics["sparsities"]:
            sparsity = metrics["sparsities"][-1]
            sparsity_color = Color.gradient(sparsity / 100, Theme.sparsity_gradient)
            print(
                f"\033[{stats_y};{stats_x}f{Theme.text}Sparsity: {sparsity_color}{sparsity:.1f}%{Term.normal}"
            )
            stats_y += 1

        # Graph panel - Loss over time
        # Use most of the terminal width for the graph
        # Leave space for: left border (3) + stats panel (25) + gap (2) + scale (8) + right border (3)
        stats_panel_width = 25
        graph_width = max(40, Term.width - stats_panel_width - 15)
        # Use most of the terminal height, leaving space for header and footer
        graph_height = max(10, Term.height - 10)
        # Position graph to the right of stats panel
        graph_x = stats_panel_width + 5
        graph_y = 3

        if len(losses) > 1:
            # Create and draw loss graph with ALL data points
            # Calculate range from ALL losses to properly scale Y-axis
            all_min = min(losses)
            all_max = max(losses)

            # Add some padding to the Y-axis range for better visibility
            range_padding = (all_max - all_min) * 0.1
            if range_padding == 0:  # Handle case where all values are the same
                range_padding = all_min * 0.1 if all_min != 0 else 1.0

            loss_graph = Graph(
                graph_width,
                graph_height,
                all_min - range_padding,
                all_max + range_padding,
            )

            # Add ALL loss values to the graph
            # The Graph class will handle sampling/compression if needed
            for loss in losses:
                loss_graph.add_value(loss)

            graph_lines = loss_graph.draw(Theme.loss_gradient, show_values=True)

            print(f"\033[{graph_y};{graph_x + 8}f{Theme.text}Loss Trend:{Term.normal}")
            for i, line in enumerate(graph_lines):
                print(f"\033[{graph_y + i + 1};{graph_x}f{line}")

            # Add X-axis labels showing iteration range
            x_axis_y = graph_y + len(graph_lines) + 1
            # Show first and last iteration numbers
            first_iter = iters[0]
            last_iter = iters[-1]

            # Draw X-axis line
            print(f"\033[{x_axis_y};{graph_x + 8}f" + "─" * graph_width)

            # Add iteration labels at start, middle, and end
            label_start = f"Iter {first_iter}"
            label_end = f"Iter {last_iter}"
            mid_iter = iters[len(iters) // 2] if len(iters) > 2 else ""
            label_mid = f"Iter {mid_iter}" if mid_iter else ""

            # Position labels
            print(
                f"\033[{x_axis_y + 1};{graph_x + 8}f{Theme.text}{label_start}{Term.normal}"
            )
            if label_mid:
                mid_pos = graph_x + 8 + (graph_width // 2) - (len(label_mid) // 2)
                print(
                    f"\033[{x_axis_y + 1};{mid_pos}f{Theme.text}{label_mid}{Term.normal}"
                )
            end_pos = graph_x + 8 + graph_width - len(label_end)
            print(f"\033[{x_axis_y + 1};{end_pos}f{Theme.text}{label_end}{Term.normal}")

            # Show zoom level indicator
            zoom_labels = ["All data", "Last 500", "Last 200", "Last 100", "Last 50"]
            zoom_text = f"View: {zoom_labels[self.zoom_level]} | Press +/- to zoom"
            zoom_y = x_axis_y + 3
            print(f"\033[{zoom_y};{graph_x + 8}f{Theme.text}{zoom_text}{Term.normal}")

        # Time estimate
        if "times" in metrics and metrics["times"] and len(metrics["times"]) > 1:
            avg_time = sum(metrics["times"][-10:]) / len(metrics["times"][-10:])
            if iters[-1] < 500:  # Assume 500 iterations total
                remaining = (500 - iters[-1]) * avg_time / 1000 / 60
                time_y = Term.height - 3
                print(
                    f"\033[{time_y};{stats_x}f{Theme.text}Est. remaining: {Theme.warning}{remaining:.1f} min{Term.normal}"
                )

    def monitor_gpu_db_live(self, interval: int = 2):
        """Monitor GPU metrics from database with live updates."""
        # Set up terminal
        print(f"{Term.alt_screen}{Term.hide_cursor}")

        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            print(f"{Term.normal_screen}{Term.show_cursor}")
            print("\n\nGPU database monitoring closed.")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)

        # Handle terminal resize (if supported)
        try:
            def resize_handler(sig, frame):
                Term.resized = True

            signal.signal(signal.SIGWINCH, resize_handler)
        except (AttributeError, ValueError):
            # SIGWINCH not available on this platform
            pass

        # Set terminal to raw mode for immediate keyboard input
        old_settings = None
        if TERMIOS_AVAILABLE and sys.stdin.isatty():
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())

        try:
            # Try to import select for keyboard input (Unix/Linux)
            try:
                import select
                has_select = True
            except ImportError:
                has_select = False

            iteration = 0
            last_update = time.time()
            last_data_count = 0

            while True:
                Term.refresh()

                # Get latest GPU metrics from database
                metrics = self.find_latest_metrics()

                # Check for keyboard input (non-blocking) if select is available
                if has_select and sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    key = sys.stdin.read(1)
                    if key == '+':
                        self.zoom_level = min(4, self.zoom_level + 1)
                        last_update = 0  # Force immediate redraw
                    elif key == '-':
                        self.zoom_level = max(0, self.zoom_level - 1)
                        last_update = 0  # Force immediate redraw
                    elif key.lower() == 'q':
                        raise KeyboardInterrupt

                # Only update display if interval has passed or data changed
                current_time = time.time()
                current_data_count = len(metrics.get('data', [])) if metrics else 0

                if (current_time - last_update >= interval or
                    current_data_count != last_data_count):

                    self.display_gpu_db_live(metrics, iteration)
                    last_update = current_time
                    last_data_count = current_data_count
                    iteration += 1

                time.sleep(0.1 if has_select else interval)  # Adjust sleep based on keyboard support

        except KeyboardInterrupt:
            pass
        finally:
            # Always restore terminal settings
            if old_settings:
                termios.tcsetattr(sys.stdin, termios.TCSANOW, old_settings)
            print(f"{Term.normal_screen}{Term.show_cursor}")
            print("\n\nGPU database monitoring closed.")

    def display_gpu_db_live(self, metrics: Dict[str, Any], iteration: int):
        """Display GPU database metrics with live terminal UI."""
        print(Term.clear)

        # Draw border box
        self._draw_box(
            1, 1, Term.width - 2, Term.height - 2, f"GPU Database Monitor - {self.project}"
        )

        if not metrics or "data" not in metrics or not metrics["data"]:
            self._center_text(
                Term.height // 2,
                "No GPU metrics found in database. Start training with log_gpu=True",
                Theme.warning,
            )
            return

        data = metrics["data"]

        # Extract latest GPU data for display
        latest_entry = data[0]  # Most recent entry
        gpu_data = {}

        # Collect all GPU metrics from the latest entry
        for key, value in latest_entry.items():
            if key.startswith('gpu/') or key.startswith('gpu_'):
                gpu_data[key] = value

        if not gpu_data:
            self._center_text(
                Term.height // 2,
                "No GPU metrics in database entries",
                Theme.warning,
            )
            return

        # Stats panel on the left
        stats_y = 3
        stats_x = 3

        print(f"\033[{stats_y};{stats_x}f{Theme.text}GPU Database Status:{Term.normal}")
        stats_y += 2

        # Data info
        print(f"\033[{stats_y};{stats_x}f{Theme.text}Total Entries: {Theme.success}{len(data)}{Term.normal}")
        stats_y += 1

        if latest_entry.get('step') is not None:
            print(f"\033[{stats_y};{stats_x}f{Theme.text}Latest Step: {Theme.success}{latest_entry['step']}{Term.normal}")
            stats_y += 1

        # GPU utilization
        if 'gpu/utilization' in gpu_data:
            util = gpu_data['gpu/utilization']
            util_color = Theme.success if util > 80 else Theme.warning if util > 50 else Theme.error
            print(f"\033[{stats_y};{stats_x}f{Theme.text}GPU Util: {util_color}{util:.1f}%{Term.normal}")
            stats_y += 1

        # Memory usage
        if 'gpu/memory_used_gb' in gpu_data and 'gpu/memory_percent' in gpu_data:
            mem_gb = gpu_data['gpu/memory_used_gb']
            mem_pct = gpu_data['gpu/memory_percent']
            mem_color = Theme.error if mem_pct > 90 else Theme.warning if mem_pct > 70 else Theme.success
            print(f"\033[{stats_y};{stats_x}f{Theme.text}Memory: {mem_color}{mem_gb:.1f}GB ({mem_pct:.1f}%){Term.normal}")
            stats_y += 1

        # Temperature
        if 'gpu/temperature_c' in gpu_data:
            temp = gpu_data['gpu/temperature_c']
            temp_color = Theme.error if temp > 80 else Theme.warning if temp > 70 else Theme.success
            print(f"\033[{stats_y};{stats_x}f{Theme.text}Temp: {temp_color}{temp:.0f}°C{Term.normal}")
            stats_y += 1

        # Power
        if 'gpu/power_w' in gpu_data:
            power = gpu_data['gpu/power_w']
            power_color = Theme.warning
            power_text = f"{power:.0f}W"
            if 'gpu/power_limit_w' in gpu_data:
                power_limit = gpu_data['gpu/power_limit_w']
                power_text = f"{power:.0f}/{power_limit:.0f}W"
            print(f"\033[{stats_y};{stats_x}f{Theme.text}Power: {power_color}{power_text}{Term.normal}")
            stats_y += 1

        # Clock frequencies
        stats_y += 1
        print(f"\033[{stats_y};{stats_x}f{Theme.text}Clock Frequencies:{Term.normal}")
        stats_y += 1

        clock_keys = [k for k in gpu_data.keys() if 'clock_' in k]
        for clock_key in sorted(clock_keys):
            clock_name = clock_key.replace('gpu/', '').replace('_mhz', '').replace('clock_', '')
            freq = gpu_data[clock_key]
            print(f"\033[{stats_y};{stats_x}f{Theme.text}  {clock_name.title()}: {Theme.warning}{freq:.0f} MHz{Term.normal}")
            stats_y += 1

        # Right side - trends/graphs
        graph_x = 35
        graph_y = 3

        # Show historical trends for key metrics
        utilization_history = []
        temp_history = []
        power_history = []

        # Extract historical data (last 50 entries for trend)
        for entry in reversed(data[-50:]):  # Get last 50, reverse to chronological order
            if 'gpu/utilization' in entry:
                utilization_history.append(entry['gpu/utilization'])
            if 'gpu/temperature_c' in entry:
                temp_history.append(entry['gpu/temperature_c'])
            if 'gpu/power_w' in entry:
                power_history.append(entry['gpu/power_w'])

        # GPU Utilization trend
        if len(utilization_history) > 1:
            print(f"\033[{graph_y};{graph_x}f{Theme.text}GPU Utilization Trend (Last {len(utilization_history)} entries):{Term.normal}")
            graph_y += 1

            # Simple ASCII trend
            trend_width = min(40, Term.width - graph_x - 5)
            trend_height = 8
            util_graph = Graph(trend_width, trend_height, 0, 100)

            for util in utilization_history:
                util_graph.add_value(util)

            trend_lines = util_graph.draw(Theme.loss_gradient, show_values=False)
            for i, line in enumerate(trend_lines):
                print(f"\033[{graph_y + i};{graph_x}f{line}")

            graph_y += len(trend_lines) + 2

        # Temperature trend
        if len(temp_history) > 1 and graph_y < Term.height - 8:
            print(f"\033[{graph_y};{graph_x}f{Theme.text}Temperature Trend:{Term.normal}")
            graph_y += 1

            trend_width = min(40, Term.width - graph_x - 5)
            trend_height = 6
            temp_min = max(0, min(temp_history) - 5)
            temp_max = max(temp_history) + 5
            temp_graph = Graph(trend_width, trend_height, temp_min, temp_max)

            for temp in temp_history:
                temp_graph.add_value(temp)

            trend_lines = temp_graph.draw([(255, 0, 0), (255, 255, 0), (0, 255, 0)], show_values=False)
            for i, line in enumerate(trend_lines):
                print(f"\033[{graph_y + i};{graph_x}f{line}")

        # Footer with instructions
        footer_y = Term.height - 3
        footer_text = "Press +/- to zoom, 'q' to quit, Ctrl+C to exit"
        print(f"\033[{footer_y};{3}f{Theme.text}{footer_text}{Term.normal}")

        # Update indicator
        update_text = f"Updates: {iteration} | Last: {datetime.now().strftime('%H:%M:%S')}"
        update_x = Term.width - len(update_text) - 3
        print(f"\033[{footer_y};{update_x}f{Theme.text}{update_text}{Term.normal}")


def main():
    parser = argparse.ArgumentParser(description="TrackIO Console Dashboard")
    parser.add_argument("--project", "-p", help="TrackIO project name", default=None)
    parser.add_argument(
        "--log", "-l", help="Path to training output.log file", default=None
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=2,
        help="Update interval in seconds (default: 2)",
    )
    parser.add_argument(
        "--once", action="store_true", help="Display once and exit (no live monitoring)"
    )
    parser.add_argument(
        "--zoom",
        "-z",
        type=int,
        default=0,
        choices=[0, 1, 2, 3, 4],
        help="Initial zoom level: 0=all data (default), 1=last 500, 2=last 200, 3=last 100, 4=last 50",
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="Show live GPU hardware metrics instead of training metrics"
    )
    parser.add_argument(
        "--gpu-db",
        action="store_true",
        help="Show GPU metrics from logged database instead of live hardware (requires --project)"
    )

    args = parser.parse_args()

    # Try to auto-detect project from .config if not specified
    if not args.project and not args.log:
        config_file = Path(".config")
        if config_file.exists():
            with open(config_file) as f:
                for line in f:
                    if "CONFIG_TRACKER_PROJECT" in line:
                        args.project = line.split('"')[1]
                        break

    # Try to find latest log file if not specified
    if not args.log and not args.project:
        # Look for latest test_matrix_results
        test_dirs = sorted(Path(".").glob("test_matrix_results_*"))
        if test_dirs:
            latest_test = test_dirs[-1]
            log_files = list(latest_test.glob("*/output.log"))
            if log_files:
                args.log = log_files[0]

    # If no project specified, try to find any trackio project
    if not args.project and not args.log:
        # Look for any trackio databases in common locations
        trackio_paths = [
            Path.home() / ".cache" / "huggingface" / "trackio",
            Path.home() / ".cache" / "trackio",
            Path.home() / ".trackio",
        ]

        for base_path in trackio_paths:
            if base_path.exists():
                # Find any .db files or project directories
                db_files = list(base_path.glob("*.db"))
                if db_files:
                    # Use the first found database
                    args.project = db_files[0].stem
                    break

                # Look for project directories
                subdirs = [d for d in base_path.iterdir() if d.is_dir()]
                if subdirs:
                    args.project = subdirs[0].name
                    break

        if not args.project:
            print("No TrackIO projects found. Starting in demo mode...")
            print("\nTo monitor a specific project, use:")
            print("  trackio-view --project PROJECT_NAME")
            print("\nTo monitor a training log, use:")
            print("  trackio-view --log path/to/output.log")
            args.project = "demo"

    # Handle GPU database option first
    if args.gpu_db:
        if not args.project:
            print("Error: --gpu-db requires --project to be specified")
            sys.exit(1)

        dashboard = TrackIOViewer(args.project)
        dashboard.zoom_level = args.zoom
        if args.once:
            metrics = dashboard.find_latest_metrics()
            dashboard.display_gpu_metrics_from_db(metrics)
        else:
            dashboard.monitor_gpu_db_live(args.interval)
    # If GPU monitoring requested, show GPU stats instead
    elif args.gpu:
        # Import GPU monitor with proper path handling
        try:
            from trackio.gpu_monitor import GPUMonitor
        except ImportError:
            # Fallback for when running directly
            sys.path.insert(0, str(Path(__file__).parent))
            from gpu_monitor import GPUMonitor
        monitor = GPUMonitor()

        if args.once:
            # Display GPU stats once and exit
            stats = monitor.get_all_gpu_stats()
            print("="*60)
            print("GPU Status")
            print("="*60)

            if not stats:
                print("No GPUs detected")
            else:
                for i, gpu_stats in enumerate(stats):
                    if not gpu_stats.get('available', False):
                        continue

                    prefix = f"GPU {i}: " if len(stats) > 1 else ""
                    print(f"\n{prefix}{gpu_stats['name']}")
                    print(f"  Utilization: {gpu_stats['utilization']:.1f}%")
                    print(f"  Memory: {gpu_stats['memory_used']:.1f}/{gpu_stats['memory_total']:.1f} GB ({gpu_stats['memory_percent']:.1f}%)")
                    print(f"  Temperature: {gpu_stats['temperature']:.0f}°C")

                    # Power
                    if gpu_stats.get('power', 0) > 0:
                        if gpu_stats.get('power_limit', 0) > 0:
                            print(f"  Power: {gpu_stats['power']:.0f}/{gpu_stats['power_limit']:.0f}W")
                        else:
                            print(f"  Power: {gpu_stats['power']:.0f}W")

                    # Fan
                    if gpu_stats.get('fan_speed', 0) > 0:
                        fan_text = f"  Fan: {gpu_stats['fan_speed']:.1f}%"
                        if gpu_stats.get('fan_rpm', 0) > 0:
                            fan_text += f" ({gpu_stats['fan_rpm']:.0f} RPM)"
                        print(fan_text)

                    # Clocks
                    if gpu_stats.get('clocks'):
                        if 'graphics' in gpu_stats['clocks']:
                            print(f"  GPU Clock: {gpu_stats['clocks']['graphics']:.0f} MHz")
                        if 'memory' in gpu_stats['clocks']:
                            print(f"  Mem Clock: {gpu_stats['clocks']['memory']:.0f} MHz")

                    # Performance state
                    if gpu_stats.get('performance_state'):
                        print(f"  Perf State: {gpu_stats['performance_state']}")
        else:
            # Live GPU monitoring
            dashboard = GPUDashboard()
            dashboard.monitor_live(args.interval)
    # Regular training metrics display
    elif args.log:
        log_path = Path(args.log)
        if not log_path.exists():
            print(f"Error: Log file not found: {log_path}")
            sys.exit(1)

        dashboard = TrackIOViewer(args.project or "training")
        dashboard.zoom_level = args.zoom
        if args.once:
            metrics = dashboard.parse_training_log(log_path)
            dashboard.display_stdout(metrics)
        else:
            dashboard.monitor_live(log_path, args.interval)
    else:
        dashboard = TrackIOViewer(args.project)
        dashboard.zoom_level = args.zoom
        if args.once:
            metrics = dashboard.find_latest_metrics()
            dashboard.display_stdout(metrics)
        else:
            dashboard.monitor_live(None, args.interval)


if __name__ == "__main__":
    main()
