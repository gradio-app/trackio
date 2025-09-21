#!/usr/bin/env python3
"""
GPU Dashboard for trackio-view --gpu
Exact gputop.py display style
"""

import os, sys, threading, signal, subprocess
from time import time, sleep, strftime
from typing import List, Dict, Tuple, Union, Any
from collections import deque
from math import ceil
from pathlib import Path
import select
import termios
import tty

# Import GPU monitor
try:
    from trackio.gpu_monitor import GPUMonitor
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from gpu_monitor import GPUMonitor

VERSION = "2.0.0-unified"


class Term:
    """Terminal control codes and variables"""

    width: int = 0
    height: int = 0
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
    unbold = "\033[22m"
    dim = "\033[2m"
    undim = "\033[22m"
    italic = "\033[3m"
    unitalic = "\033[23m"
    underline = "\033[4m"
    nounderline = "\033[24m"
    blink = "\033[5m"
    unblink = "\033[25m"
    reverse = "\033[7m"
    noreverse = "\033[27m"

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

    # GPU utilization gradient (green -> yellow -> red)
    gpu_gradient = [
        (0, 200, 0),  # Green
        (200, 200, 0),  # Yellow
        (255, 100, 0),  # Orange
        (255, 0, 0),  # Red
    ]

    # Memory gradient (blue -> cyan -> yellow -> red)
    mem_gradient = [
        (0, 100, 200),  # Blue
        (0, 200, 200),  # Cyan
        (200, 200, 0),  # Yellow
        (255, 0, 0),  # Red
    ]

    # Temperature gradient (blue -> green -> yellow -> red)
    temp_gradient = [
        (0, 150, 255),  # Cool blue
        (0, 255, 150),  # Green
        (255, 255, 0),  # Yellow
        (255, 100, 0),  # Orange
        (255, 0, 0),  # Red
    ]

    main_fg = Color.fg(200, 200, 200)
    main_bg = Color.bg(0, 0, 0)
    title = Color.fg(255, 255, 255)
    border = Color.fg(100, 100, 100)
    text = Color.fg(180, 180, 180)
    selected = Color.fg(0, 255, 200)


class Box:
    """Base class for UI boxes"""

    @staticmethod
    def draw(x: int, y: int, w: int, h: int, title: str = "") -> str:
        """Draw a box with optional title"""
        out = []

        # Top border
        out.append(f"\033[{y};{x}f" + Theme.border + "┌")
        if title:
            title_str = f"─┤ {Theme.title}{title}{Theme.border} ├"
            out.append(title_str)
            remaining = w - len(title) - 6
            out.append("─" * remaining)
        else:
            out.append("─" * (w - 2))
        out.append("┐")

        # Sides
        for i in range(1, h - 1):
            out.append(f"\033[{y + i};{x}f│")
            out.append(f"\033[{y + i};{x + w - 1}f│")

        # Bottom border
        out.append(f"\033[{y + h - 1};{x}f└" + "─" * (w - 2) + "┘")

        return "".join(out)


class Graph:
    """Graph drawing for metrics visualization"""

    def __init__(self, width: int, height: int, max_value: int = 100):
        self.width = width
        self.height = height
        self.max_value = max_value
        self.data = deque(maxlen=width)

    def add_value(self, value: float):
        """Add a new value to the graph"""
        self.data.append(min(value, self.max_value))

    def draw(self, x: int, y: int, gradient: List[Tuple[int, int, int]]) -> str:
        """Draw the graph at position x, y with nice dot style"""
        out = []

        # Fill with zeros if not enough data
        data_list = list(self.data)
        while len(data_list) < self.width:
            data_list.insert(0, 0)

        # Create matrix for smooth graph
        matrix = [[" " for _ in range(self.width)] for _ in range(self.height)]

        # Plot data points with smoothing
        for col in range(len(data_list)):
            value = data_list[col]
            if value > 0:
                norm_value = min(value / self.max_value, 1.0)
                row = int((1 - norm_value) * (self.height - 1))

                if 0 <= row < self.height and 0 <= col < self.width:
                    # Draw connecting lines for smooth graph
                    if col > 0:
                        prev_value = data_list[col - 1]
                        if prev_value > 0:
                            prev_norm = min(prev_value / self.max_value, 1.0)
                            prev_row = int((1 - prev_norm) * (self.height - 1))

                            # Draw vertical line between points
                            if abs(prev_row - row) > 1:
                                step = 1 if row > prev_row else -1
                                for r in range(prev_row + step, row, step):
                                    if 0 <= r < self.height and 0 <= col < self.width:
                                        matrix[r][col] = "│"

                    # Use dots for actual data points
                    if norm_value > 0.8:
                        matrix[row][col] = "●"
                    elif norm_value > 0.5:
                        matrix[row][col] = "○"
                    else:
                        matrix[row][col] = "·"

        # Render with colors
        for row in range(self.height):
            out.append(f"\033[{y + row};{x}f")
            for col in range(self.width):
                if matrix[row][col] != " ":
                    # Calculate color based on height position
                    height_ratio = 1 - (row / (self.height - 1))
                    color = Color.gradient(height_ratio, gradient)
                    out.append(color + matrix[row][col])
                else:
                    out.append(" ")
            out.append(Term.normal)

        return "".join(out)


class ClockGraph:
    """Multi-clock frequency graph"""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.clock_data = {}  # Dictionary of clock_type: deque
        self.clock_ranges = {}  # Min/max frequencies for each clock

    def add_values(self, clocks: Dict[str, float], clock_states: Dict[str, List]):
        """Add clock values"""
        # First pass: collect all clocks and determine global range
        all_freqs = list(clocks.values())
        if all_freqs:
            global_min = 0
            global_max = max(all_freqs) * 1.1  # Give some headroom
        else:
            global_min, global_max = 0, 3000  # Default range

        for clock_type, freq in clocks.items():
            if clock_type not in self.clock_data:
                self.clock_data[clock_type] = deque(maxlen=self.width)

                # Use global range for all clocks to ensure proper relative positioning
                if clock_type in clock_states and clock_states[clock_type]:
                    freqs = [state[1] for state in clock_states[clock_type]]
                    self.clock_ranges[clock_type] = (min(freqs), max(freqs))
                else:
                    # Use global range so all clocks appear at correct relative heights
                    self.clock_ranges[clock_type] = (global_min, global_max)

            self.clock_data[clock_type].append(freq)

    def draw(self, x: int, y: int) -> str:
        """Draw multi-clock graph"""
        out = []

        # Define colors for different clocks
        clock_colors = {
            "sclk": (255, 100, 0),  # Orange - GPU Core
            "mclk": (0, 150, 255),  # Blue - Memory
            "fclk": (0, 255, 150),  # Green - Fabric
            "socclk": (255, 0, 255),  # Magenta - SoC
            "gpu": (255, 100, 0),  # Orange - NVIDIA GPU
            "memory": (0, 150, 255),  # Blue - Memory
            "graphics": (255, 100, 0),  # Orange - Graphics (AMD)
        }

        clock_labels = {
            "sclk": "C",
            "mclk": "M",
            "fclk": "F",
            "socclk": "S",
            "gpu": "G",
            "memory": "M",
            "graphics": "G",
        }

        # Create a 2D grid
        grid = [[" " for _ in range(self.width)] for _ in range(self.height)]
        grid_colors = [[None for _ in range(self.width)] for _ in range(self.height)]

        # Plot each clock's data
        for clock_type, data in self.clock_data.items():
            if clock_type not in self.clock_ranges:
                continue

            min_freq, max_freq = self.clock_ranges[clock_type]
            freq_range = max_freq - min_freq
            if freq_range <= 0:
                continue

            data_list = list(data)
            # Pad with first value if we have data, otherwise min
            if data_list:
                pad_value = data_list[0]
            else:
                pad_value = min_freq

            while len(data_list) < self.width:
                data_list.insert(0, pad_value)

            for col, freq in enumerate(data_list):
                if col < self.width:
                    # Normalize frequency to 0-1 range
                    norm_freq = (freq - min_freq) / freq_range
                    # Calculate position with proper scaling
                    graph_height = norm_freq * (self.height - 1)
                    row_from_top = self.height - 1 - int(graph_height)

                    if row_from_top < 0:
                        row_from_top = 0
                    elif row_from_top >= self.height:
                        row_from_top = self.height - 1

                    # Draw transitions between states
                    if col > 0:
                        prev_freq = data_list[col - 1]
                        if prev_freq != freq:
                            # Draw vertical line for transition
                            prev_norm = (prev_freq - min_freq) / freq_range
                            prev_row = (
                                self.height - 1 - int(prev_norm * (self.height - 1))
                            )

                            min_row = min(row_from_top, prev_row)
                            max_row = max(row_from_top, prev_row)

                            for r in range(min_row, max_row + 1):
                                if 0 <= r < self.height and grid[r][col] == " ":
                                    grid[r][col] = "│"
                                    grid_colors[r][col] = clock_colors.get(
                                        clock_type, (200, 200, 200)
                                    )

                    # Draw the dot for current value - use different chars for different clocks
                    clock_chars = {
                        "graphics": "●",
                        "sclk": "●",
                        "gpu": "●",  # Main GPU clock
                        "memory": "■",
                        "mclk": "■",  # Memory clock
                        "fclk": "♦",  # Fabric clock (more visible)
                        "socclk": "▲",  # SoC clock
                    }
                    char = clock_chars.get(clock_type, "·")

                    # Always place the clock symbol, try adjacent positions if occupied
                    placed = False
                    if grid[row_from_top][col] == " ":
                        # Primary position is free
                        grid[row_from_top][col] = char
                        grid_colors[row_from_top][col] = clock_colors.get(
                            clock_type, (200, 200, 200)
                        )
                        placed = True
                    else:
                        # Try adjacent positions
                        offset_order = (
                            [-1, 1, -2, 2] if clock_type == "fclk" else [1, -1, 2, -2]
                        )
                        for offset in offset_order:
                            adj_row = row_from_top + offset
                            if 0 <= adj_row < self.height and grid[adj_row][col] == " ":
                                grid[adj_row][col] = char
                                grid_colors[adj_row][col] = clock_colors.get(
                                    clock_type, (200, 200, 200)
                                )
                                placed = True
                                break

                    # If still not placed, force overwrite at original position
                    if not placed:
                        grid[row_from_top][col] = char
                        grid_colors[row_from_top][col] = clock_colors.get(
                            clock_type, (200, 200, 200)
                        )

        # Draw the graph area
        for row in range(self.height):
            out.append(f"\033[{y + row};{x}f")
            for col in range(self.width):
                if grid[row][col] != " ":
                    color_tuple = grid_colors[row][col]
                    out.append(Color.fg(*color_tuple) + grid[row][col])
                else:
                    out.append(" ")

        # Draw legend at the bottom
        legend_y = y + self.height + 1
        legend_items = []
        for clock_type in self.clock_data.keys():
            if clock_type in clock_colors:
                color_tuple = clock_colors[clock_type]
                label = clock_labels.get(clock_type, clock_type)
                if self.clock_data[clock_type]:
                    latest_freq = list(self.clock_data[clock_type])[-1]
                    legend_items.append(
                        f"{Color.fg(*color_tuple)}• {label}:{latest_freq:.0f}{Term.normal}"
                    )

        if legend_items:
            legend_text = "  ".join(legend_items)
            out.append(f"\033[{legend_y};{x}f{legend_text}")

        return "".join(out)


class TemperatureGraph:
    """Multi-sensor temperature graph"""

    def __init__(self, width: int, height: int, max_value: int = 150):
        self.width = width
        self.height = height
        self.max_value = max_value
        self.sensor_data = {}  # Dictionary of sensor_name: deque
        self.limits = {}  # Dictionary of sensor_name: {critical: val, emergency: val}

    def add_values(
        self, temperatures: Dict[str, float], limits: Dict[str, Dict[str, float]] = None
    ):
        """Add temperature values for all sensors"""
        for sensor, temp in temperatures.items():
            if sensor not in self.sensor_data:
                self.sensor_data[sensor] = deque(maxlen=self.width)
            self.sensor_data[sensor].append(min(temp, self.max_value))

        # Update limits if provided
        if limits:
            self.limits = limits

    def draw(self, x: int, y: int) -> str:
        """Draw multi-sensor temperature graph"""
        out = []

        # Define colors for different sensors - support both AMD and NVIDIA names
        sensor_colors = {
            # AMD sensors
            "Edge": (0, 150, 255),
            "Junction": (255, 100, 0),
            "Memory": (0, 255, 150),
            "Hotspot": (255, 0, 100),
            # NVIDIA sensors
            "GPU": (255, 100, 0),
            "CPU": (0, 150, 255),
            "PMIC": (0, 255, 150),
            "AO": (255, 0, 100),
            "PLL": (200, 200, 200),
        }

        # Create a 2D grid to represent the graph
        grid = [[" " for _ in range(self.width)] for _ in range(self.height)]
        grid_colors = [[None for _ in range(self.width)] for _ in range(self.height)]

        # Plot each sensor's data
        sensor_index = 0
        for sensor_name, data in self.sensor_data.items():
            data_list = list(data)
            while len(data_list) < self.width:
                data_list.insert(0, 0)

            for col, value in enumerate(data_list):
                if value > 0 and col < self.width:
                    # Calculate which row this value should appear on
                    graph_height = (value / self.max_value) * self.height
                    row_from_top = self.height - int(graph_height)

                    # Ensure we're within bounds
                    if row_from_top < 0:
                        row_from_top = 0
                    elif row_from_top >= self.height:
                        row_from_top = self.height - 1

                    # Use smallest dot for all sensors
                    dot_char = "·"

                    # Try to place the dot, if position is taken, try adjacent rows
                    placed = False
                    for offset in [0, -1, 1]:  # Try current row, then above, then below
                        target_row = row_from_top + offset
                        if 0 <= target_row < self.height:
                            if grid[target_row][col] == " ":
                                grid[target_row][col] = dot_char
                                color_tuple = sensor_colors.get(
                                    sensor_name, (200, 200, 200)
                                )
                                grid_colors[target_row][col] = color_tuple
                                placed = True
                                break

                    # If we couldn't place it nearby, force it at original position
                    if not placed:
                        grid[row_from_top][col] = dot_char
                        color_tuple = sensor_colors.get(sensor_name, (200, 200, 200))
                        grid_colors[row_from_top][col] = color_tuple

            sensor_index += 1

        # Draw the graph area
        for row in range(self.height):
            out.append(f"\033[{y + row};{x}f")
            for col in range(self.width):
                if grid[row][col] != " ":
                    color_tuple = grid_colors[row][col]
                    out.append(Color.fg(*color_tuple) + grid[row][col])
                else:
                    out.append(" ")

        # Draw legend at the bottom
        legend_y = y + self.height + 1
        legend_items = []
        for sensor_name in self.sensor_data.keys():
            if sensor_name in sensor_colors:
                color_tuple = sensor_colors[sensor_name]
                if self.sensor_data[sensor_name]:
                    latest_temp = list(self.sensor_data[sensor_name])[-1]
                    legend_items.append(
                        f"{Color.fg(*color_tuple)}• {sensor_name}: {latest_temp:.0f}°C{Term.normal}"
                    )

        if legend_items:
            legend_text = "  ".join(legend_items)
            out.append(f"\033[{legend_y};{x}f{legend_text}")

        return "".join(out)


class GPUTop:
    """Main application class"""

    def __init__(self):
        self.running = True
        self.gpu_monitor = GPUMonitor()
        self.selected_gpu = 0
        self.update_interval = 1.0  # seconds

        # Graphs for historical data
        self.util_graph = None
        self.mem_graph = None
        self.temp_graph = None  # Now a TemperatureGraph
        self.power_graph = None
        self.clock_graph = None  # Clock frequency graph
        self.fan_graph = None  # Fan speed graph

        # Stats history
        self.stats_history = deque(maxlen=60)  # Keep 60 seconds of history

    def init_display(self):
        """Initialize terminal display"""
        print(Term.alt_screen + Term.hide_cursor + Term.clear)
        Term.refresh()

        # Initialize graphs based on terminal size
        graph_width = min(60, Term.width - 10)
        graph_height = 8

        self.util_graph = Graph(graph_width, graph_height, 100)
        self.mem_graph = Graph(graph_width, graph_height, 100)
        self.temp_graph = TemperatureGraph(
            graph_width, graph_height, 150
        )  # Multi-sensor temp graph

        # Adjust power graph scale based on GPU type
        if self.gpu_monitor.gpu_type == "nvidia_jetson":
            self.power_graph = Graph(
                graph_width, graph_height, 10
            )  # Jetson uses less power
        else:
            self.power_graph = Graph(graph_width, graph_height, 300)  # Desktop GPUs

        self.clock_graph = ClockGraph(
            graph_width, graph_height
        )  # Clock frequency graph
        self.fan_graph = Graph(graph_width, graph_height, 100)  # Fan speed graph

    def cleanup(self):
        """Cleanup terminal on exit"""
        self.gpu_monitor.cleanup()
        print(Term.normal_screen + Term.show_cursor + Term.normal)

    def draw_header(self):
        """Draw the header with title and GPU selection"""
        out = []

        # Title banner with GPU type indicator
        vendor_text = ""
        if self.gpu_monitor.gpu_type:
            if "nvidia" in self.gpu_monitor.gpu_type:
                vendor_text = " (NVIDIA)"
            elif self.gpu_monitor.gpu_type == "amd":
                vendor_text = " (AMD)"

        title = f"╔═╗╔═╗╦ ╦  ╔╦╗╔═╗╔═╗{vendor_text}"
        title2 = "║ ╦╠═╝║ ║   ║ ║ ║╠═╝"
        title3 = "╚═╝╩  ╚═╝   ╩ ╚═╝╩"

        x = (Term.width - len(title)) // 2
        y = 2

        out.append(f"\033[{y};{x}f" + Color.fg(0, 255, 200) + Term.bold + title)
        out.append(f"\033[{y+1};{x}f" + Color.fg(0, 200, 255) + title2)
        out.append(f"\033[{y+2};{x}f" + Color.fg(0, 150, 255) + title3)
        out.append(Term.unbold + Term.normal)

        # GPU selector
        if len(self.gpu_monitor.gpus) > 1:
            y = 6
            out.append(f"\033[{y};3f" + Theme.text + "Select GPU: ")
            for i in range(len(self.gpu_monitor.gpus)):
                if i == self.selected_gpu:
                    out.append(Theme.selected + f"[{i}]" + Theme.text)
                else:
                    out.append(f" {i} ")

        return "".join(out)

    def draw_stats(self, stats: Dict[str, Any]):
        """Draw current statistics"""
        out = []
        y_offset = 8

        # GPU Name
        out.append(
            f"\033[{y_offset};3f" + Theme.title + f"GPU: {stats['name']}" + Term.normal
        )
        y_offset += 2

        # Current values box - make it taller to accommodate more temps
        box_y = y_offset
        box_height = 10 + len(stats.get("temperatures", {}))
        out.append(Box.draw(2, box_y, 45, box_height, "Current Values"))

        line = 2

        # Utilization
        util_color = Color.gradient(stats["utilization"] / 100, Theme.gpu_gradient)
        out.append(
            f"\033[{box_y + line};4f"
            + Theme.text
            + "Utilization: "
            + util_color
            + f"{stats['utilization']:5.1f}%"
            + Term.normal
        )
        line += 1

        # Memory
        mem_color = Color.gradient(stats["memory_percent"] / 100, Theme.mem_gradient)
        out.append(
            f"\033[{box_y + line};4f"
            + Theme.text
            + "Memory:      "
            + mem_color
            + f"{stats['memory_used']:5.0f}/{stats['memory_total']:.0f} MB ({stats['memory_percent']:.1f}%)"
            + Term.normal
        )
        line += 1

        # Temperature sensors (multiple)
        if stats.get("temperatures"):
            out.append(
                f"\033[{box_y + line};4f" + Theme.text + "Temperatures:" + Term.normal
            )
            line += 1

            for sensor_name, temp_value in sorted(stats["temperatures"].items()):
                temp_normalized = min(temp_value / 90, 1.0)  # Normalize to 90°C max
                temp_color = Color.gradient(temp_normalized, Theme.temp_gradient)

                # Check if this sensor has limits (AMD only)
                limits_str = ""
                if sensor_name in stats.get("temp_limits", {}):
                    limits = stats["temp_limits"][sensor_name]
                    if "critical" in limits:
                        limits_str += f" (C:{limits['critical']:.0f}°"
                    if "emergency" in limits:
                        if limits_str:
                            limits_str += f" E:{limits['emergency']:.0f}°)"
                        else:
                            limits_str += f" (E:{limits['emergency']:.0f}°)"
                    if limits_str and not limits_str.endswith(")"):
                        limits_str += ")"

                out.append(
                    f"\033[{box_y + line};6f"
                    + Theme.text
                    + f"  {sensor_name:10s}: "
                    + temp_color
                    + f"{temp_value:5.1f}°C"
                    + Theme.text
                    + limits_str
                    + Term.normal
                )
                line += 1

        # Power
        if stats["power"] > 0:
            if stats["power_limit"] > 0:
                power_percent = stats["power"] / stats["power_limit"]
                power_color = Color.gradient(power_percent, Theme.gpu_gradient)
                out.append(
                    f"\033[{box_y + line};4f"
                    + Theme.text
                    + "Power:       "
                    + power_color
                    + f"{stats['power']:5.1f}/{stats['power_limit']:.0f} W"
                    + Term.normal
                )
            else:
                out.append(
                    f"\033[{box_y + line};4f"
                    + Theme.text
                    + "Power:       "
                    + Color.fg(200, 200, 0)
                    + f"{stats['power']:5.1f} W"
                    + Term.normal
                )
            line += 1

        # Fan Speed
        if stats["fan_speed"] > 0:
            fan_color = Color.gradient(stats["fan_speed"] / 100, Theme.gpu_gradient)
            out.append(
                f"\033[{box_y + line};4f"
                + Theme.text
                + "Fan Speed:   "
                + fan_color
                + f"{stats['fan_speed']:5.0f}%"
                + Term.normal
            )
            line += 1

        # Clock frequencies
        if stats.get("clocks"):
            out.append(
                f"\033[{box_y + line};4f" + Theme.text + "Clock Speeds:" + Term.normal
            )
            line += 1

            clock_labels = {
                "sclk": "Core",
                "mclk": "Memory",
                "fclk": "Fabric",
                "socclk": "SoC",
                "gpu": "GPU",
                "memory": "Memory",
                "graphics": "Graphics",  # Add graphics mapping
            }

            # Display clocks 2 per line to fit in box
            available_clocks = list(stats["clocks"].keys())
            clock_pairs = []
            for i in range(0, len(available_clocks), 2):
                pair = available_clocks[i : i + 2]
                clock_pairs.append(pair)

            for pair in clock_pairs:
                clock_parts = []
                for clock_type in pair:
                    if clock_type in stats["clocks"]:
                        freq = stats["clocks"][clock_type]
                        label = clock_labels.get(clock_type, clock_type)

                        # Get min/max from states to show relative position
                        if clock_type in stats.get("clock_states", {}):
                            states = stats["clock_states"][clock_type]
                            if states:
                                freqs = [s[1] for s in states]
                                min_freq, max_freq = min(freqs), max(freqs)
                                if max_freq > min_freq:
                                    rel_pos = (freq - min_freq) / (max_freq - min_freq)
                                    color = Color.gradient(rel_pos, Theme.gpu_gradient)
                                else:
                                    color = Color.fg(200, 200, 0)
                            else:
                                color = Color.fg(200, 200, 0)
                        else:
                            color = Color.fg(200, 200, 0)

                        clock_parts.append(
                            f"{label:7s}:" + color + f"{freq:4.0f}" + Theme.text + "M"
                        )

                if clock_parts:
                    # Build complete line with positioning and all clock parts
                    if len(clock_parts) == 1:
                        clock_line = (
                            f"\033[{box_y + line};6f"
                            + Theme.text
                            + f"  {clock_parts[0]}"
                        )
                    else:
                        clock_line = (
                            f"\033[{box_y + line};6f"
                            + Theme.text
                            + f"  {clock_parts[0]}  {clock_parts[1]}"
                        )

                    out.append(clock_line + Term.normal)
                    line += 1

        # Performance level (AMD only)
        if stats.get("performance_level") and stats["performance_level"] != "unknown":
            out.append(
                f"\033[{box_y + line};4f"
                + Theme.text
                + "Perf Level:  "
                + Color.fg(100, 200, 255)
                + f"{stats['performance_level']}   "
                + Term.normal
            )

        return "".join(out)

    def draw_graphs(self, stats: Dict[str, Any]):
        """Draw performance graphs"""
        out = []

        # Add current values to graphs
        self.util_graph.add_value(stats["utilization"])
        self.mem_graph.add_value(stats["memory_percent"])

        # Add temperature values (multi-sensor)
        if stats.get("temperatures"):
            self.temp_graph.add_values(
                stats["temperatures"], stats.get("temp_limits", {})
            )

        self.power_graph.add_value(stats["power"])
        self.fan_graph.add_value(stats["fan_speed"])

        # Add clock values
        if stats.get("clocks"):
            # Use empty clock_states if not available
            clock_states = stats.get("clock_states", {})
            self.clock_graph.add_values(stats["clocks"], clock_states)

        # Layout: Center column for main metrics, right column for clocks and power
        center_x = 50
        right_x = 120  # Right column position (adjusted for terminal width)
        graph_spacing = 10

        # CENTER COLUMN - Main metrics
        # GPU Utilization Graph
        y = 8
        out.append(
            Box.draw(
                center_x,
                y,
                self.util_graph.width + 4,
                self.util_graph.height + 3,
                "GPU Utilization %",
            )
        )
        out.append(self.util_graph.draw(center_x + 2, y + 1, Theme.gpu_gradient))

        # Memory Usage Graph
        y += graph_spacing
        out.append(
            Box.draw(
                center_x,
                y,
                self.mem_graph.width + 4,
                self.mem_graph.height + 3,
                "Memory %",
            )
        )
        out.append(self.mem_graph.draw(center_x + 2, y + 1, Theme.mem_gradient))

        # Temperature Graph
        y += graph_spacing
        if y + self.temp_graph.height + 4 < Term.height:
            out.append(
                Box.draw(
                    center_x,
                    y,
                    self.temp_graph.width + 4,
                    self.temp_graph.height + 4,  # Extra space for legend
                    "Temperature °C",
                )
            )
            out.append(self.temp_graph.draw(center_x + 2, y + 1))

        # RIGHT COLUMN - Secondary metrics
        if Term.width > 140:
            # Clock Frequency Graph
            y = 8
            out.append(
                Box.draw(
                    right_x,
                    y,
                    45,
                    self.clock_graph.height + 4,  # Extra space for legend
                    "Clock Frequencies",
                )
            )
            out.append(self.clock_graph.draw(right_x + 2, y + 1))

            # Power Graph
            y += self.clock_graph.height + 6
            if y + self.power_graph.height + 3 < Term.height:
                out.append(
                    Box.draw(right_x, y, 45, self.power_graph.height + 3, "Power (W)")
                )
                power_small = Graph(41, self.power_graph.height, 300)
                power_small.data = self.power_graph.data
                out.append(power_small.draw(right_x + 2, y + 1, Theme.gpu_gradient))

            # Fan Speed Graph
            y += self.power_graph.height + 4
            if y + self.fan_graph.height + 3 < Term.height:
                out.append(
                    Box.draw(right_x, y, 45, self.fan_graph.height + 3, "Fan Speed %")
                )
                fan_small = Graph(41, self.fan_graph.height, 100)
                fan_small.data = self.fan_graph.data
                out.append(fan_small.draw(right_x + 2, y + 1, Theme.gpu_gradient))

        return "".join(out)

    def draw_footer(self):
        """Draw footer with controls"""
        out = []
        y = Term.height - 2
        footer_text = "Press 'q' to quit"
        if len(self.gpu_monitor.gpus) > 1:
            footer_text += " | Use number keys to select GPU"

        x = (Term.width - len(footer_text)) // 2
        out.append(f"\033[{y};{x}f" + Theme.text + footer_text + Term.normal)
        return "".join(out)

    def display(self):
        """Main display update"""
        out = []

        # Clear screen first
        out.append(Term.clear)

        # Draw all components
        out.append(self.draw_header())

        # Get GPU stats
        stats = self.gpu_monitor.get_gpu_stats(self.selected_gpu)

        if stats and stats.get("available"):
            # Convert memory to MB for display consistency
            if "memory_used" in stats and stats["memory_used"] < 100:
                # Assume it's in GB, convert to MB
                stats["memory_used"] = stats["memory_used"] * 1024
                stats["memory_total"] = stats["memory_total"] * 1024

            # Convert single temperature to dict format if needed
            if "temperature" in stats and not isinstance(
                stats.get("temperatures"), dict
            ):
                stats["temperatures"] = {"GPU": stats["temperature"]}
            elif not stats.get("temperatures"):
                stats["temperatures"] = {}

            # Ensure other required fields
            if "temp_limits" not in stats:
                stats["temp_limits"] = {}
            if "clock_states" not in stats:
                stats["clock_states"] = {}
            if "clocks" not in stats:
                stats["clocks"] = {}
            if "performance_level" not in stats:
                stats["performance_level"] = "unknown"

            # Draw stats and graphs
            out.append(self.draw_stats(stats))
            out.append(self.draw_graphs(stats))

        out.append(self.draw_footer())

        # Print everything at once
        print("".join(out), end="", flush=True)

    def monitor_live(self, interval: int = 1):
        """Monitor GPUs live with updates - compatible with view.py interface"""
        self.update_interval = interval
        self.run()

    def _check_keyboard_input(self):
        """Check for keyboard input (non-blocking)"""
        try:
            if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                key = sys.stdin.read(1)
                if key.lower() == "q":
                    self.running = False
                    return True
                elif ord(key) == 3:  # Ctrl+C
                    self.running = False
                    return True
                elif key.isdigit():
                    gpu_num = int(key)
                    if 0 <= gpu_num < len(self.gpu_monitor.gpus):
                        self.selected_gpu = gpu_num
        except:
            pass
        return False

    def run(self):
        """Main run loop"""
        self.init_display()

        # Set terminal to raw mode for immediate key detection
        old_settings = None
        raw_mode_enabled = False
        try:
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())
            raw_mode_enabled = True
        except:
            # If raw mode fails, continue without it
            pass

        def signal_handler(sig, frame):
            self.running = False
            if raw_mode_enabled and old_settings:
                try:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                except:
                    pass
            self.cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            while self.running:
                Term.refresh()
                self.display()

                # Check for key presses with timeout (only if raw mode enabled)
                if raw_mode_enabled:
                    for _ in range(
                        int(self.update_interval * 10)
                    ):  # Check 10 times per second
                        if self._check_keyboard_input():
                            break
                        try:
                            sleep(0.1)
                        except KeyboardInterrupt:
                            self.running = False
                            break
                else:
                    try:
                        sleep(self.update_interval)
                    except KeyboardInterrupt:
                        self.running = False
                        break

        except KeyboardInterrupt:
            pass
        finally:
            if raw_mode_enabled and old_settings:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            self.cleanup()


def main():
    """Main entry point"""
    app = GPUTop()
    app.run()


if __name__ == "__main__":
    main()
