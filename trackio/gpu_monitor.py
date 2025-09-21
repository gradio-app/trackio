"""
GPU monitoring module for TrackIO
Based on gputop - vendor-agnostic GPU monitoring
Supports NVIDIA (desktop & Jetson), AMD, and Intel GPUs
"""

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any

# Try to import pynvml for NVIDIA desktop GPU support
try:
    import pynvml

    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False


class GPUMonitor:
    """Lightweight GPU monitoring for TrackIO"""

    def __init__(self):
        self.gpus = []
        self.gpu_type = None  # 'amd', 'nvidia_jetson', or 'nvidia_desktop'
        self.initialized = False

        # For NVIDIA Jetson tegrastats monitoring
        self.tegrastats_process = None
        self.tegrastats_data = {}

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

    def _discover_nvidia_jetson(self) -> bool:
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
                    }
                )
                self.initialized = True
                return True
        except:
            pass
        return False

    def _discover_nvidia_desktop(self) -> bool:
        """Discover desktop NVIDIA GPU using nvidia-ml-py"""
        if not PYNVML_AVAILABLE:
            return False

        try:
            pynvml.nvmlInit()
            gpu_count = pynvml.nvmlDeviceGetCount()

            for i in range(gpu_count):
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

    def _discover_amd(self) -> bool:
        """Discover AMD GPUs through /sys/class/drm"""
        try:
            drm_path = Path("/sys/class/drm")
            for card_path in sorted(drm_path.glob("card[0-9]*")):
                # Skip render nodes
                if "render" in card_path.name:
                    continue

                device_path = card_path / "device"

                # Check for AMD GPU vendor ID
                vendor_path = device_path / "vendor"
                if not vendor_path.exists():
                    continue

                with open(vendor_path, "r") as f:
                    vendor_id = f.read().strip()

                # AMD vendor ID is 0x1002
                if vendor_id != "0x1002":
                    continue

                # Find hwmon directory
                hwmon_dir = device_path / "hwmon"
                if not hwmon_dir.exists():
                    continue

                hwmon_dirs = list(hwmon_dir.iterdir())
                if not hwmon_dirs:
                    continue

                hwmon_path = hwmon_dirs[0]

                # Get GPU name
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
                    }
                )

            if self.gpus:
                self.initialized = True
                return True
        except:
            pass
        return False

    def _get_jetson_name(self) -> str:
        """Get NVIDIA Jetson model name"""
        try:
            model_path = Path("/sys/firmware/devicetree/base/model")
            if model_path.exists():
                with open(model_path, "r") as f:
                    model = f.read().strip("\x00")
                    if "Jetson" in model:
                        return model
            return "NVIDIA Jetson GPU"
        except:
            return "NVIDIA GPU"

    def _get_amd_gpu_name(self, device_path: Path) -> str:
        """Get AMD GPU name from device information"""
        try:
            device_id_path = device_path / "device"
            if device_id_path.exists():
                with open(device_id_path, "r") as f:
                    device_id = f.read().strip()

                # Map common AMD GPU device IDs
                amd_gpus = {
                    "0x73df": "AMD Radeon RX 6750 XT",
                    "0x744c": "AMD Radeon RX 7900 XTX",
                    "0x745f": "AMD Radeon RX 7900 XT",
                    "0x7448": "AMD Radeon Pro W7900",
                }
                return amd_gpus.get(device_id, f"AMD GPU ({device_id})")
            return "AMD GPU"
        except:
            return "Unknown AMD GPU"

    def get_gpu_stats(self, gpu_index: int = 0) -> Dict[str, Any]:
        """Get stats for a specific GPU"""
        if not self.initialized or gpu_index >= len(self.gpus):
            return {
                "available": False,
                "name": "No GPU",
                "utilization": 0,
                "memory_used": 0,
                "memory_total": 0,
                "memory_percent": 0,
                "temperature": 0,
                "power": 0,
            }

        gpu = self.gpus[gpu_index]

        if gpu["type"] == "nvidia_jetson":
            return self._get_nvidia_jetson_stats(gpu)
        elif gpu["type"] == "nvidia_desktop":
            return self._get_nvidia_desktop_stats(gpu)
        elif gpu["type"] == "amd":
            return self._get_amd_stats(gpu)

    def _get_nvidia_jetson_stats(self, gpu: Dict) -> Dict[str, Any]:
        """Get stats for NVIDIA Jetson GPU"""
        stats = {
            "available": True,
            "name": gpu["name"],
            "utilization": 0,
            "memory_used": 0,
            "memory_total": 0,
            "memory_percent": 0,
            "temperature": 0,
            "power": 0,
        }

        try:
            # Get GPU utilization
            if gpu["load_path"].exists():
                with open(gpu["load_path"], "r") as f:
                    load = int(f.read().strip())
                    stats["utilization"] = load / 10  # Convert from 0-1000 to 0-100

            # Get GPU temperature from thermal zone
            temp_path = Path("/sys/class/thermal/thermal_zone2/temp")
            if temp_path.exists():
                with open(temp_path, "r") as f:
                    temp = int(f.read().strip())
                    stats["temperature"] = temp / 1000  # Convert from millicelsius
        except:
            pass

        return stats

    def _get_nvidia_desktop_stats(self, gpu: Dict) -> Dict[str, Any]:
        """Get stats for desktop NVIDIA GPU using nvidia-ml-py"""
        stats = {
            "available": True,
            "name": gpu["name"],
            "utilization": 0,
            "memory_used": 0,
            "memory_total": 0,
            "memory_percent": 0,
            "temperature": 0,
            "power": 0,
            "power_limit": 0,
            "fan_speed": 0,
            "clocks": {},
            "performance_state": "",
        }

        if not PYNVML_AVAILABLE:
            return stats

        try:
            handle = gpu["handle"]

            # GPU utilization
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            stats["utilization"] = util.gpu

            # Memory info
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            stats["memory_used"] = mem_info.used / (1024**3)  # Convert to GB
            stats["memory_total"] = mem_info.total / (1024**3)  # Convert to GB
            stats["memory_percent"] = (mem_info.used / mem_info.total) * 100

            # Temperature
            try:
                temp = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
                stats["temperature"] = temp
            except:
                pass

            # Power
            try:
                power = pynvml.nvmlDeviceGetPowerUsage(handle)
                stats["power"] = power / 1000  # Convert from milliwatts to watts

                # Power limit
                power_limit = pynvml.nvmlDeviceGetPowerManagementLimit(handle)
                stats["power_limit"] = power_limit / 1000
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
                stats["clocks"] = {
                    "graphics": graphics_clock,
                    "memory": memory_clock,
                }
            except:
                pass

            # Performance state
            try:
                pstate = pynvml.nvmlDeviceGetPerformanceState(handle)
                stats["performance_state"] = f"P{pstate}"
            except:
                pass

        except Exception as e:
            pass

        return stats

    def _get_amd_stats(self, gpu: Dict) -> Dict[str, Any]:
        """Get stats for AMD GPU using hwmon"""
        stats = {
            "available": True,
            "name": gpu["name"],
            "utilization": 0,
            "memory_used": 0,
            "memory_total": 0,
            "memory_percent": 0,
            "temperature": 0,
            "power": 0,
            "power_limit": 0,
            "fan_speed": 0,
            "clocks": {},
            "performance_state": "",
        }

        try:
            hwmon = gpu["hwmon_path"]
            device = gpu["device_path"]

            # GPU utilization (gpu_busy_percent)
            util_path = device / "gpu_busy_percent"
            if util_path.exists():
                with open(util_path, "r") as f:
                    stats["utilization"] = int(f.read().strip())

            # Memory info
            mem_used_path = device / "mem_info_vram_used"
            mem_total_path = device / "mem_info_vram_total"

            if mem_used_path.exists() and mem_total_path.exists():
                with open(mem_used_path, "r") as f:
                    mem_used = int(f.read().strip())
                    stats["memory_used"] = mem_used / (1024**3)  # Convert to GB

                with open(mem_total_path, "r") as f:
                    mem_total = int(f.read().strip())
                    stats["memory_total"] = mem_total / (1024**3)  # Convert to GB

                if mem_total > 0:
                    stats["memory_percent"] = (mem_used / mem_total) * 100

            # Temperature
            temp_path = hwmon / "temp1_input"
            if temp_path.exists():
                with open(temp_path, "r") as f:
                    temp = int(f.read().strip())
                    stats["temperature"] = temp / 1000  # Convert from millicelsius

            # Power
            power_path = hwmon / "power1_average"
            if power_path.exists():
                with open(power_path, "r") as f:
                    power = int(f.read().strip())
                    stats["power"] = power / 1000000  # Convert from microwatts to watts

            # Power limit
            power_cap_path = hwmon / "power1_cap"
            if power_cap_path.exists():
                with open(power_cap_path, "r") as f:
                    power_cap = int(f.read().strip())
                    stats["power_limit"] = power_cap / 1000000

            # Fan speed - try multiple possible paths
            fan_paths = [
                hwmon / "fan1_input",  # RPM reading
                hwmon / "pwm1",  # PWM control
            ]

            for fan_path in fan_paths:
                if fan_path.exists():
                    with open(fan_path, "r") as f:
                        value = int(f.read().strip())
                        if "fan1_input" in str(fan_path):
                            # This is RPM, convert to percentage (assume max 3000 RPM)
                            max_rpm = 3000
                            # Try to read actual max if available
                            fan_max_path = hwmon / "fan1_max"
                            if fan_max_path.exists():
                                with open(fan_max_path, "r") as fm:
                                    max_rpm = int(fm.read().strip())
                            stats["fan_speed"] = min(100, (value / max_rpm) * 100)
                            stats["fan_rpm"] = value  # Also store actual RPM
                        else:
                            # This is PWM (0-255)
                            stats["fan_speed"] = (value / 255) * 100
                    break

            # GPU clocks - try hwmon first (more reliable)
            gpu_freq_path = hwmon / "freq1_input"
            if gpu_freq_path.exists():
                with open(gpu_freq_path, "r") as f:
                    freq_hz = int(f.read().strip())
                    stats["clocks"]["graphics"] = freq_hz / 1000000  # Convert Hz to MHz
            else:
                # Fallback to pp_dpm_sclk
                freq_path = device / "pp_dpm_sclk"
                if freq_path.exists():
                    with open(freq_path, "r") as f:
                        lines = f.readlines()
                        for line in lines:
                            if "*" in line:  # Current active frequency
                                freq = int(line.split()[1].replace("Mhz", ""))
                                stats["clocks"]["graphics"] = freq
                                break

            # Memory clock
            mem_freq_path = hwmon / "freq2_input"
            if mem_freq_path.exists():
                with open(mem_freq_path, "r") as f:
                    freq_hz = int(f.read().strip())
                    stats["clocks"]["memory"] = freq_hz / 1000000  # Convert Hz to MHz
            else:
                # Fallback to pp_dpm_mclk
                mem_freq_path = device / "pp_dpm_mclk"
                if mem_freq_path.exists():
                    with open(mem_freq_path, "r") as f:
                        lines = f.readlines()
                        for line in lines:
                            if "*" in line:
                                freq = int(line.split()[1].replace("Mhz", ""))
                                stats["clocks"]["memory"] = freq
                                break

            # Fabric clock (fclk) - AMD specific
            fclk_path = device / "pp_dpm_fclk"
            if fclk_path.exists():
                with open(fclk_path, "r") as f:
                    lines = f.readlines()
                    for line in lines:
                        if "*" in line:  # Current active frequency
                            freq = int(line.split()[1].replace("Mhz", ""))
                            stats["clocks"]["fclk"] = freq
                            break

            # SoC clock (socclk) - AMD specific
            socclk_path = device / "pp_dpm_socclk"
            if socclk_path.exists():
                with open(socclk_path, "r") as f:
                    lines = f.readlines()
                    for line in lines:
                        if "*" in line:  # Current active frequency
                            freq = int(line.split()[1].replace("Mhz", ""))
                            stats["clocks"]["socclk"] = freq
                            break

            # Performance level
            perf_path = device / "power_dpm_force_performance_level"
            if perf_path.exists():
                with open(perf_path, "r") as f:
                    stats["performance_state"] = f.read().strip()

        except Exception as e:
            pass

        return stats

    def get_all_gpu_stats(self) -> List[Dict[str, Any]]:
        """Get stats for all GPUs"""
        stats = []
        for i in range(len(self.gpus)):
            stats.append(self.get_gpu_stats(i))
        return stats

    def cleanup(self):
        """Cleanup resources"""
        if PYNVML_AVAILABLE and self.gpu_type == "nvidia_desktop":
            try:
                pynvml.nvmlShutdown()
            except:
                pass
