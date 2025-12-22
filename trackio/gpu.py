import threading
import time
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trackio.run import Run

pynvml = None
PYNVML_AVAILABLE = False
_nvml_initialized = False
_nvml_lock = threading.Lock()
_energy_baseline: dict[int, float] = {}


def _ensure_pynvml():
    global PYNVML_AVAILABLE, pynvml
    if PYNVML_AVAILABLE:
        return pynvml
    try:
        import pynvml as _pynvml

        pynvml = _pynvml
        PYNVML_AVAILABLE = True
        return pynvml
    except ImportError:
        raise ImportError(
            "nvidia-ml-py is required for GPU monitoring. "
            "Install it with: pip install nvidia-ml-py"
        )


def _init_nvml() -> bool:
    global _nvml_initialized
    with _nvml_lock:
        if _nvml_initialized:
            return True
        try:
            nvml = _ensure_pynvml()
            nvml.nvmlInit()
            _nvml_initialized = True
            return True
        except Exception:
            return False


def _shutdown_nvml():
    global _nvml_initialized
    with _nvml_lock:
        if _nvml_initialized and pynvml is not None:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
            _nvml_initialized = False


def get_gpu_count() -> int:
    if not _init_nvml():
        return 0
    try:
        return pynvml.nvmlDeviceGetCount()
    except Exception:
        return 0


def gpu_available() -> bool:
    """
    Check if GPU monitoring is available.

    Returns True if nvidia-ml-py is installed and at least one NVIDIA GPU is detected.
    This is used for auto-detection of GPU logging.
    """
    try:
        _ensure_pynvml()
        return get_gpu_count() > 0
    except ImportError:
        return False
    except Exception:
        return False


def reset_energy_baseline():
    """Reset the energy baseline for all GPUs. Called when a new run starts."""
    global _energy_baseline
    _energy_baseline = {}


def collect_gpu_metrics() -> dict:
    if not _init_nvml():
        return {}

    gpu_count = get_gpu_count()
    if gpu_count == 0:
        return {}

    metrics = {}
    total_util = 0.0
    total_mem_used_gib = 0.0
    total_power = 0.0
    max_temp = 0.0
    valid_util_count = 0

    for i in range(gpu_count):
        prefix = f"gpu/{i}"
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)

            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                metrics[f"{prefix}/utilization"] = util.gpu
                metrics[f"{prefix}/memoryUtilization"] = util.memory
                total_util += util.gpu
                valid_util_count += 1
            except Exception:
                pass

            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                mem_used_gib = mem.used / (1024**3)
                mem_total_gib = mem.total / (1024**3)
                metrics[f"{prefix}/memoryUsedGiB"] = mem_used_gib
                metrics[f"{prefix}/memoryTotalGiB"] = mem_total_gib
                if mem.total > 0:
                    metrics[f"{prefix}/memoryAllocated"] = (mem.used / mem.total) * 100
                total_mem_used_gib += mem_used_gib
            except Exception:
                pass

            try:
                power_mw = pynvml.nvmlDeviceGetPowerUsage(handle)
                power_w = power_mw / 1000.0
                metrics[f"{prefix}/powerWatts"] = power_w
                total_power += power_w
            except Exception:
                pass

            try:
                power_limit_mw = pynvml.nvmlDeviceGetPowerManagementLimit(handle)
                power_limit_w = power_limit_mw / 1000.0
                metrics[f"{prefix}/powerLimitWatts"] = power_limit_w
                if power_limit_w > 0 and f"{prefix}/powerWatts" in metrics:
                    metrics[f"{prefix}/powerPercent"] = (
                        metrics[f"{prefix}/powerWatts"] / power_limit_w
                    ) * 100
            except Exception:
                pass

            try:
                temp = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
                metrics[f"{prefix}/temp"] = temp
                max_temp = max(max_temp, temp)
            except Exception:
                pass

            try:
                sm_clock = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM)
                metrics[f"{prefix}/smClock"] = sm_clock
            except Exception:
                pass

            try:
                mem_clock = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
                metrics[f"{prefix}/memoryClock"] = mem_clock
            except Exception:
                pass

            try:
                fan_speed = pynvml.nvmlDeviceGetFanSpeed(handle)
                metrics[f"{prefix}/fanSpeed"] = fan_speed
            except Exception:
                pass

            try:
                pstate = pynvml.nvmlDeviceGetPerformanceState(handle)
                metrics[f"{prefix}/performanceState"] = pstate
            except Exception:
                pass

            try:
                energy_mj = pynvml.nvmlDeviceGetTotalEnergyConsumption(handle)
                if i not in _energy_baseline:
                    _energy_baseline[i] = energy_mj
                energy_consumed_mj = energy_mj - _energy_baseline[i]
                metrics[f"{prefix}/energyConsumedJoules"] = energy_consumed_mj / 1000.0
            except Exception:
                pass

            try:
                pcie_tx = pynvml.nvmlDeviceGetPcieThroughput(
                    handle, pynvml.NVML_PCIE_UTIL_TX_BYTES
                )
                pcie_rx = pynvml.nvmlDeviceGetPcieThroughput(
                    handle, pynvml.NVML_PCIE_UTIL_RX_BYTES
                )
                metrics[f"{prefix}/pcieTxMBps"] = pcie_tx / 1024.0
                metrics[f"{prefix}/pcieRxMBps"] = pcie_rx / 1024.0
            except Exception:
                pass

            try:
                throttle = pynvml.nvmlDeviceGetCurrentClocksThrottleReasons(handle)
                metrics[f"{prefix}/throttleThermal"] = int(
                    bool(throttle & pynvml.nvmlClocksThrottleReasonSwThermalSlowdown)
                )
                metrics[f"{prefix}/throttlePower"] = int(
                    bool(throttle & pynvml.nvmlClocksThrottleReasonSwPowerCap)
                )
                metrics[f"{prefix}/throttleHwSlowdown"] = int(
                    bool(throttle & pynvml.nvmlClocksThrottleReasonHwSlowdown)
                )
                metrics[f"{prefix}/throttleApps"] = int(
                    bool(
                        throttle
                        & pynvml.nvmlClocksThrottleReasonApplicationsClocksSetting
                    )
                )
            except Exception:
                pass

            try:
                ecc_corrected = pynvml.nvmlDeviceGetTotalEccErrors(
                    handle,
                    pynvml.NVML_MEMORY_ERROR_TYPE_CORRECTED,
                    pynvml.NVML_VOLATILE_ECC,
                )
                metrics[f"{prefix}/correctedMemoryErrors"] = ecc_corrected
            except Exception:
                pass

            try:
                ecc_uncorrected = pynvml.nvmlDeviceGetTotalEccErrors(
                    handle,
                    pynvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED,
                    pynvml.NVML_VOLATILE_ECC,
                )
                metrics[f"{prefix}/uncorrectedMemoryErrors"] = ecc_uncorrected
            except Exception:
                pass

        except Exception:
            continue

    if valid_util_count > 0:
        metrics["gpu/meanUtilization"] = total_util / valid_util_count
    if total_mem_used_gib > 0:
        metrics["gpu/totalMemoryGiB"] = total_mem_used_gib
    if total_power > 0:
        metrics["gpu/totalPowerWatts"] = total_power
    if max_temp > 0:
        metrics["gpu/maxTemp"] = max_temp

    return metrics


class GpuMonitor:
    def __init__(self, run: "Run", interval: float = 10.0):
        self._run = run
        self._interval = interval
        self._stop_flag = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self):
        if get_gpu_count() == 0:
            warnings.warn(
                "auto_log_gpu=True but no NVIDIA GPUs detected. GPU logging disabled."
            )
            return

        reset_energy_baseline()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _monitor_loop(self):
        while not self._stop_flag.is_set():
            try:
                metrics = collect_gpu_metrics()
                if metrics:
                    self._run.log(metrics)
            except Exception:
                pass

            self._stop_flag.wait(timeout=self._interval)


def log_gpu(run: "Run | None" = None) -> dict:
    """
    Log GPU metrics to the current or specified run.

    Args:
        run: Optional Run instance. If None, uses current run from context.

    Returns:
        dict: The GPU metrics that were logged.

    Example:
        ```python
        import trackio

        run = trackio.init(project="my-project")
        trackio.log({"loss": 0.5})
        trackio.log_gpu()
        ```
    """
    from trackio import context_vars

    if run is None:
        run = context_vars.current_run.get()
        if run is None:
            raise RuntimeError("Call trackio.init() before trackio.log_gpu().")

    metrics = collect_gpu_metrics()
    if metrics:
        run.log(metrics)
    return metrics
