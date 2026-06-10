import threading
import time
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trackio.run import Run

psutil: Any = None
PSUTIL_AVAILABLE = False
_psutil_lock = threading.Lock()


def _ensure_psutil():
    global PSUTIL_AVAILABLE, psutil
    if PSUTIL_AVAILABLE:
        return psutil
    with _psutil_lock:
        if PSUTIL_AVAILABLE:
            return psutil
        try:
            import psutil as _psutil

            psutil = _psutil
            PSUTIL_AVAILABLE = True
            return psutil
        except ImportError:
            raise ImportError(
                "psutil is required for CPU and RAM monitoring. "
                "Install it with: pip install psutil"
            )


def cpu_available() -> bool:
    """
    Check if CPU and RAM monitoring is available.

    Returns True if psutil is installed.
    """
    try:
        _ensure_psutil()
        return True
    except ImportError:
        return False
    except Exception:
        return False


def collect_cpu_metrics(
    prev_disk_counters: Any = None,
    prev_net_counters: Any = None,
    elapsed: float | None = None,
    include_static: bool = True,
) -> dict:
    """
    Collect CPU, RAM, disk, network, and sensor metrics using psutil.

    Args:
        prev_disk_counters: Previous disk I/O counters for computing read/write rates.
            If None, only cumulative values are reported.
        prev_net_counters: Previous network I/O counters for computing send/recv rates.
            If None, only cumulative values are reported.
        elapsed: Seconds since prev_disk_counters and prev_net_counters were captured.
            If None or non-positive, cumulative values are reported instead of rates.
        include_static: Whether to include mostly static metrics such as CPU
            frequency and core counts.

    Returns:
        Dictionary of system metrics.
    """
    if not PSUTIL_AVAILABLE:
        try:
            _ensure_psutil()
        except ImportError:
            return {}

    metrics = {}

    try:
        per_core = psutil.cpu_percent(interval=0.1, percpu=True)
        for i, pct in enumerate(per_core):
            metrics[f"cpu/{i}/utilization"] = pct
        if per_core:
            metrics["cpu/utilization"] = sum(per_core) / len(per_core)
    except Exception:
        pass

    if include_static:
        try:
            cpu_freq = psutil.cpu_freq()
            if cpu_freq:
                metrics["cpu/frequency"] = cpu_freq.current
                if cpu_freq.max > 0:
                    metrics["cpu/frequency_max"] = cpu_freq.max
        except Exception:
            pass

        try:
            cpu_count_logical = psutil.cpu_count(logical=True)
            if cpu_count_logical is not None:
                metrics["cpu/count_logical"] = cpu_count_logical
            cpu_count_physical = psutil.cpu_count(logical=False)
            if cpu_count_physical is not None:
                metrics["cpu/count_physical"] = cpu_count_physical
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
        disk = psutil.disk_io_counters()
        if disk is not None:
            if prev_disk_counters is not None and elapsed and elapsed > 0:
                metrics["disk/read_mb_per_sec"] = (
                    (disk.read_bytes - prev_disk_counters.read_bytes)
                    / elapsed
                    / (1024**2)
                )
                metrics["disk/write_mb_per_sec"] = (
                    (disk.write_bytes - prev_disk_counters.write_bytes)
                    / elapsed
                    / (1024**2)
                )
                metrics["disk/read_iops"] = (
                    disk.read_count - prev_disk_counters.read_count
                ) / elapsed
                metrics["disk/write_iops"] = (
                    disk.write_count - prev_disk_counters.write_count
                ) / elapsed
            else:
                metrics["disk/read_bytes"] = disk.read_bytes / (1024**3)
                metrics["disk/write_bytes"] = disk.write_bytes / (1024**3)
    except Exception:
        pass

    try:
        net = psutil.net_io_counters()
        if net is not None:
            if prev_net_counters is not None and elapsed and elapsed > 0:
                metrics["network/sent_mb_per_sec"] = (
                    (net.bytes_sent - prev_net_counters.bytes_sent)
                    / elapsed
                    / (1024**2)
                )
                metrics["network/recv_mb_per_sec"] = (
                    (net.bytes_recv - prev_net_counters.bytes_recv)
                    / elapsed
                    / (1024**2)
                )
            else:
                metrics["network/sent_bytes"] = net.bytes_sent / (1024**3)
                metrics["network/recv_bytes"] = net.bytes_recv / (1024**3)
    except Exception:
        pass

    try:
        sensors = psutil.sensors_temperatures()
        if sensors:
            for chip_name, entries in sensors.items():
                for i, entry in enumerate(entries):
                    label = (
                        entry.label.strip()
                        if entry.label and entry.label.strip()
                        else f"{chip_name}_{i}"
                    )
                    metrics[f"temp/{label}"] = entry.current
    except Exception:
        pass

    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            metrics["battery/percent"] = battery.percent
            metrics["battery/power_plugged"] = int(battery.power_plugged)
    except Exception:
        pass

    return metrics


class CpuMonitor:
    def __init__(self, run: "Run", interval: float = 10.0):
        self._run = run
        self._interval = interval
        self._stop_flag = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._last_disk_counters: Any = None
        self._last_net_counters: Any = None
        self._last_time: float | None = None

    def start(self):
        if not PSUTIL_AVAILABLE:
            try:
                _ensure_psutil()
            except ImportError:
                warnings.warn(
                    "auto_log_cpu=True but psutil is not installed. "
                    "CPU and RAM logging disabled. Install with: pip install psutil"
                )
                return

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _monitor_loop(self):
        try:
            self._last_disk_counters = psutil.disk_io_counters()
        except Exception:
            pass
        try:
            self._last_net_counters = psutil.net_io_counters()
        except Exception:
            pass
        self._last_time = time.monotonic()

        while not self._stop_flag.is_set():
            self._stop_flag.wait(timeout=self._interval)
            if self._stop_flag.is_set():
                break
            try:
                now = time.monotonic()
                elapsed = now - self._last_time if self._last_time is not None else None
                metrics = collect_cpu_metrics(
                    prev_disk_counters=self._last_disk_counters,
                    prev_net_counters=self._last_net_counters,
                    elapsed=elapsed,
                    include_static=False,
                )
                try:
                    self._last_disk_counters = psutil.disk_io_counters()
                except Exception:
                    self._last_disk_counters = None
                try:
                    self._last_net_counters = psutil.net_io_counters()
                except Exception:
                    self._last_net_counters = None
                self._last_time = now
                if metrics:
                    self._run.log_system(metrics)
            except Exception:
                pass


def log_cpu(run: "Run | None" = None) -> dict:
    """
    Log CPU, RAM, disk, network, and sensor metrics to the current or specified run
    as system metrics.

    Args:
        run: Optional Run instance. If None, uses current run from context.

    Returns:
        dict: The system metrics that were logged.

    Example:
        ```python
        import trackio

        run = trackio.init(project="my-project")
        trackio.log({"loss": 0.5})
        trackio.log_cpu()
        ```
    """
    from trackio import context_vars

    if run is None:
        run = context_vars.current_run.get()
        if run is None:
            raise RuntimeError("Call trackio.init() before trackio.log_cpu().")

    try:
        _ensure_psutil()
    except ImportError:
        warnings.warn(
            "trackio.log_cpu() requires psutil. Install it with: pip install trackio[cpu]"
        )
        return {}

    metrics = collect_cpu_metrics()
    if metrics:
        run.log_system(metrics)
    return metrics
