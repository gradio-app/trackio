import platform
import subprocess
import sys
import threading
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trackio.run import Run

psutil: Any = None
PSUTIL_AVAILABLE = False
_monitor_lock = threading.Lock()


def _ensure_psutil():
    global PSUTIL_AVAILABLE, psutil
    if PSUTIL_AVAILABLE:
        return psutil
    try:
        import psutil as _psutil

        psutil = _psutil
        PSUTIL_AVAILABLE = True
        return psutil
    except ImportError:
        raise ImportError(
            "psutil is required for Apple Silicon monitoring. "
            "Install it with: pip install psutil"
        )


def is_apple_silicon() -> bool:
    """Check if running on Apple Silicon (M1/M2/M3/M4)."""
    if platform.system() != "Darwin":
        return False

    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        cpu_brand = result.stdout.strip()
        return "Apple" in cpu_brand
    except Exception:
        return False


def get_gpu_info() -> dict[str, Any]:
    """Get Apple GPU information using ioreg."""
    try:
        result = subprocess.run(
            ["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"],
            capture_output=True,
            text=True,
            timeout=2,
        )

        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split("\n")
            for line in lines:
                if "IOAccelerator" in line and "class" in line:
                    return {"detected": True, "type": "Apple GPU"}
        else:
            print("Error collecting Apple GPU info. ioreg stdout was:", file=sys.stderr)
            print(result.stdout, file=sys.stderr)
            print("ioreg stderr was:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)

        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True,
            text=True,
            timeout=3,
        )

        if result.returncode == 0 and "Apple" in result.stdout:
            for line in result.stdout.split("\n"):
                if "Chipset Model:" in line:
                    model = line.split(":")[-1].strip()
                    return {"detected": True, "type": model}

    except Exception:
        pass

    return {"detected": False}


def apple_gpu_available() -> bool:
    """
    Check if Apple GPU monitoring is available.

    Returns True if running on Apple Silicon (M-series chips) and psutil is installed.
    """
    try:
        _ensure_psutil()
        return is_apple_silicon()
    except ImportError:
        return False
    except Exception:
        return False


def collect_apple_metrics() -> dict:
    """
    Collect system metrics for Apple Silicon.

    Returns:
        Dictionary of system metrics including CPU, memory, and GPU info.
    """
    if not PSUTIL_AVAILABLE:
        try:
            _ensure_psutil()
        except ImportError:
            return {}

    metrics = {}

    try:
        cpu_percent = psutil.cpu_percent(interval=0.1, percpu=False)
        metrics["cpu/utilization"] = cpu_percent
    except Exception:
        pass

    try:
        cpu_percents = psutil.cpu_percent(interval=0.1, percpu=True)
        for i, percent in enumerate(cpu_percents):
            metrics[f"cpu/{i}/utilization"] = percent
    except Exception:
        pass

    try:
        cpu_freq = psutil.cpu_freq()
        if cpu_freq:
            metrics["cpu/frequency"] = cpu_freq.current
            if cpu_freq.max > 0:
                metrics["cpu/frequency_max"] = cpu_freq.max
    except Exception:
        pass

    try:
        mem = psutil.virtual_memory()
        metrics["memory/used"] = mem.used / (1024**3)
        metrics["memory/total"] = mem.total / (1024**3)
        metrics["memory/available"] = mem.available / (1024**3)
        metrics["memory/percent"] = mem.percent
    except Exception:
        pass

    try:
        swap = psutil.swap_memory()
        metrics["swap/used"] = swap.used / (1024**3)
        metrics["swap/total"] = swap.total / (1024**3)
        metrics["swap/percent"] = swap.percent
    except Exception:
        pass

    try:
        sensors_temps = psutil.sensors_temperatures()
        if sensors_temps:
            for name, entries in sensors_temps.items():
                for i, entry in enumerate(entries):
                    label = entry.label or f"{name}_{i}"
                    metrics[f"temp/{label}"] = entry.current
    except Exception:
        pass

    gpu_info = get_gpu_info()
    if gpu_info.get("detected"):
        metrics["gpu/detected"] = 1
        if "type" in gpu_info:
            pass

    return metrics


class AppleGpuMonitor:
    def __init__(self, run: "Run", interval: float = 10.0):
        self._run = run
        self._interval = interval
        self._stop_flag = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self):
        if not is_apple_silicon():
            warnings.warn(
                "auto_log_gpu=True but not running on Apple Silicon. "
                "Apple GPU logging disabled."
            )
            return

        if not PSUTIL_AVAILABLE:
            try:
                _ensure_psutil()
            except ImportError:
                warnings.warn(
                    "auto_log_gpu=True but psutil not installed. "
                    "Install with: pip install psutil"
                )
                return

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _monitor_loop(self):
        while not self._stop_flag.is_set():
            try:
                metrics = collect_apple_metrics()
                if metrics:
                    self._run.log_system(metrics)
            except Exception:
                pass

            self._stop_flag.wait(timeout=self._interval)


def log_apple_gpu(run: "Run | None" = None) -> dict:
    """
    Log Apple Silicon system metrics to the current or specified run.

    Args:
        run: Optional Run instance. If None, uses current run from context.

    Returns:
        dict: The system metrics that were logged.

    Example:
        ```python
        import trackio

        run = trackio.init(project="my-project")
        trackio.log({"loss": 0.5})
        trackio.log_apple_gpu()
        ```
    """
    from trackio import context_vars

    if run is None:
        run = context_vars.current_run.get()
        if run is None:
            raise RuntimeError("Call trackio.init() before trackio.log_apple_gpu().")

    metrics = collect_apple_metrics()
    if metrics:
        run.log_system(metrics)
    return metrics
