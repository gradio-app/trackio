"""
GPU Dashboard for trackio-view --gpu
Exact gputop.py experience and style
"""

import os, sys, time, signal
from collections import deque
from pathlib import Path
from typing import List, Dict, Tuple, Any

# Import our GPU monitor
try:
    from trackio.gpu_monitor import GPUMonitor
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from gpu_monitor import GPUMonitor


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
    unbold = "\033[22m"
    dim = "\033[2m"

    @classmethod
    def refresh(cls):
        """Get terminal dimensions"""
        try:
            import os

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
    def gradient(value: float, colors: list) -> str:
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
    """Color theme definitions matching gputop"""

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
    title = Color.fg(255, 255, 255)
    border = Color.fg(100, 100, 100)
    text = Color.fg(180, 180, 180)
    selected = Color.fg(0, 255, 200)
    success = Color.fg(0, 255, 100)
    warning = Color.fg(255, 200, 0)
    error = Color.fg(255, 50, 50)


class Graph:
    """Graph drawing for metrics visualization"""

    def __init__(self, width: int, height: int, max_value: int = 100):
        self.width = width
        self.height = height
        self.max_value = max_value
        self.data = deque(maxlen=width)

    def add_value(self, value: float):
        """Add a new value to the graph"""
        self.data.append(value)

    def draw(self, gradient: list) -> list:
        """Draw the graph with gradient colors"""
        if not self.data:
            return [" " * self.width] * self.height

        # Normalize data
        data_list = list(self.data)
        while len(data_list) < self.width:
            data_list.insert(0, 0)

        lines = []
        for row in range(self.height):
            line = []
            threshold = (self.height - row - 1) * self.max_value / (self.height - 1)

            for col, value in enumerate(data_list):
                if value > threshold:
                    # Calculate color based on value
                    norm_value = min(value / self.max_value, 1.0)
                    color = Color.gradient(norm_value, gradient)

                    # Different characters based on value
                    if value > threshold + self.max_value / (2 * self.height):
                        char = "█"
                    else:
                        char = "▄"
                    line.append(color + char + Term.normal)
                else:
                    line.append(" ")

            lines.append("".join(line))

        return lines


class GPUDashboard:
    """GPU monitoring dashboard matching gputop UI"""

    def __init__(self):
        self.gpu_monitor = GPUMonitor()
        self.selected_gpu = 0
        self.graphs = {
            "utilization": Graph(60, 5, 100),
            "memory": Graph(60, 5, 100),
            "temperature": Graph(60, 5, 100),
            "power": Graph(60, 5, 300),
        }
        self.running = True

    def monitor_live(self, interval: int = 2):
        """Monitor GPUs live with updates"""
        # Set up terminal
        print(f"{Term.alt_screen}{Term.hide_cursor}")

        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            self.running = False
            print(f"{Term.normal_screen}{Term.show_cursor}")
            print("\n\nGPU monitoring stopped.")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)

        try:
            while self.running:
                Term.refresh()
                self.draw_display()
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        finally:
            print(f"{Term.normal_screen}{Term.show_cursor}")
            print("\n\nGPU monitoring stopped.")

    def draw_display(self):
        """Draw the complete display"""
        print(Term.clear)

        # Draw header
        self.draw_header()

        # Get current GPU stats
        stats = self.gpu_monitor.get_gpu_stats(self.selected_gpu)

        if not stats.get("available", False):
            self._center_text(Term.height // 2, "No GPUs detected", Theme.warning)
            return

        # Update graphs
        self.graphs["utilization"].add_value(stats.get("utilization", 0))
        self.graphs["memory"].add_value(stats.get("memory_percent", 0))
        self.graphs["temperature"].add_value(stats.get("temperature", 0))
        self.graphs["power"].add_value(stats.get("power", 0))

        # Draw stats
        self.draw_stats(stats)

        # Draw graphs
        self.draw_graphs()

    def draw_header(self):
        """Draw the header with title"""
        # Title banner (like gputop)
        vendor_text = ""
        if self.gpu_monitor.gpu_type:
            if "nvidia" in self.gpu_monitor.gpu_type:
                vendor_text = " (NVIDIA)"
            elif self.gpu_monitor.gpu_type == "amd":
                vendor_text = " (AMD)"

        title = f"╔═╗╔═╗╦ ╦  ╔╦╗╔═╗╔╗╔╦╔╦╗╔═╗╦═╗{vendor_text}"
        title2 = "║ ╦╠═╝║ ║  ║║║║ ║║║║║ ║ ║ ║╠╦╝"
        title3 = "╚═╝╩  ╚═╝  ╩ ╩╚═╝╝╚╝╩ ╩ ╚═╝╩╚═"

        x = (Term.width - len(title)) // 2
        y = 2

        print(f"\033[{y};{x}f" + Color.fg(0, 255, 200) + Term.bold + title)
        print(f"\033[{y+1};{x}f" + Color.fg(0, 200, 255) + title2)
        print(
            f"\033[{y+2};{x}f"
            + Color.fg(0, 150, 255)
            + title3
            + Term.unbold
            + Term.normal
        )

        # GPU selector if multiple GPUs
        if len(self.gpu_monitor.gpus) > 1:
            y = 6
            print(f"\033[{y};3f" + Theme.text + "Select GPU: ", end="")
            for i in range(len(self.gpu_monitor.gpus)):
                if i == self.selected_gpu:
                    print(Theme.selected + f"[{i}]" + Theme.text, end="")
                else:
                    print(f" {i} ", end="")

    def draw_stats(self, stats):
        """Draw current statistics"""
        y_offset = 8

        # GPU Name
        print(
            f"\033[{y_offset};3f" + Theme.title + f"GPU: {stats['name']}" + Term.normal
        )
        y_offset += 2

        # Current values box - adjust height to fit all metrics
        box_height = 14  # Increased to fit all metrics
        self._draw_box(2, y_offset, 45, box_height, "Current Values")

        line = y_offset + 2

        # Utilization
        util_color = Color.gradient(stats["utilization"] / 100, Theme.gpu_gradient)
        print(
            f"\033[{line};4f"
            + Theme.text
            + "Utilization: "
            + util_color
            + f"{stats['utilization']:5.1f}%"
            + Term.normal
        )
        line += 1

        # Memory
        mem_color = Color.gradient(stats["memory_percent"] / 100, Theme.mem_gradient)
        mem_text = f"{stats['memory_used']:.1f}/{stats['memory_total']:.1f} GB "
        mem_text += f"({stats['memory_percent']:.1f}%)"
        print(
            f"\033[{line};4f"
            + Theme.text
            + "Memory:      "
            + mem_color
            + mem_text
            + Term.normal
        )
        line += 1

        # Temperature
        temp = stats["temperature"]
        temp_normalized = min(temp / 90, 1.0)
        temp_color = Color.gradient(temp_normalized, Theme.temp_gradient)
        print(
            f"\033[{line};4f"
            + Theme.text
            + "Temperature: "
            + temp_color
            + f"{temp:5.1f}°C"
            + Term.normal
        )
        line += 1

        # Power
        if stats.get("power", 0) > 0:
            if stats.get("power_limit", 0) > 0:
                power_percent = stats["power"] / stats["power_limit"]
                power_color = Color.gradient(power_percent, Theme.gpu_gradient)
                power_text = f"{stats['power']:5.1f}/{stats['power_limit']:.0f} W"
            else:
                power_color = Color.fg(200, 200, 0)
                power_text = f"{stats['power']:5.1f} W"
            print(
                f"\033[{line};4f"
                + Theme.text
                + "Power:       "
                + power_color
                + power_text
                + Term.normal
            )
            line += 1

        # Fan Speed with RPM
        if stats.get("fan_speed", 0) > 0:
            fan_color = Color.gradient(stats["fan_speed"] / 100, Theme.gpu_gradient)
            fan_text = f"{stats['fan_speed']:5.1f}%"
            if stats.get("fan_rpm", 0) > 0:
                fan_text += f" ({stats['fan_rpm']:.0f} RPM)"
            print(
                f"\033[{line};4f"
                + Theme.text
                + "Fan Speed:   "
                + fan_color
                + fan_text
                + Term.normal
            )
            line += 1

        # Clocks
        if stats.get("clocks"):
            if "graphics" in stats["clocks"]:
                print(
                    f"\033[{line};4f"
                    + Theme.text
                    + "GPU Clock:   "
                    + Theme.warning
                    + f"{stats['clocks']['graphics']:5.0f} MHz"
                    + Term.normal
                )
                line += 1
            if "memory" in stats["clocks"]:
                print(
                    f"\033[{line};4f"
                    + Theme.text
                    + "Mem Clock:   "
                    + Theme.warning
                    + f"{stats['clocks']['memory']:5.0f} MHz"
                    + Term.normal
                )
                line += 1

        # Performance State
        if stats.get("performance_state"):
            print(
                f"\033[{line};4f"
                + Theme.text
                + "Perf State:  "
                + Theme.selected
                + stats["performance_state"]
                + Term.normal
            )

    def draw_graphs(self):
        """Draw the graphs"""
        # Calculate graph positions
        graph_x = 50
        graph_width = min(60, Term.width - graph_x - 2)
        graph_height = 5

        # Utilization graph
        y = 10
        if graph_x + graph_width + 2 <= Term.width:
            self._draw_box(
                graph_x, y, graph_width + 2, graph_height + 2, "GPU Utilization %"
            )
            util_lines = self.graphs["utilization"].draw(Theme.gpu_gradient)
            for i, line in enumerate(util_lines[:graph_height]):
                print(f"\033[{y + i + 1};{graph_x + 1}f{line}")

        # Memory graph
        y += graph_height + 2
        if (
            y + graph_height + 2 < Term.height
            and graph_x + graph_width + 2 <= Term.width
        ):
            self._draw_box(
                graph_x, y, graph_width + 2, graph_height + 2, "Memory Usage %"
            )
            mem_lines = self.graphs["memory"].draw(Theme.mem_gradient)
            for i, line in enumerate(mem_lines[:graph_height]):
                print(f"\033[{y + i + 1};{graph_x + 1}f{line}")

        # Temperature graph
        y += graph_height + 2
        if (
            y + graph_height + 2 < Term.height
            and graph_x + graph_width + 2 <= Term.width
        ):
            self._draw_box(
                graph_x, y, graph_width + 2, graph_height + 2, "Temperature °C"
            )
            temp_lines = self.graphs["temperature"].draw(Theme.temp_gradient)
            for i, line in enumerate(temp_lines[:graph_height]):
                print(f"\033[{y + i + 1};{graph_x + 1}f{line}")

        # Power graph
        y += graph_height + 2
        if (
            y + graph_height + 2 < Term.height
            and graph_x + graph_width + 2 <= Term.width
        ):
            self._draw_box(graph_x, y, graph_width + 2, graph_height + 2, "Power (W)")
            power_lines = self.graphs["power"].draw(Theme.gpu_gradient)
            for i, line in enumerate(power_lines[:graph_height]):
                print(f"\033[{y + i + 1};{graph_x + 1}f{line}")

    def _draw_box(self, x: int, y: int, w: int, h: int, title: str = ""):
        """Draw a box with optional title"""
        print(f"\033[{y};{x}f" + Theme.border + "┌", end="")
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

        print(f"\033[{y + h - 1};{x}f└" + "─" * (w - 2) + "┘")

    def _center_text(self, y: int, text: str, color: str = ""):
        """Center text on a line"""
        x = (Term.width - len(text)) // 2
        print(f"\033[{y};{x}f{color}{text}{Term.normal}")


def main():
    """Main entry point for standalone testing"""
    dashboard = GPUDashboard()
    dashboard.monitor_live()


if __name__ == "__main__":
    main()
