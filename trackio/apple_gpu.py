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


def collect_apple_metrics(include_cpu_metrics: bool = True) -> dict:
    """
    Collect system metrics for Apple Silicon.

    Returns:
        Dictionary of system metrics including CPU, memory, and GPU info.
    """
    metrics = {}

    if include_cpu_metrics:
        from trackio.cpu import collect_cpu_metrics

        metrics.update(collect_cpu_metrics(include_static=True))

    gpu_info = get_gpu_info()
    if gpu_info.get("detected"):
        metrics["gpu/detected"] = 1

    return metrics


class AppleGpuMonitor:
    def __init__(
        self, run: "Run", interval: float = 10.0, include_cpu_metrics: bool = True
    ):
        self._run = run
        self._interval = interval
        self._include_cpu_metrics = include_cpu_metrics
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
                metrics = collect_apple_metrics(
                    include_cpu_metrics=self._include_cpu_metrics
                )
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
