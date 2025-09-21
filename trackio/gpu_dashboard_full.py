#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# indent = tab
# tab-size = 4

import os, sys, threading, signal, subprocess
from time import time, sleep, strftime
from typing import List, Dict, Tuple, Union, Any
from collections import deque
from math import ceil
import fcntl, termios, tty
from select import select
import argparse
import json
from datetime import datetime
from pathlib import Path
import glob
import re

# Try to import matplotlib for graph generation
try:
    import matplotlib

    matplotlib.use("Agg")  # Use non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

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
        """Draw the graph at position x, y"""
        out = []

        # Fill with zeros if not enough data
        data_list = list(self.data)
        while len(data_list) < self.width:
            data_list.insert(0, 0)

        # Create a 2D grid to represent the graph
        grid = [[" " for _ in range(self.width)] for _ in range(self.height)]

        # Plot each data point as a small dot
        for col, value in enumerate(data_list):
            # Calculate which row this value should appear on
            graph_height = (value / self.max_value) * self.height
            row_from_top = self.height - int(graph_height)

            # Ensure we're within bounds
            if row_from_top < 0:
                row_from_top = 0
            elif row_from_top >= self.height:
                row_from_top = self.height - 1

            # Use small dot character
            grid[row_from_top][col] = "·"

        # Render the grid with colors
        for row in range(self.height):
            out.append(f"\033[{y + row};{x}f")
            for col in range(self.width):
                if grid[row][col] != " ":
                    # Calculate value for this position for coloring
                    value = data_list[col] if col < len(data_list) else 0
                    color = Color.gradient(value / self.max_value, gradient)
                    out.append(color + grid[row][col])
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
        for clock_type, freq in clocks.items():
            if clock_type not in self.clock_data:
                self.clock_data[clock_type] = deque(maxlen=self.width)
                # Get min/max from available states
                if clock_type in clock_states and clock_states[clock_type]:
                    freqs = [state[1] for state in clock_states[clock_type]]
                    self.clock_ranges[clock_type] = (min(freqs), max(freqs))
                else:
                    self.clock_ranges[clock_type] = (0, freq * 1.2)

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
            "memory": (0, 150, 255),  # Blue - NVIDIA Memory
        }

        clock_labels = {
            "sclk": "Core",
            "mclk": "Mem",
            "fclk": "Fabric",
            "socclk": "SoC",
            "gpu": "GPU",
            "memory": "Memory",
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

                    # Use smallest dot for all clocks
                    dot_char = "·"

                    # Try to place the dot, if position is taken, try adjacent rows
                    placed = False
                    for offset in [0, -1, 1, -2, 2]:  # Try current, then nearby rows
                        target_row = row_from_top + offset
                        if 0 <= target_row < self.height:
                            if grid[target_row][col] in [" ", "│"]:
                                grid[target_row][col] = dot_char
                                color_tuple = clock_colors.get(
                                    clock_type, (200, 200, 200)
                                )
                                grid_colors[target_row][col] = color_tuple
                                placed = True
                                break

                    # If we couldn't place it nearby, force it at original position
                    if not placed:
                        grid[row_from_top][col] = dot_char
                        color_tuple = clock_colors.get(clock_type, (200, 200, 200))
                        grid_colors[row_from_top][col] = color_tuple

        # Draw the graph
        for row in range(self.height):
            out.append(f"\033[{y + row};{x}f")
            for col in range(self.width):
                if grid[row][col] != " ":
                    color_tuple = grid_colors[row][col]
                    out.append(Color.fg(*color_tuple) + grid[row][col])
                else:
                    out.append(" ")
            out.append(Term.normal)

        # Draw legend
        legend_y = y + self.height + 1
        legend_items = []
        for clock_type in ["sclk", "mclk", "fclk", "socclk", "gpu", "memory"]:
            if clock_type in self.clock_data and self.clock_data[clock_type]:
                latest_freq = list(self.clock_data[clock_type])[-1]
                color_tuple = clock_colors.get(clock_type, (200, 200, 200))
                label = clock_labels.get(clock_type, clock_type)
                legend_items.append(
                    f"{Color.fg(*color_tuple)}· {label}: {latest_freq}MHz{Term.normal}"
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

            # End of row
            out.append(Term.normal)

        # Draw legend below the graph
        legend_y = y + self.height + 1
        legend_items = []
        for sensor_name in sorted(self.sensor_data.keys()):
            if sensor_name in sensor_colors:
                color_tuple = sensor_colors[sensor_name]
                if sensor_name in self.sensor_data and self.sensor_data[sensor_name]:
                    latest_temp = list(self.sensor_data[sensor_name])[-1]
                    legend_items.append(
                        f"{Color.fg(*color_tuple)}• {sensor_name}: {latest_temp:.0f}°C{Term.normal}"
                    )

        if legend_items:
            legend_text = "  ".join(legend_items)
            out.append(f"\033[{legend_y};{x}f{legend_text}")

        return "".join(out)


class GPUMonitor:
    """Unified GPU monitoring for AMD and NVIDIA GPUs"""

    def __init__(self):
        self.gpu_count = 0
        self.gpus = []
        self.initialized = False
        self.gpu_type = None  # 'amd', 'nvidia_jetson', or 'nvidia_desktop'

        # For NVIDIA Jetson tegrastats monitoring
        self.tegrastats_process = None
        self.tegrastats_data = {}

        # Try to discover GPUs
        self._discover_gpus()

    def _discover_gpus(self):
        """Discover GPUs - try NVIDIA first, then AMD"""
        # First, try NVIDIA Jetson
        if self._discover_nvidia_jetson():
            self.gpu_type = "nvidia_jetson"
            return

        # Try desktop NVIDIA
        if self._discover_nvidia_desktop():
            self.gpu_type = "nvidia_desktop"
            return

        # Finally, try AMD
        if self._discover_amd():
            self.gpu_type = "amd"
            return

    def _discover_nvidia_jetson(self):
        """Discover NVIDIA Jetson GPU"""
        try:
            gpu_load_path = Path("/sys/devices/gpu.0/load")
            if gpu_load_path.exists():
                self.gpus.append(
                    {
                        "index": 0,
                        "name": self._get_jetson_name(),
                        "type": "nvidia_jetson",
                        "load_path": gpu_load_path,
                        "freq_path": Path("/sys/class/devfreq/57000000.gpu/cur_freq"),
                        "available_freqs_path": Path(
                            "/sys/class/devfreq/57000000.gpu/available_frequencies"
                        ),
                    }
                )
                self.gpu_count = 1
                self.initialized = True
                return True
        except:
            pass
        return False

    def _discover_nvidia_desktop(self):
        """Discover desktop NVIDIA GPU using nvidia-ml-py"""
        try:
            import pynvml

            pynvml.nvmlInit()
            self.gpu_count = pynvml.nvmlDeviceGetCount()
            for i in range(self.gpu_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8")
                self.gpus.append(
                    {
                        "index": i,
                        "name": name,
                        "type": "nvidia_desktop",
                        "handle": handle,
                    }
                )
            self.initialized = True
            return True
        except:
            pass
        return False

    def _discover_amd(self):
        """Discover AMD GPUs through /sys/class/drm"""
        try:
            drm_path = Path("/sys/class/drm")
            for card_path in sorted(drm_path.glob("card[0-9]*")):
                # Skip render nodes
                if "render" in card_path.name:
                    continue

                # Check if this is a real GPU (has device subdirectory)
                device_path = card_path / "device"
                if not device_path.exists():
                    continue

                # Check if it's an AMD GPU
                vendor_path = device_path / "vendor"
                if vendor_path.exists():
                    with open(vendor_path, "r") as f:
                        vendor = f.read().strip()
                        if vendor != "0x1002":  # AMD vendor ID
                            continue

                # Find hwmon directory
                hwmon_base = device_path / "hwmon"
                if not hwmon_base.exists():
                    continue

                hwmon_dirs = list(hwmon_base.glob("hwmon*"))
                if not hwmon_dirs:
                    continue

                hwmon_path = hwmon_dirs[0]

                # Get GPU name from device
                gpu_name = self._get_amd_gpu_name(device_path)

                # Extract card number
                card_num = int(card_path.name.replace("card", ""))

                self.gpus.append(
                    {
                        "index": card_num,
                        "name": gpu_name,
                        "type": "amd",
                        "device_path": device_path,
                        "hwmon_path": hwmon_path,
                        "card_path": card_path,
                    }
                )

            self.gpu_count = len(self.gpus)
            if self.gpu_count > 0:
                self.initialized = True
                return True
        except Exception as e:
            pass
        return False

    def _get_jetson_name(self):
        """Get GPU name for Jetson device"""
        try:
            with open("/proc/device-tree/model", "r") as f:
                model = f.read().strip()
                if "Nano" in model:
                    return "NVIDIA Jetson Nano GPU"
                elif "Xavier" in model:
                    return "NVIDIA Jetson Xavier GPU"
                elif "Orin" in model:
                    return "NVIDIA Jetson Orin GPU"
                elif "TX2" in model:
                    return "NVIDIA Jetson TX2 GPU"
                elif "TX1" in model:
                    return "NVIDIA Jetson TX1 GPU"
            return "NVIDIA Jetson GPU"
        except:
            return "NVIDIA GPU"

    def _get_amd_gpu_name(self, device_path):
        """Get AMD GPU name from device information"""
        try:
            device_id_path = device_path / "device"
            if device_id_path.exists():
                with open(device_id_path, "r") as f:
                    device_id = f.read().strip()

                # Map known AMD GPU device IDs
                amd_gpus = {
                    "0x66a1": "AMD Radeon Pro VII/MI50",
                    "0x66a0": "AMD Radeon Instinct MI50",
                    "0x66af": "AMD Radeon VII",
                    "0x738c": "AMD Instinct MI100",
                    "0x740c": "AMD Instinct MI210",
                    "0x740f": "AMD Instinct MI250X",
                    "0x73ff": "AMD Radeon RX 6900 XT",
                    "0x73bf": "AMD Radeon RX 6900 XT",
                    "0x73df": "AMD Radeon RX 6750 XT",
                    "0x744c": "AMD Radeon RX 7900 XTX",
                    "0x745f": "AMD Radeon RX 7900 XT",
                    "0x7448": "AMD Radeon Pro W7900",
                }
                return amd_gpus.get(device_id, f"AMD GPU ({device_id})")
            return "AMD GPU"
        except:
            return "Unknown AMD GPU"

    def _parse_tegrastats_line(self, line):
        """Parse a line from tegrastats output"""
        data = {}

        # Parse GR3D_FREQ (GPU utilization and frequency)
        gr3d_match = re.search(r"GR3D_FREQ (\d+)%@(\d+)", line)
        if gr3d_match:
            data["gpu_util"] = float(gr3d_match.group(1))
            data["gpu_freq"] = float(gr3d_match.group(2))

        # Parse temperatures
        temp_patterns = {
            "GPU": r"GPU@([\d.]+)C",
            "CPU": r"CPU@([\d.]+)C",
            "PMIC": r"PMIC@([\d.]+)C",
            "AO": r"AO@([\d.]+)C",
            "PLL": r"PLL@([\d.]+)C",
        }

        temperatures = {}
        for name, pattern in temp_patterns.items():
            match = re.search(pattern, line)
            if match:
                temperatures[name] = float(match.group(1))
        data["temperatures"] = temperatures

        # Parse RAM usage
        ram_match = re.search(r"RAM (\d+)/(\d+)MB", line)
        if ram_match:
            data["mem_used"] = float(ram_match.group(1))
            data["mem_total"] = float(ram_match.group(2))

        # Parse power (if available)
        power_match = re.search(r"POM_5V_IN (\d+)/(\d+)", line)
        if power_match:
            data["power"] = float(power_match.group(1)) / 1000.0  # Convert mW to W

        return data

    def _start_tegrastats(self):
        """Start tegrastats process for continuous monitoring"""
        if self.tegrastats_process is None:
            try:
                self.tegrastats_process = subprocess.Popen(
                    ["tegrastats", "--interval", "1000"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    universal_newlines=True,
                )
                # Start a thread to read tegrastats output
                threading.Thread(target=self._read_tegrastats, daemon=True).start()
            except:
                pass

    def _read_tegrastats(self):
        """Read tegrastats output in background"""
        if self.tegrastats_process:
            for line in self.tegrastats_process.stdout:
                self.tegrastats_data = self._parse_tegrastats_line(line)

    def get_stats(self, gpu_index: int = 0) -> Dict[str, Any]:
        """Get GPU statistics"""
        if not self.initialized or gpu_index >= self.gpu_count:
            return {
                "utilization": 0,
                "memory_used": 0,
                "memory_total": 0,
                "memory_percent": 0,
                "temperatures": {},
                "temp_limits": {},
                "power": 0,
                "power_limit": 0,
                "fan_speed": 0,
                "clocks": {},
                "clock_states": {},
                "performance_level": "",
                "name": "No GPU",
            }

        gpu = self.gpus[gpu_index]

        if gpu["type"] == "nvidia_jetson":
            return self._get_nvidia_jetson_stats(gpu)
        elif gpu["type"] == "nvidia_desktop":
            return self._get_nvidia_desktop_stats(gpu)
        elif gpu["type"] == "amd":
            return self._get_amd_stats(gpu)

    def _get_nvidia_jetson_stats(self, gpu):
        """Get stats for NVIDIA Jetson GPU"""
        stats = {
            "name": gpu["name"],
            "utilization": 0,
            "memory_used": 0,
            "memory_total": 0,
            "memory_percent": 0,
            "temperatures": {},
            "temp_limits": {},
            "power": 0,
            "power_limit": 0,
            "fan_speed": 0,
            "clocks": {},
            "clock_states": {},
            "performance_level": "",
        }

        # Start tegrastats if not running
        self._start_tegrastats()

        # Use tegrastats data if available
        if self.tegrastats_data:
            stats["utilization"] = self.tegrastats_data.get("gpu_util", 0)
            stats["memory_used"] = self.tegrastats_data.get("mem_used", 0)
            stats["memory_total"] = self.tegrastats_data.get("mem_total", 0)
            if stats["memory_total"] > 0:
                stats["memory_percent"] = (
                    stats["memory_used"] / stats["memory_total"]
                ) * 100
            stats["temperatures"] = self.tegrastats_data.get("temperatures", {})
            stats["power"] = self.tegrastats_data.get("power", 0)

            # Add GPU frequency to clocks
            if "gpu_freq" in self.tegrastats_data:
                stats["clocks"]["gpu"] = self.tegrastats_data["gpu_freq"]

        # Fallback to sysfs for some values
        try:
            # GPU load from sysfs - IMPORTANT: Scale by 10 (0-1000 range)
            if gpu["load_path"].exists():
                with open(gpu["load_path"], "r") as f:
                    load_val = f.read().strip()
                    if load_val:
                        # Divide by 10 to convert from 0-1000 to 0-100 range
                        stats["utilization"] = float(load_val) / 10.0

            # GPU frequency from sysfs
            if gpu["freq_path"].exists():
                with open(gpu["freq_path"], "r") as f:
                    freq = float(f.read().strip()) / 1000000  # Convert Hz to MHz
                    stats["clocks"]["gpu"] = freq

            # Available frequencies
            if gpu["available_freqs_path"].exists():
                with open(gpu["available_freqs_path"], "r") as f:
                    freqs = f.read().strip().split()
                    freq_states = [(i, float(f) / 1000000) for i, f in enumerate(freqs)]
                    stats["clock_states"]["gpu"] = freq_states

            # Temperature sensors from thermal zones
            thermal_zones = {
                "/sys/class/thermal/thermal_zone2/temp": "GPU",
                "/sys/class/thermal/thermal_zone1/temp": "CPU",
                "/sys/class/thermal/thermal_zone4/temp": "PMIC",
                "/sys/class/thermal/thermal_zone0/temp": "AO",
                "/sys/class/thermal/thermal_zone3/temp": "PLL",
            }

            if not stats["temperatures"]:  # Only if tegrastats didn't provide temps
                temps = {}
                for path, name in thermal_zones.items():
                    try:
                        with open(path, "r") as f:
                            temp = (
                                float(f.read().strip()) / 1000
                            )  # Convert millidegrees
                            temps[name] = temp
                    except:
                        pass
                stats["temperatures"] = temps

            # Memory from /proc/meminfo if not from tegrastats
            if stats["memory_total"] == 0:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            stats["memory_total"] = (
                                float(line.split()[1]) / 1024
                            )  # KB to MB
                        elif line.startswith("MemAvailable:"):
                            mem_avail = float(line.split()[1]) / 1024
                            stats["memory_used"] = stats["memory_total"] - mem_avail
                            if stats["memory_total"] > 0:
                                stats["memory_percent"] = (
                                    stats["memory_used"] / stats["memory_total"]
                                ) * 100
                            break

        except Exception as e:
            pass

        return stats

    def _get_nvidia_desktop_stats(self, gpu):
        """Get stats for desktop NVIDIA GPU using nvidia-ml-py"""
        stats = {
            "name": gpu["name"],
            "utilization": 0,
            "memory_used": 0,
            "memory_total": 0,
            "memory_percent": 0,
            "temperatures": {},
            "temp_limits": {},
            "power": 0,
            "power_limit": 0,
            "fan_speed": 0,
            "clocks": {},
            "clock_states": {},
            "performance_level": "",
        }

        try:
            import pynvml

            handle = gpu["handle"]

            # Utilization
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            stats["utilization"] = util.gpu

            # Memory
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            stats["memory_used"] = mem_info.used / (1024 * 1024)  # Convert to MB
            stats["memory_total"] = mem_info.total / (1024 * 1024)
            stats["memory_percent"] = (mem_info.used / mem_info.total) * 100

            # Temperature
            try:
                temp = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
                stats["temperatures"]["GPU"] = temp
            except:
                pass

            # Power
            try:
                power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000  # mW to W
                stats["power"] = power
                power_limit = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000
                stats["power_limit"] = power_limit
            except:
                pass

            # Fan speed
            try:
                fan = pynvml.nvmlDeviceGetFanSpeed(handle)
                stats["fan_speed"] = fan
            except:
                pass

            # Clocks
            try:
                graphics_clock = pynvml.nvmlDeviceGetClockInfo(
                    handle, pynvml.NVML_CLOCK_GRAPHICS
                )
                memory_clock = pynvml.nvmlDeviceGetClockInfo(
                    handle, pynvml.NVML_CLOCK_MEM
                )
                stats["clocks"]["gpu"] = graphics_clock
                stats["clocks"]["memory"] = memory_clock
            except:
                pass

        except Exception as e:
            pass

        return stats

    def _read_sysfs_value(self, path, default=0, scale=1):
        """Read a value from sysfs file"""
        try:
            with open(path, "r") as f:
                value = f.read().strip()
                return float(value) / scale
        except:
            return default

    def _parse_dpm_clock_file(self, file_path):
        """Parse a pp_dpm_* clock file to get current state and available states"""
        try:
            if not file_path.exists():
                return None, []

            with open(file_path, "r") as f:
                lines = f.readlines()

            states = []
            current_state = None
            current_freq = None

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Parse lines like "0: 925Mhz *" or "0: 925Mhz"
                is_active = "*" in line
                line = line.replace("*", "").strip()

                parts = line.split(":")
                if len(parts) == 2:
                    state_num = int(parts[0])
                    freq_str = parts[1].strip()

                    # Extract frequency value
                    if "Mhz" in freq_str or "MHz" in freq_str:
                        freq_val = int(
                            freq_str.replace("Mhz", "").replace("MHz", "").strip()
                        )
                        states.append((state_num, freq_val))

                        if is_active:
                            current_state = state_num
                            current_freq = freq_val

            return current_freq, states

        except Exception:
            return None, []

    def _get_performance_level(self, device_path):
        """Get current performance level setting"""
        try:
            perf_level_path = device_path / "power_dpm_force_performance_level"
            if perf_level_path.exists():
                with open(perf_level_path, "r") as f:
                    return f.read().strip()
        except Exception:
            pass
        return "unknown"

    def _get_amd_stats(self, gpu):
        """Get stats for AMD GPU using hwmon"""
        stats = {
            "name": gpu["name"],
            "utilization": 0,
            "memory_used": 0,
            "memory_total": 0,
            "memory_percent": 0,
            "temperatures": {},
            "temp_limits": {},
            "power": 0,
            "power_limit": 0,
            "fan_speed": 0,
            "clocks": {},
            "clock_states": {},
            "performance_level": "",
        }

        device_path = gpu["device_path"]
        hwmon_path = gpu["hwmon_path"]

        # Get GPU utilization from gpu_busy_percent if available
        gpu_busy_path = device_path / "gpu_busy_percent"
        if gpu_busy_path.exists():
            stats["utilization"] = self._read_sysfs_value(gpu_busy_path)

        # Get memory usage
        mem_used_path = device_path / "mem_info_vram_used"
        mem_total_path = device_path / "mem_info_vram_total"

        if mem_used_path.exists() and mem_total_path.exists():
            stats["memory_used"] = self._read_sysfs_value(
                mem_used_path, scale=1024 * 1024
            )  # Convert bytes to MB
            stats["memory_total"] = self._read_sysfs_value(
                mem_total_path, scale=1024 * 1024
            )
            if stats["memory_total"] > 0:
                stats["memory_percent"] = (
                    stats["memory_used"] / stats["memory_total"]
                ) * 100

        # Get all temperature sensors
        temp_sensors = {}
        temp_limits = {}
        temp_sensor_labels = {
            "edge": "Edge",
            "junction": "Junction",
            "mem": "Memory",
            "hotspot": "Hotspot",
        }

        for temp_file in sorted(hwmon_path.glob("temp*_input")):
            sensor_num = temp_file.name.replace("temp", "").replace("_input", "")

            # Get sensor label
            label_file = hwmon_path / f"temp{sensor_num}_label"
            if label_file.exists():
                with open(label_file, "r") as f:
                    label = f.read().strip().lower()
            else:
                label = f"sensor{sensor_num}"

            # Get temperature value (convert from millidegrees)
            temp_value = self._read_sysfs_value(temp_file, scale=1000)

            # Get human-friendly label
            friendly_label = temp_sensor_labels.get(label, label.capitalize())
            temp_sensors[friendly_label] = temp_value

            # Get temperature limits for this sensor
            limits = {}

            # Critical temperature
            crit_file = hwmon_path / f"temp{sensor_num}_crit"
            if crit_file.exists():
                limits["critical"] = self._read_sysfs_value(crit_file, scale=1000)

            # Emergency temperature
            emerg_file = hwmon_path / f"temp{sensor_num}_emergency"
            if emerg_file.exists():
                limits["emergency"] = self._read_sysfs_value(emerg_file, scale=1000)

            # Max temperature
            max_file = hwmon_path / f"temp{sensor_num}_max"
            if max_file.exists():
                limits["max"] = self._read_sysfs_value(max_file, scale=1000)

            if limits:
                temp_limits[friendly_label] = limits

        stats["temperatures"] = temp_sensors
        stats["temp_limits"] = temp_limits

        # Get power consumption
        power1_input = hwmon_path / "power1_average"
        if not power1_input.exists():
            power1_input = hwmon_path / "power1_input"

        if power1_input.exists():
            stats["power"] = self._read_sysfs_value(
                power1_input, scale=1000000
            )  # Convert microwatts to watts

        # Get power limit
        power1_cap = hwmon_path / "power1_cap"
        if power1_cap.exists():
            stats["power_limit"] = self._read_sysfs_value(power1_cap, scale=1000000)

        # Get fan speed (PWM or RPM)
        # Try PWM first (0-255 range)
        pwm1_path = hwmon_path / "pwm1"
        if pwm1_path.exists():
            pwm_value = self._read_sysfs_value(pwm1_path)
            stats["fan_speed"] = (pwm_value / 255) * 100  # Convert to percentage
        else:
            # Try fan RPM
            fan1_input = hwmon_path / "fan1_input"
            fan1_max = hwmon_path / "fan1_max"
            if fan1_input.exists() and fan1_max.exists():
                current_rpm = self._read_sysfs_value(fan1_input)
                max_rpm = self._read_sysfs_value(fan1_max)
                if max_rpm > 0:
                    stats["fan_speed"] = (current_rpm / max_rpm) * 100

        # Get GPU clock states
        clocks = {}
        clock_states = {}

        for clock_type in ["sclk", "mclk", "fclk", "socclk"]:
            clock_file = device_path / f"pp_dpm_{clock_type}"
            current_freq, states = self._parse_dpm_clock_file(clock_file)

            if current_freq is not None:
                clocks[clock_type] = current_freq
                clock_states[clock_type] = states

        stats["clocks"] = clocks
        stats["clock_states"] = clock_states

        # Get performance level
        stats["performance_level"] = self._get_performance_level(device_path)

        return stats

    def cleanup(self):
        """Cleanup resources"""
        if self.tegrastats_process:
            self.tegrastats_process.terminate()
            self.tegrastats_process = None


class GPUTop:
    """Main application class"""

    def __init__(self, stats_file=None):
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

        # JSON logging
        self.stats_file = stats_file
        self.json_data = []

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

        # Generate graph on exit if matplotlib is available and we have data
        if MATPLOTLIB_AVAILABLE and self.stats_file and self.json_data:
            self.generate_graphs()

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
        if self.gpu_monitor.gpu_count > 1:
            y = 6
            out.append(f"\033[{y};3f" + Theme.text + "Select GPU: ")
            for i in range(self.gpu_monitor.gpu_count):
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
            }

            for clock_type in ["sclk", "mclk", "fclk", "socclk", "gpu", "memory"]:
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

                    out.append(
                        f"\033[{box_y + line};6f"
                        + Theme.text
                        + f"  {label:8s}: "
                        + color
                        + f"{freq:5.0f} MHz"
                        + Term.normal
                    )
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
        if stats.get("clocks") and stats.get("clock_states"):
            self.clock_graph.add_values(stats["clocks"], stats["clock_states"])

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
                "Memory Usage %",
            )
        )
        out.append(self.mem_graph.draw(center_x + 2, y + 1, Theme.mem_gradient))

        # Temperature Graph (multi-sensor with limits)
        y += graph_spacing
        # Make box taller to accommodate legend
        out.append(
            Box.draw(
                center_x,
                y,
                self.temp_graph.width + 4,
                self.temp_graph.height + 5,
                "Temperature Sensors °C",
            )
        )
        out.append(self.temp_graph.draw(center_x + 2, y + 1))

        # RIGHT COLUMN - Clock and Power
        # Clock Graph at top right
        if stats.get("clocks"):
            y_right = 8  # Start at same height as GPU utilization
            out.append(
                Box.draw(
                    right_x,
                    y_right,
                    self.clock_graph.width + 4,
                    self.clock_graph.height + 5,
                    "Clock Frequencies MHz",
                )
            )
            out.append(self.clock_graph.draw(right_x + 2, y_right + 1))
            y_power = y_right + self.clock_graph.height + 7
        else:
            y_power = 8

        # Power Graph below clocks
        if stats["power"] > 0:
            y = y_power

            # Adjust max value if current power exceeds it
            if stats["power"] > self.power_graph.max_value * 0.9:
                self.power_graph.max_value = int(stats["power"] * 1.2)

            # Create power gradient that gets redder as we approach limit
            power_gradient = [
                (0, 200, 100),  # Green at low power
                (100, 200, 0),  # Yellow-green
                (200, 200, 0),  # Yellow
                (255, 150, 0),  # Orange
                (255, 50, 0),  # Red-orange
                (255, 0, 0),  # Red at max
            ]

            title = f"Power Draw W (Max: {self.power_graph.max_value}W)"
            if stats["power_limit"] > 0:
                title = f"Power Draw W (Limit: {stats['power_limit']}W)"

            out.append(
                Box.draw(
                    right_x,
                    y,
                    self.power_graph.width + 4,
                    self.power_graph.height + 3,
                    title,
                )
            )
            out.append(self.power_graph.draw(right_x + 2, y + 1, power_gradient))
            y_fan = y + self.power_graph.height + 5
        else:
            y_fan = y_power

        # Fan Speed Graph below power
        if stats.get("fan_speed", 0) >= 0:  # Show even if 0%
            y = y_fan

            # Fan gradient - blue to red as speed increases
            fan_gradient = [
                (0, 100, 255),  # Blue at low speed
                (0, 200, 200),  # Cyan
                (200, 200, 0),  # Yellow
                (255, 150, 0),  # Orange
                (255, 0, 0),  # Red at max
            ]

            out.append(
                Box.draw(
                    right_x,
                    y,
                    self.fan_graph.width + 4,
                    self.fan_graph.height + 3,
                    "Fan Speed %",
                )
            )
            out.append(self.fan_graph.draw(right_x + 2, y + 1, fan_gradient))

        return "".join(out)

    def draw_footer(self):
        """Draw footer with controls"""
        out = []
        y = Term.height - 2

        footer_text = "Press 'q' to quit"
        if self.gpu_monitor.gpu_count > 1:
            footer_text += " | Use number keys to select GPU"
        footer_text += f" | Update: {self.update_interval:.1f}s"

        x = (Term.width - len(footer_text)) // 2
        out.append(f"\033[{y};{x}f" + Theme.border + footer_text + Term.normal)

        return "".join(out)

    def update_display(self):
        """Update the entire display"""
        stats = self.gpu_monitor.get_stats(self.selected_gpu)
        self.stats_history.append(stats)

        # Log to JSON if enabled
        if self.stats_file:
            self.log_stats_to_json(stats)

        # Clear screen and redraw
        output = [Term.clear]
        output.append(self.draw_header())
        output.append(self.draw_stats(stats))
        output.append(self.draw_graphs(stats))
        output.append(self.draw_footer())

        print("".join(output), end="", flush=True)

    def log_stats_to_json(self, stats):
        """Log stats to JSON file for currently selected GPU and all GPUs if multi-GPU"""
        timestamp = datetime.now().isoformat()

        # Log currently selected GPU (backwards compatibility)
        entry = {
            "timestamp": timestamp,
            "gpu_index": self.selected_gpu,
            "gpu_name": stats["name"],
            "gpu_type": self.gpu_monitor.gpu_type,
            "utilization": stats["utilization"],
            "memory_used": stats["memory_used"],
            "memory_total": stats["memory_total"],
            "memory_percent": stats["memory_percent"],
            "temperatures": stats.get("temperatures", {}),
            "temp_limits": stats.get("temp_limits", {}),
            "power": stats["power"],
            "power_limit": stats["power_limit"],
            "fan_speed": stats["fan_speed"],
            "clocks": stats.get("clocks", {}),
            "clock_states": stats.get("clock_states", {}),
            "performance_level": stats.get("performance_level", "unknown"),
        }

        self.json_data.append(entry)

        # For multi-GPU setups, also log all GPUs in a separate structure
        if self.gpu_monitor.gpu_count > 1:
            all_gpu_entry = {"timestamp": timestamp, "multi_gpu_data": []}

            # Collect data for all GPUs and calculate aggregates
            total_memory_used = 0
            total_memory_total = 0
            total_power = 0
            total_power_limit = 0
            avg_utilization = 0
            max_temp = 0

            for gpu_idx in range(self.gpu_monitor.gpu_count):
                gpu_stats = self.gpu_monitor.get_stats(gpu_idx)
                all_gpu_entry["multi_gpu_data"].append(
                    {
                        "gpu_index": gpu_idx,
                        "gpu_name": gpu_stats["name"],
                        "utilization": gpu_stats["utilization"],
                        "memory_used": gpu_stats["memory_used"],
                        "memory_total": gpu_stats["memory_total"],
                        "memory_percent": gpu_stats["memory_percent"],
                        "temperatures": gpu_stats.get("temperatures", {}),
                        "power": gpu_stats["power"],
                        "power_limit": gpu_stats["power_limit"],
                        "clocks": gpu_stats.get("clocks", {}),
                    }
                )

                # Accumulate for aggregates
                total_memory_used += gpu_stats["memory_used"]
                total_memory_total += gpu_stats["memory_total"]
                total_power += gpu_stats["power"]
                total_power_limit += gpu_stats["power_limit"]
                avg_utilization += gpu_stats["utilization"]

                # Find max temperature across all sensors
                temps = gpu_stats.get("temperatures", {})
                if temps:
                    current_max = max(temps.values()) if temps.values() else 0
                    max_temp = max(max_temp, current_max)

            # Add aggregate summary
            avg_utilization = avg_utilization / self.gpu_monitor.gpu_count
            total_memory_percent = (
                (total_memory_used / total_memory_total * 100)
                if total_memory_total > 0
                else 0
            )

            all_gpu_entry["aggregate_stats"] = {
                "total_memory_used": total_memory_used,
                "total_memory_total": total_memory_total,
                "total_memory_percent": total_memory_percent,
                "average_utilization": avg_utilization,
                "total_power": total_power,
                "total_power_limit": total_power_limit,
                "max_temperature": max_temp,
                "gpu_count": self.gpu_monitor.gpu_count,
            }

            # Store multi-GPU data separately
            if not hasattr(self, "multi_gpu_data"):
                self.multi_gpu_data = []
            self.multi_gpu_data.append(all_gpu_entry)

        # Write to file
        try:
            with open(self.stats_file, "w") as f:
                json.dump(self.json_data, f, indent=2)

            # Write multi-GPU data to separate file if available
            if hasattr(self, "multi_gpu_data") and self.multi_gpu_data:
                multi_gpu_file = self.stats_file.replace(".json", "_multi_gpu.json")
                with open(multi_gpu_file, "w") as f:
                    json.dump(self.multi_gpu_data, f, indent=2)
        except Exception as e:
            pass  # Silently ignore write errors

    def handle_input(self):
        """Handle keyboard input"""
        try:
            # Set stdin to non-blocking
            old_settings = termios.tcgetattr(sys.stdin)
            try:
                tty.setraw(sys.stdin.fileno())

                # Check for input without blocking
                if select([sys.stdin], [], [], 0)[0]:
                    key = sys.stdin.read(1)

                    if key == "q" or key == "Q":
                        self.running = False
                    elif key.isdigit():
                        gpu_num = int(key)
                        if gpu_num < self.gpu_monitor.gpu_count:
                            self.selected_gpu = gpu_num
                            # Clear graph history when switching GPUs
                            self.util_graph.data.clear()
                            self.mem_graph.data.clear()
                            self.temp_graph.sensor_data.clear()
                            self.power_graph.data.clear()
                            self.clock_graph.clock_data.clear()
                            self.fan_graph.data.clear()
            finally:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        except (termios.error, OSError):
            # Running in non-interactive mode (SSH, etc.)
            pass

    def generate_graphs(self):
        """Generate matplotlib graphs from collected data"""
        if not self.json_data:
            return

        print("\nGenerating performance graphs...")

        try:
            # Extract data for plotting (Python 3.6 compatible)
            timestamps = []
            for d in self.json_data:
                # Parse ISO format manually for Python 3.6 compatibility
                ts = d["timestamp"]
                # Handle different timestamp formats
                try:
                    # Try parsing with microseconds first
                    timestamps.append(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f"))
                except ValueError:
                    try:
                        # Try without microseconds
                        timestamps.append(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S"))
                    except ValueError:
                        # If both fail, try removing microseconds manually
                        if "." in ts:
                            ts = ts.split(".")[0]
                        timestamps.append(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S"))

            utilization = [d["utilization"] for d in self.json_data]
            memory_percent = [d["memory_percent"] for d in self.json_data]

            # Handle temperature structure (multiple sensors)
            # Need to ensure all arrays have same length as timestamps
            temp_sensors = {}
            for i, entry in enumerate(self.json_data):
                if "temperatures" in entry and entry["temperatures"]:
                    for sensor_name, temp_value in entry["temperatures"].items():
                        if sensor_name not in temp_sensors:
                            # Initialize with None for all previous entries
                            temp_sensors[sensor_name] = [None] * i
                        temp_sensors[sensor_name].append(temp_value)
                # For sensors that exist but not in this entry, append None
                for sensor_name in temp_sensors:
                    if len(temp_sensors[sensor_name]) <= i:
                        temp_sensors[sensor_name].append(None)

            # Ensure all temp sensors have same length as timestamps
            for sensor_name in temp_sensors:
                while len(temp_sensors[sensor_name]) < len(timestamps):
                    temp_sensors[sensor_name].append(None)

            power = [d["power"] for d in self.json_data]
            fan_speed = [d["fan_speed"] for d in self.json_data]

            # Extract clock data with same length guarantee
            clock_data = {}
            for i, entry in enumerate(self.json_data):
                clocks = entry.get("clocks", {})
                for clock_type in clocks:
                    if clock_type not in clock_data:
                        # Initialize with None for all previous entries
                        clock_data[clock_type] = [None] * i
                    clock_data[clock_type].append(clocks[clock_type])
                # For clocks that exist but not in this entry, append None
                for clock_type in clock_data:
                    if len(clock_data[clock_type]) <= i:
                        clock_data[clock_type].append(None)

            # Ensure all clocks have same length as timestamps
            for clock_type in clock_data:
                while len(clock_data[clock_type]) < len(timestamps):
                    clock_data[clock_type].append(None)

            # Create figure with 3 rows x 2 columns
            fig, axes = plt.subplots(3, 2, figsize=(15, 12))
            fig.suptitle(
                f'GPU Performance - {self.json_data[0]["gpu_name"]}', fontsize=16
            )

            # Row 1: GPU Utilization, Clock Frequencies
            # GPU Utilization
            axes[0, 0].plot(timestamps, utilization, "b-", linewidth=2)
            axes[0, 0].set_title("GPU Utilization")
            axes[0, 0].set_ylabel("Utilization (%)")
            axes[0, 0].grid(True, alpha=0.3)
            axes[0, 0].set_ylim(0, 105)

            # Clock frequencies - All clocks combined
            clock_colors_map = {
                "sclk": "orange",
                "mclk": "blue",
                "fclk": "green",
                "socclk": "magenta",
                "gpu": "orange",
                "memory": "blue",
            }
            clock_labels = {
                "sclk": "Core",
                "mclk": "Memory",
                "fclk": "Fabric",
                "socclk": "SoC",
                "gpu": "GPU",
                "memory": "Memory",
            }

            for clock_type, values in clock_data.items():
                # Filter out None values and check if any valid data exists
                if any(v is not None and v > 0 for v in values):
                    color = clock_colors_map.get(clock_type, "gray")
                    label = clock_labels.get(clock_type, clock_type)
                    # Create masked arrays to handle None values
                    import numpy as np

                    masked_values = np.ma.array(
                        values, mask=[v is None for v in values]
                    )
                    axes[0, 1].plot(
                        timestamps,
                        masked_values,
                        "-",
                        linewidth=2,
                        color=color,
                        label=label,
                    )

            axes[0, 1].set_title("Clock Frequencies")
            axes[0, 1].set_ylabel("Frequency (MHz)")
            axes[0, 1].grid(True, alpha=0.3)
            if clock_data:
                axes[0, 1].legend(loc="upper right", fontsize=8)

            # Row 2: Memory Usage, Power Draw
            # Memory Usage (percentage)
            axes[1, 0].plot(timestamps, memory_percent, "g-", linewidth=2)
            axes[1, 0].set_title("Memory Usage")
            axes[1, 0].set_ylabel("Memory (%)")
            axes[1, 0].grid(True, alpha=0.3)
            axes[1, 0].set_ylim(0, 105)

            # Power Draw
            if any(p > 0 for p in power):
                axes[1, 1].plot(timestamps, power, "orange", linewidth=2)
                axes[1, 1].set_title("Power Draw")
                axes[1, 1].set_ylabel("Power (W)")
                axes[1, 1].grid(True, alpha=0.3)
                if (
                    self.json_data
                    and "power_limit" in self.json_data[0]
                    and self.json_data[0]["power_limit"] > 0
                ):
                    axes[1, 1].axhline(
                        y=self.json_data[0]["power_limit"],
                        color="r",
                        linestyle="--",
                        alpha=0.5,
                        label=f"Limit: {self.json_data[0]['power_limit']:.0f}W",
                    )
                    axes[1, 1].legend()
            else:
                axes[1, 1].text(
                    0.5,
                    0.5,
                    "Power Data\nNot Available",
                    ha="center",
                    va="center",
                    fontsize=12,
                )
                axes[1, 1].set_xticks([])
                axes[1, 1].set_yticks([])

            # Row 3: Temperature Sensors, Fan Speed
            # Temperature (multiple sensors)
            if temp_sensors:
                sensor_colors_map = {
                    # AMD sensors
                    "Edge": "blue",
                    "Junction": "orange",
                    "Memory": "green",
                    "Hotspot": "red",
                    # NVIDIA sensors
                    "GPU": "orange",
                    "CPU": "blue",
                    "PMIC": "green",
                    "AO": "red",
                    "PLL": "gray",
                }

                import numpy as np

                for sensor_name, temps in temp_sensors.items():
                    # Only plot if there's valid data
                    if any(t is not None for t in temps):
                        color = sensor_colors_map.get(sensor_name, "gray")
                        # Create masked array to handle None values
                        masked_temps = np.ma.array(
                            temps, mask=[t is None for t in temps]
                        )
                        axes[2, 0].plot(
                            timestamps,
                            masked_temps,
                            "-",
                            linewidth=2,
                            color=color,
                            label=sensor_name,
                        )

                # Add temperature limit lines if available (AMD)
                if self.json_data and "temp_limits" in self.json_data[0]:
                    for sensor_name, limits in self.json_data[0]["temp_limits"].items():
                        if "critical" in limits:
                            axes[2, 0].axhline(
                                y=limits["critical"],
                                color="orange",
                                linestyle="--",
                                alpha=0.5,
                                linewidth=1,
                            )
                        if "emergency" in limits:
                            axes[2, 0].axhline(
                                y=limits["emergency"],
                                color="red",
                                linestyle="--",
                                alpha=0.5,
                                linewidth=1,
                            )

                axes[2, 0].set_title("Temperature Sensors")
                axes[2, 0].set_ylabel("Temperature (°C)")
                axes[2, 0].grid(True, alpha=0.3)
                axes[2, 0].legend(loc="upper right", fontsize=8)

            # Fan Speed
            if any(fs > 0 for fs in fan_speed):
                axes[2, 1].plot(timestamps, fan_speed, "cyan", linewidth=2)
                axes[2, 1].set_title("Fan Speed")
                axes[2, 1].set_ylabel("Fan Speed (%)")
                axes[2, 1].grid(True, alpha=0.3)
                axes[2, 1].set_ylim(0, 105)
            else:
                axes[2, 1].text(
                    0.5,
                    0.5,
                    "Fan Speed\nNot Available",
                    ha="center",
                    va="center",
                    fontsize=12,
                )
                axes[2, 1].set_xticks([])
                axes[2, 1].set_yticks([])

            # Format x-axis for all subplots
            for ax in axes.flat:
                if ax.get_xticks().size > 0:  # Only format if axis has ticks
                    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
                    ax.tick_params(axis="x", rotation=45)

            plt.tight_layout()

            # Save the plot
            plot_file = self.stats_file.replace(".json", "_plot.png")
            plt.savefig(plot_file, dpi=100, bbox_inches="tight")
            print(f"Graph saved to: {plot_file}")

            # Also save a summary statistics file
            self.save_summary_stats()

        except Exception as e:
            print(f"Error generating graphs: {e}")

    def save_summary_stats(self):
        """Save summary statistics to a text file"""
        if not self.json_data:
            return

        summary_file = self.stats_file.replace(".json", "_summary.txt")

        try:
            # Calculate statistics
            utilization = [d["utilization"] for d in self.json_data]
            memory_percent = [d["memory_percent"] for d in self.json_data]

            # Handle temperature structure
            temp_sensors = {}
            for entry in self.json_data:
                if "temperatures" in entry and entry["temperatures"]:
                    for sensor_name, temp_value in entry["temperatures"].items():
                        if sensor_name not in temp_sensors:
                            temp_sensors[sensor_name] = []
                        temp_sensors[sensor_name].append(temp_value)

            power = [d["power"] for d in self.json_data if d["power"] > 0]

            with open(summary_file, "w") as f:
                f.write(f"GPU Performance Summary\n")
                f.write(f"========================\n\n")
                f.write(f"GPU: {self.json_data[0]['gpu_name']}\n")
                f.write(f"Type: {self.json_data[0].get('gpu_type', 'unknown')}\n")
                f.write(f"Duration: {len(self.json_data)} seconds\n")
                f.write(f"Start: {self.json_data[0]['timestamp']}\n")
                f.write(f"End: {self.json_data[-1]['timestamp']}\n\n")

                f.write(f"GPU Utilization:\n")
                f.write(f"  Average: {sum(utilization)/len(utilization):.1f}%\n")
                f.write(f"  Max: {max(utilization):.1f}%\n")
                f.write(f"  Min: {min(utilization):.1f}%\n\n")

                f.write(f"Memory Usage:\n")
                f.write(f"  Average: {sum(memory_percent)/len(memory_percent):.1f}%\n")
                f.write(f"  Max: {max(memory_percent):.1f}%\n")
                f.write(f"  Min: {min(memory_percent):.1f}%\n\n")

                f.write(f"Temperature Sensors:\n")
                for sensor_name, temps in temp_sensors.items():
                    if temps:
                        f.write(f"  {sensor_name}:\n")
                        f.write(f"    Average: {sum(temps)/len(temps):.1f}°C\n")
                        f.write(f"    Max: {max(temps):.1f}°C\n")
                        f.write(f"    Min: {min(temps):.1f}°C\n")
                f.write("\n")

                if power:
                    f.write(f"Power Draw:\n")
                    f.write(f"  Average: {sum(power)/len(power):.1f}W\n")
                    f.write(f"  Max: {max(power):.1f}W\n")
                    f.write(f"  Min: {min(power):.1f}W\n")

            print(f"Summary saved to: {summary_file}")

        except Exception as e:
            pass

    def compare_and_visualize(self, json_data1, json_data2, file1_name, file2_name):
        """Compare two JSON datasets and visualize differences"""
        if not json_data1 or not json_data2:
            print("Error: One or both datasets are empty")
            return

        print(f"\nComparing GPU performance data:")
        print(f"  Run 1: {file1_name} ({len(json_data1)} samples)")
        print(f"  Run 2: {file2_name} ({len(json_data2)} samples)")

        # Extract comparison data
        def extract_stats(data):
            stats = {
                "timestamps": [],
                "utilization": [],
                "memory_percent": [],
                "power": [],
                "fan_speed": [],
                "temp_sensors": {},
                "clocks": {},
            }

            for d in data:
                # Parse timestamp
                ts = d["timestamp"]
                try:
                    stats["timestamps"].append(
                        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f")
                    )
                except ValueError:
                    try:
                        stats["timestamps"].append(
                            datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
                        )
                    except ValueError:
                        if "." in ts:
                            ts = ts.split(".")[0]
                        stats["timestamps"].append(
                            datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
                        )

                stats["utilization"].append(d["utilization"])
                stats["memory_percent"].append(d["memory_percent"])
                stats["power"].append(d["power"])
                stats["fan_speed"].append(d["fan_speed"])

                # Handle temperatures
                if "temperatures" in d and d["temperatures"]:
                    for sensor, temp in d["temperatures"].items():
                        if sensor not in stats["temp_sensors"]:
                            stats["temp_sensors"][sensor] = []
                        stats["temp_sensors"][sensor].append(temp)

                # Handle clocks
                if "clocks" in d and d["clocks"]:
                    for clock_type, freq in d["clocks"].items():
                        if clock_type not in stats["clocks"]:
                            stats["clocks"][clock_type] = []
                        stats["clocks"][clock_type].append(freq)

            return stats

        stats1 = extract_stats(json_data1)
        stats2 = extract_stats(json_data2)

        # Calculate summary statistics for comparison
        def calc_summary(values):
            if not values:
                return {"avg": 0, "max": 0, "min": 0}
            return {
                "avg": sum(values) / len(values),
                "max": max(values),
                "min": min(values),
            }

        # Print comparison summary
        print("\n" + "=" * 60)
        print("PERFORMANCE COMPARISON SUMMARY")
        print("=" * 60)

        # GPU Utilization
        util1 = calc_summary(stats1["utilization"])
        util2 = calc_summary(stats2["utilization"])
        print(f"\nGPU Utilization:")
        print(
            f"  Average:  Run1: {util1['avg']:6.1f}%  |  Run2: {util2['avg']:6.1f}%  |  Diff: {util2['avg']-util1['avg']:+6.1f}%"
        )
        print(
            f"  Maximum:  Run1: {util1['max']:6.1f}%  |  Run2: {util2['max']:6.1f}%  |  Diff: {util2['max']-util1['max']:+6.1f}%"
        )
        print(
            f"  Minimum:  Run1: {util1['min']:6.1f}%  |  Run2: {util2['min']:6.1f}%  |  Diff: {util2['min']-util1['min']:+6.1f}%"
        )

        # Memory Usage
        mem1 = calc_summary(stats1["memory_percent"])
        mem2 = calc_summary(stats2["memory_percent"])
        print(f"\nMemory Usage:")
        print(
            f"  Average:  Run1: {mem1['avg']:6.1f}%  |  Run2: {mem2['avg']:6.1f}%  |  Diff: {mem2['avg']-mem1['avg']:+6.1f}%"
        )
        print(
            f"  Maximum:  Run1: {mem1['max']:6.1f}%  |  Run2: {mem2['max']:6.1f}%  |  Diff: {mem2['max']-mem1['max']:+6.1f}%"
        )
        print(
            f"  Minimum:  Run1: {mem1['min']:6.1f}%  |  Run2: {mem2['min']:6.1f}%  |  Diff: {mem2['min']-mem1['min']:+6.1f}%"
        )

        # Power Draw
        power1_vals = [p for p in stats1["power"] if p > 0]
        power2_vals = [p for p in stats2["power"] if p > 0]
        if power1_vals and power2_vals:
            pow1 = calc_summary(power1_vals)
            pow2 = calc_summary(power2_vals)
            print(f"\nPower Draw:")
            print(
                f"  Average:  Run1: {pow1['avg']:6.1f}W  |  Run2: {pow2['avg']:6.1f}W  |  Diff: {pow2['avg']-pow1['avg']:+6.1f}W"
            )
            print(
                f"  Maximum:  Run1: {pow1['max']:6.1f}W  |  Run2: {pow2['max']:6.1f}W  |  Diff: {pow2['max']-pow1['max']:+6.1f}W"
            )
            print(
                f"  Minimum:  Run1: {pow1['min']:6.1f}W  |  Run2: {pow2['min']:6.1f}W  |  Diff: {pow2['min']-pow1['min']:+6.1f}W"
            )

        # Temperature comparison
        common_sensors = set(stats1["temp_sensors"].keys()) & set(
            stats2["temp_sensors"].keys()
        )
        if common_sensors:
            print(f"\nTemperature Sensors:")
            for sensor in sorted(common_sensors):
                temp1 = calc_summary(stats1["temp_sensors"][sensor])
                temp2 = calc_summary(stats2["temp_sensors"][sensor])
                print(f"  {sensor}:")
                print(
                    f"    Average:  Run1: {temp1['avg']:5.1f}°C  |  Run2: {temp2['avg']:5.1f}°C  |  Diff: {temp2['avg']-temp1['avg']:+5.1f}°C"
                )
                print(
                    f"    Maximum:  Run1: {temp1['max']:5.1f}°C  |  Run2: {temp2['max']:5.1f}°C  |  Diff: {temp2['max']-temp1['max']:+5.1f}°C"
                )

        # Clock frequency comparison
        common_clocks = set(stats1["clocks"].keys()) & set(stats2["clocks"].keys())
        if common_clocks:
            print(f"\nClock Frequencies:")
            for clock_type in sorted(common_clocks):
                clk1 = calc_summary(stats1["clocks"][clock_type])
                clk2 = calc_summary(stats2["clocks"][clock_type])
                print(f"  {clock_type}:")
                print(
                    f"    Average:  Run1: {clk1['avg']:6.0f}MHz  |  Run2: {clk2['avg']:6.0f}MHz  |  Diff: {clk2['avg']-clk1['avg']:+6.0f}MHz"
                )
                print(
                    f"    Maximum:  Run1: {clk1['max']:6.0f}MHz  |  Run2: {clk2['max']:6.0f}MHz  |  Diff: {clk2['max']-clk1['max']:+6.0f}MHz"
                )

        print("\n" + "=" * 60)

        # Generate comparison graphs if matplotlib is available
        if MATPLOTLIB_AVAILABLE:
            self.generate_comparison_graphs(stats1, stats2, file1_name, file2_name)

    def generate_comparison_graphs(self, stats1, stats2, file1_name, file2_name):
        """Generate comparison graphs for two datasets"""
        print("\nGenerating comparison graphs...")

        # Create figure with 4 rows x 2 columns to include memory temperature
        fig, axes = plt.subplots(4, 2, figsize=(16, 16))
        fig.suptitle("GPU Performance Comparison", fontsize=16)

        # Prepare labels
        label1 = f"Run 1: {Path(file1_name).stem}"
        label2 = f"Run 2: {Path(file2_name).stem}"

        # GPU Utilization comparison
        axes[0, 0].plot(
            range(len(stats1["utilization"])),
            stats1["utilization"],
            "b-",
            linewidth=1.5,
            label=label1,
            alpha=0.7,
        )
        axes[0, 0].plot(
            range(len(stats2["utilization"])),
            stats2["utilization"],
            "r-",
            linewidth=1.5,
            label=label2,
            alpha=0.7,
        )
        axes[0, 0].set_title("GPU Utilization Comparison")
        axes[0, 0].set_ylabel("Utilization (%)")
        axes[0, 0].set_xlabel("Sample")
        axes[0, 0].grid(True, alpha=0.3)
        axes[0, 0].legend()
        axes[0, 0].set_ylim(0, 105)

        # Memory Usage comparison
        axes[0, 1].plot(
            range(len(stats1["memory_percent"])),
            stats1["memory_percent"],
            "b-",
            linewidth=1.5,
            label=label1,
            alpha=0.7,
        )
        axes[0, 1].plot(
            range(len(stats2["memory_percent"])),
            stats2["memory_percent"],
            "r-",
            linewidth=1.5,
            label=label2,
            alpha=0.7,
        )
        axes[0, 1].set_title("Memory Usage Comparison")
        axes[0, 1].set_ylabel("Memory (%)")
        axes[0, 1].set_xlabel("Sample")
        axes[0, 1].grid(True, alpha=0.3)
        axes[0, 1].legend()
        axes[0, 1].set_ylim(0, 105)

        # Power Draw comparison
        power1_vals = [p if p > 0 else None for p in stats1["power"]]
        power2_vals = [p if p > 0 else None for p in stats2["power"]]
        if any(p for p in power1_vals if p) or any(p for p in power2_vals if p):
            axes[1, 0].plot(
                range(len(power1_vals)),
                power1_vals,
                "b-",
                linewidth=1.5,
                label=label1,
                alpha=0.7,
            )
            axes[1, 0].plot(
                range(len(power2_vals)),
                power2_vals,
                "r-",
                linewidth=1.5,
                label=label2,
                alpha=0.7,
            )
            axes[1, 0].set_title("Power Draw Comparison")
            axes[1, 0].set_ylabel("Power (W)")
            axes[1, 0].set_xlabel("Sample")
            axes[1, 0].grid(True, alpha=0.3)
            axes[1, 0].legend()
        else:
            axes[1, 0].text(
                0.5,
                0.5,
                "Power Data\nNot Available",
                ha="center",
                va="center",
                fontsize=12,
            )
            axes[1, 0].set_xticks([])
            axes[1, 0].set_yticks([])

        # Fan Speed comparison
        if any(stats1["fan_speed"]) or any(stats2["fan_speed"]):
            axes[1, 1].plot(
                range(len(stats1["fan_speed"])),
                stats1["fan_speed"],
                "b-",
                linewidth=1.5,
                label=label1,
                alpha=0.7,
            )
            axes[1, 1].plot(
                range(len(stats2["fan_speed"])),
                stats2["fan_speed"],
                "r-",
                linewidth=1.5,
                label=label2,
                alpha=0.7,
            )
            axes[1, 1].set_title("Fan Speed Comparison")
            axes[1, 1].set_ylabel("Fan Speed (%)")
            axes[1, 1].set_xlabel("Sample")
            axes[1, 1].grid(True, alpha=0.3)
            axes[1, 1].legend()
            axes[1, 1].set_ylim(0, 105)
        else:
            axes[1, 1].text(
                0.5,
                0.5,
                "Fan Speed\nNot Available",
                ha="center",
                va="center",
                fontsize=12,
            )
            axes[1, 1].set_xticks([])
            axes[1, 1].set_yticks([])

        # Temperature comparison (pick most common sensor)
        common_sensors = set(stats1["temp_sensors"].keys()) & set(
            stats2["temp_sensors"].keys()
        )
        if common_sensors:
            # Use the first common sensor for main comparison
            main_sensor = sorted(common_sensors)[0]
            axes[2, 0].plot(
                range(len(stats1["temp_sensors"][main_sensor])),
                stats1["temp_sensors"][main_sensor],
                "b-",
                linewidth=1.5,
                label=f"{label1} - {main_sensor}",
                alpha=0.7,
            )
            axes[2, 0].plot(
                range(len(stats2["temp_sensors"][main_sensor])),
                stats2["temp_sensors"][main_sensor],
                "r-",
                linewidth=1.5,
                label=f"{label2} - {main_sensor}",
                alpha=0.7,
            )
            axes[2, 0].set_title(f"Temperature Comparison ({main_sensor})")
            axes[2, 0].set_ylabel("Temperature (°C)")
            axes[2, 0].set_xlabel("Sample")
            axes[2, 0].grid(True, alpha=0.3)
            axes[2, 0].legend()
        else:
            axes[2, 0].text(
                0.5,
                0.5,
                "No Common\nTemperature Sensors",
                ha="center",
                va="center",
                fontsize=12,
            )
            axes[2, 0].set_xticks([])
            axes[2, 0].set_yticks([])

        # Clock frequency comparison
        common_clocks = set(stats1["clocks"].keys()) & set(stats2["clocks"].keys())
        if common_clocks:
            # Pick the main clock (sclk, gpu, or first available)
            main_clock = None
            for preferred in ["sclk", "gpu"]:
                if preferred in common_clocks:
                    main_clock = preferred
                    break
            if not main_clock:
                main_clock = sorted(common_clocks)[0]

            axes[2, 1].plot(
                range(len(stats1["clocks"][main_clock])),
                stats1["clocks"][main_clock],
                "b-",
                linewidth=1.5,
                label=f"{label1} - {main_clock}",
                alpha=0.7,
            )
            axes[2, 1].plot(
                range(len(stats2["clocks"][main_clock])),
                stats2["clocks"][main_clock],
                "r-",
                linewidth=1.5,
                label=f"{label2} - {main_clock}",
                alpha=0.7,
            )
            axes[2, 1].set_title(f"Clock Frequency Comparison ({main_clock})")
            axes[2, 1].set_ylabel("Frequency (MHz)")
            axes[2, 1].set_xlabel("Sample")
            axes[2, 1].grid(True, alpha=0.3)
            axes[2, 1].legend()
        else:
            axes[2, 1].text(
                0.5, 0.5, "No Common\nClock Data", ha="center", va="center", fontsize=12
            )
            axes[2, 1].set_xticks([])
            axes[2, 1].set_yticks([])

        # Memory Temperature comparison (Row 4, Column 1)
        memory_found = False
        for sensor_name in ["Memory", "mem", "MEM"]:
            if sensor_name in stats1.get(
                "temp_sensors", {}
            ) and sensor_name in stats2.get("temp_sensors", {}):
                axes[3, 0].plot(
                    range(len(stats1["temp_sensors"][sensor_name])),
                    stats1["temp_sensors"][sensor_name],
                    "b-",
                    linewidth=1.5,
                    label=f"{label1}",
                    alpha=0.7,
                )
                axes[3, 0].plot(
                    range(len(stats2["temp_sensors"][sensor_name])),
                    stats2["temp_sensors"][sensor_name],
                    "r-",
                    linewidth=1.5,
                    label=f"{label2}",
                    alpha=0.7,
                )
                axes[3, 0].set_title("Memory Temperature Comparison")
                axes[3, 0].set_ylabel("Temperature (°C)")
                axes[3, 0].set_xlabel("Sample")
                axes[3, 0].grid(True, alpha=0.3)
                axes[3, 0].legend()
                memory_found = True
                break

        if not memory_found:
            axes[3, 0].text(
                0.5,
                0.5,
                "Memory Temperature\nNot Available",
                ha="center",
                va="center",
                fontsize=12,
            )
            axes[3, 0].set_xticks([])
            axes[3, 0].set_yticks([])

        # All Temperature Sensors Overlay (Row 4, Column 2)
        # Show all available temperature sensors for comprehensive view
        if common_sensors:
            for sensor in sorted(common_sensors):
                # Plot Run 1
                axes[3, 1].plot(
                    range(len(stats1["temp_sensors"][sensor])),
                    stats1["temp_sensors"][sensor],
                    linewidth=1.0,
                    label=f"{label1} - {sensor}",
                    alpha=0.6,
                )
            for sensor in sorted(common_sensors):
                # Plot Run 2 with dashed lines for distinction
                axes[3, 1].plot(
                    range(len(stats2["temp_sensors"][sensor])),
                    stats2["temp_sensors"][sensor],
                    "--",
                    linewidth=1.0,
                    label=f"{label2} - {sensor}",
                    alpha=0.6,
                )
            axes[3, 1].set_title("All Temperature Sensors Comparison")
            axes[3, 1].set_ylabel("Temperature (°C)")
            axes[3, 1].set_xlabel("Sample")
            axes[3, 1].grid(True, alpha=0.3)
            axes[3, 1].legend(fontsize=8, ncol=2)
        else:
            axes[3, 1].text(
                0.5,
                0.5,
                "No Temperature\nSensor Data",
                ha="center",
                va="center",
                fontsize=12,
            )
            axes[3, 1].set_xticks([])
            axes[3, 1].set_yticks([])

        plt.tight_layout()

        # Save the comparison plot
        output_file = "gpu_comparison.png"
        plt.savefig(output_file, dpi=100, bbox_inches="tight")
        print(f"Comparison graph saved to: {output_file}")

        # Also generate histograms for distribution comparison
        self.generate_comparison_histograms(stats1, stats2, label1, label2)

    def generate_comparison_histograms(self, stats1, stats2, label1, label2):
        """Generate histogram comparisons for key metrics"""
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        fig.suptitle("Performance Distribution Comparison", fontsize=16)

        # GPU Utilization distribution
        axes[0, 0].hist(
            stats1["utilization"], bins=20, alpha=0.5, label=label1, color="blue"
        )
        axes[0, 0].hist(
            stats2["utilization"], bins=20, alpha=0.5, label=label2, color="red"
        )
        axes[0, 0].set_title("GPU Utilization Distribution")
        axes[0, 0].set_xlabel("Utilization (%)")
        axes[0, 0].set_ylabel("Frequency")
        axes[0, 0].legend()
        axes[0, 0].grid(True, alpha=0.3)

        # Memory Usage distribution
        axes[0, 1].hist(
            stats1["memory_percent"], bins=20, alpha=0.5, label=label1, color="blue"
        )
        axes[0, 1].hist(
            stats2["memory_percent"], bins=20, alpha=0.5, label=label2, color="red"
        )
        axes[0, 1].set_title("Memory Usage Distribution")
        axes[0, 1].set_xlabel("Memory (%)")
        axes[0, 1].set_ylabel("Frequency")
        axes[0, 1].legend()
        axes[0, 1].grid(True, alpha=0.3)

        # Power Draw distribution
        power1_filtered = [p for p in stats1["power"] if p > 0]
        power2_filtered = [p for p in stats2["power"] if p > 0]
        if power1_filtered or power2_filtered:
            if power1_filtered:
                axes[1, 0].hist(
                    power1_filtered, bins=20, alpha=0.5, label=label1, color="blue"
                )
            if power2_filtered:
                axes[1, 0].hist(
                    power2_filtered, bins=20, alpha=0.5, label=label2, color="red"
                )
            axes[1, 0].set_title("Power Draw Distribution")
            axes[1, 0].set_xlabel("Power (W)")
            axes[1, 0].set_ylabel("Frequency")
            axes[1, 0].legend()
            axes[1, 0].grid(True, alpha=0.3)
        else:
            axes[1, 0].text(
                0.5,
                0.5,
                "Power Data\nNot Available",
                ha="center",
                va="center",
                fontsize=12,
            )
            axes[1, 0].set_xticks([])
            axes[1, 0].set_yticks([])

        # Temperature distribution (if common sensor exists)
        common_sensors = set(stats1["temp_sensors"].keys()) & set(
            stats2["temp_sensors"].keys()
        )
        if common_sensors:
            main_sensor = sorted(common_sensors)[0]
            axes[1, 1].hist(
                stats1["temp_sensors"][main_sensor],
                bins=20,
                alpha=0.5,
                label=f"{label1} - {main_sensor}",
                color="blue",
            )
            axes[1, 1].hist(
                stats2["temp_sensors"][main_sensor],
                bins=20,
                alpha=0.5,
                label=f"{label2} - {main_sensor}",
                color="red",
            )
            axes[1, 1].set_title(f"Temperature Distribution ({main_sensor})")
            axes[1, 1].set_xlabel("Temperature (°C)")
            axes[1, 1].set_ylabel("Frequency")
            axes[1, 1].legend()
            axes[1, 1].grid(True, alpha=0.3)
        else:
            axes[1, 1].text(
                0.5,
                0.5,
                "No Common\nTemperature Sensors",
                ha="center",
                va="center",
                fontsize=12,
            )
            axes[1, 1].set_xticks([])
            axes[1, 1].set_yticks([])

        plt.tight_layout()

        # Save the histogram comparison
        output_file = "gpu_comparison_histograms.png"
        plt.savefig(output_file, dpi=100, bbox_inches="tight")
        print(f"Distribution comparison saved to: {output_file}")

    def run(self):
        """Main run loop"""
        self.init_display()

        try:
            while self.running:
                Term.refresh()
                self.update_display()

                # Wait for update interval while checking for input
                start_time = time()
                while time() - start_time < self.update_interval and self.running:
                    self.handle_input()
                    sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    @staticmethod
    def load_json_safe(file_path):
        """Load JSON file with error recovery for incomplete/corrupted files"""
        with open(file_path, "r") as f:
            content = f.read()

        # First try to parse as-is
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"Warning: JSON file appears corrupted, attempting recovery...")
            print(f"  Error: {e}")

            # Try to find the last complete JSON array entry
            # Look for the last complete object by finding matching braces
            entries = []
            depth = 0
            current_entry = []
            in_string = False
            escape_next = False

            lines = content.split("\n")
            for line_num, line in enumerate(lines):
                if line_num % 10000 == 0 and line_num > 0:
                    print(f"  Processing line {line_num}...")

                for char in line:
                    if escape_next:
                        escape_next = False
                        current_entry.append(char)
                        continue

                    if char == "\\":
                        escape_next = True
                        current_entry.append(char)
                        continue

                    if char == '"' and not escape_next:
                        in_string = not in_string

                    if not in_string:
                        if char == "{":
                            if depth == 0:
                                current_entry = [char]
                            else:
                                current_entry.append(char)
                            depth += 1
                        elif char == "}":
                            depth -= 1
                            current_entry.append(char)
                            if depth == 0 and current_entry:
                                # We have a complete object
                                try:
                                    obj_str = "".join(current_entry)
                                    obj = json.loads(obj_str)
                                    entries.append(obj)
                                    current_entry = []
                                except:
                                    # This object is corrupted, skip it
                                    current_entry = []
                        else:
                            if depth > 0:
                                current_entry.append(char)
                    else:
                        if depth > 0:
                            current_entry.append(char)

            if entries:
                print(f"  Recovered {len(entries)} valid entries from corrupted file")
                return entries

            # If the above didn't work, try a more aggressive approach
            # Find all complete JSON objects using regex
            import re

            pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
            matches = re.findall(pattern, content, re.DOTALL)

            entries = []
            for match in matches:
                try:
                    obj = json.loads(match)
                    # Verify it has expected fields
                    if isinstance(obj, dict) and "timestamp" in obj:
                        entries.append(obj)
                except:
                    continue

            if entries:
                print(
                    f"  Recovered {len(entries)} valid entries using pattern matching"
                )
                return entries

            # Last resort: try to parse line by line for JSONL format
            entries = []
            for line in lines:
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict) and "timestamp" in obj:
                            entries.append(obj)
                    except:
                        continue

            if entries:
                print(f"  Recovered {len(entries)} valid entries as JSONL")
                return entries

            print("  Error: Could not recover any valid entries from file")
            return []


def main():
    """Main entry point"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="GPU monitoring tool for AMD and NVIDIA GPUs"
    )
    parser.add_argument("--stats", type=str, help="Path to stats file for logging")
    parser.add_argument(
        "--gen-graph",
        type=str,
        metavar="FILE",
        help="Generate graphs from stats JSON file and exit",
    )
    parser.add_argument(
        "--compare",
        type=str,
        nargs=2,
        metavar=("FILE1", "FILE2"),
        help="Compare two JSON stats files and visualize differences",
    )
    args = parser.parse_args()

    # Handle comparison mode
    if args.compare:
        if not MATPLOTLIB_AVAILABLE:
            print(
                "Error: matplotlib is not installed. Install it with: pip install matplotlib"
            )
            sys.exit(1)

        file1, file2 = args.compare
        file1_path = Path(file1)
        file2_path = Path(file2)

        # Check if both files exist
        if not file1_path.exists():
            print(f"Error: First stats file not found: {file1}")
            sys.exit(1)
        if not file2_path.exists():
            print(f"Error: Second stats file not found: {file2}")
            sys.exit(1)

        # Load both JSON files
        try:
            json_data1 = GPUTop.load_json_safe(file1_path)
            json_data2 = GPUTop.load_json_safe(file2_path)

            if not json_data1:
                print(f"Error: First stats file is empty: {file1}")
                sys.exit(1)
            if not json_data2:
                print(f"Error: Second stats file is empty: {file2}")
                sys.exit(1)

            # Create a GPUTop instance for comparison
            app = GPUTop()
            app.compare_and_visualize(
                json_data1, json_data2, str(file1_path), str(file2_path)
            )
            sys.exit(0)

        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse JSON file: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Error during comparison: {e}")
            sys.exit(1)

    # Handle graph generation mode
    if args.gen_graph:
        if not MATPLOTLIB_AVAILABLE:
            print(
                "Error: matplotlib is not installed. Install it with: pip install matplotlib"
            )
            sys.exit(1)

        stats_file = Path(args.gen_graph)
        if not stats_file.exists():
            print(f"Error: Stats file not found: {args.gen_graph}")
            sys.exit(1)

        # Load and generate graphs
        try:
            json_data = GPUTop.load_json_safe(stats_file)

            if not json_data:
                print("Error: Stats file is empty")
                sys.exit(1)

            # Create a temporary GPUTop instance just for graph generation
            app = GPUTop(stats_file=str(stats_file))
            app.json_data = json_data
            app.generate_graphs()
            sys.exit(0)

        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse JSON file: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Error generating graphs: {e}")
            sys.exit(1)

    # Check if any GPU is available
    monitor = GPUMonitor()
    if not monitor.initialized:
        print("Error: No supported GPU detected")
        print(
            "This tool supports AMD GPUs (via hwmon) and NVIDIA GPUs (Jetson/Desktop)"
        )
        print("Make sure your GPU drivers are properly installed")
        sys.exit(1)

    # Create .gputop directory if it doesn't exist
    stats_dir = Path.home() / ".gputop"
    stats_dir.mkdir(exist_ok=True)

    # Create stats file with timestamp
    if args.stats:
        stats_file = args.stats
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        gpu_type_str = monitor.gpu_type if monitor.gpu_type else "unknown"
        stats_file = stats_dir / f"stats-{gpu_type_str}-{timestamp}.json"

    print(f"Detected GPU type: {monitor.gpu_type}")
    print(f"Logging stats to: {stats_file}")
    print("Press CTRL-C to stop monitoring and generate graphs")
    sleep(1)

    # Run the application
    app = GPUTop(stats_file=str(stats_file))
    app.run()


if __name__ == "__main__":
    main()
