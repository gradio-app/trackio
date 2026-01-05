import os
import threading
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trackio.run import Run

pynvml: Any = None
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


def get_gpu_count() -> tuple[int, list[int]]:
    """
    Get the number of GPUs visible to this process and their physical indices.
    Respects CUDA_VISIBLE_DEVICES environment variable.

    Returns:
        Tuple of (count, physical_indices) where:
        - count: Number of visible GPUs
        - physical_indices: List mapping logical index to physical GPU index.
          e.g., if CUDA_VISIBLE_DEVICES=2,3 returns (2, [2, 3])
          meaning logical GPU 0 = physical GPU 2, logical GPU 1 = physical GPU 3
    """
    if not _init_nvml():
        return 0, []

    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cuda_visible is not None and cuda_visible.strip():
        try:
            indices = [int(x.strip()) for x in cuda_visible.split(",") if x.strip()]
            return len(indices), indices
        except ValueError:
            pass

    try:
        total = pynvml.nvmlDeviceGetCount()
        return total, list(range(total))
    except Exception:
        return 0, []


def gpu_available() -> bool:
    """
    Check if GPU monitoring is available.

    Returns True if nvidia-ml-py is installed and at least one NVIDIA GPU is detected.
    This is used for auto-detection of GPU logging.
    """
    try:
        _ensure_pynvml()
        count, _ = get_gpu_count()
        return count > 0
    except ImportError:
        return False
    except Exception:
        return False


def reset_energy_baseline():
    """Reset the energy baseline for all GPUs. Called when a new run starts."""
    global _energy_baseline
    _energy_baseline = {}


def collect_gpu_metrics(device: int | None = None) -> dict:
    """
    Collect GPU metrics for visible GPUs.

    Args:
        device: CUDA device index to collect metrics from. If None, collects
                from all GPUs visible to this process (respects CUDA_VISIBLE_DEVICES).
                The device index is the logical CUDA index (0, 1, 2...), not the
                physical GPU index.

    Returns:
        Dictionary of GPU metrics. Keys use logical device indices (gpu/0/, gpu/1/, etc.)
        which correspond to CUDA device indices, not physical GPU indices.
    """
    if not _init_nvml():
        return {}

    gpu_count, visible_gpus = get_gpu_count()
    if gpu_count == 0:
        return {}

    if device is not None:
        if device < 0 or device >= gpu_count:
            return {}
        gpu_indices = [(device, visible_gpus[device])]
    else:
        gpu_indices = list(enumerate(visible_gpus))

    metrics = {}
    total_util = 0.0
    total_mem_used_gib = 0.0
    total_power = 0.0
    max_temp = 0.0
    valid_util_count = 0

    for logical_idx, physical_idx in gpu_indices:
        prefix = f"gpu/{logical_idx}"
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(physical_idx)

            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                metrics[f"{prefix}/utilization"] = util.gpu
                metrics[f"{prefix}/memory_utilization"] = util.memory
                total_util += util.gpu
                valid_util_count += 1
            except Exception:
                pass

            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                mem_used_gib = mem.used / (1024**3)
                mem_total_gib = mem.total / (1024**3)
                metrics[f"{prefix}/allocated_memory"] = mem_used_gib
                metrics[f"{prefix}/total_memory"] = mem_total_gib
                if mem.total > 0:
                    metrics[f"{prefix}/memory_usage"] = mem.used / mem.total
                total_mem_used_gib += mem_used_gib
            except Exception:
                pass

            try:
                power_mw = pynvml.nvmlDeviceGetPowerUsage(handle)
                power_w = power_mw / 1000.0
                metrics[f"{prefix}/power"] = power_w
                total_power += power_w
            except Exception:
                pass

            try:
                power_limit_mw = pynvml.nvmlDeviceGetPowerManagementLimit(handle)
                power_limit_w = power_limit_mw / 1000.0
                metrics[f"{prefix}/power_limit"] = power_limit_w
                if power_limit_w > 0 and f"{prefix}/power" in metrics:
                    metrics[f"{prefix}/power_percent"] = (
                        metrics[f"{prefix}/power"] / power_limit_w
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
                metrics[f"{prefix}/sm_clock"] = sm_clock
            except Exception:
                pass

            try:
                mem_clock = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
                metrics[f"{prefix}/memory_clock"] = mem_clock
            except Exception:
                pass

            try:
                fan_speed = pynvml.nvmlDeviceGetFanSpeed(handle)
                metrics[f"{prefix}/fan_speed"] = fan_speed
            except Exception:
                pass

            try:
                pstate = pynvml.nvmlDeviceGetPerformanceState(handle)
                metrics[f"{prefix}/performance_state"] = pstate
            except Exception:
                pass

            try:
                energy_mj = pynvml.nvmlDeviceGetTotalEnergyConsumption(handle)
                if logical_idx not in _energy_baseline:
                    _energy_baseline[logical_idx] = energy_mj
                energy_consumed_mj = energy_mj - _energy_baseline[logical_idx]
                metrics[f"{prefix}/energy_consumed"] = energy_consumed_mj / 1000.0
            except Exception:
                pass

            try:
                pcie_tx = pynvml.nvmlDeviceGetPcieThroughput(
                    handle, pynvml.NVML_PCIE_UTIL_TX_BYTES
                )
                pcie_rx = pynvml.nvmlDeviceGetPcieThroughput(
                    handle, pynvml.NVML_PCIE_UTIL_RX_BYTES
                )
                metrics[f"{prefix}/pcie_tx"] = pcie_tx / 1024.0
                metrics[f"{prefix}/pcie_rx"] = pcie_rx / 1024.0
            except Exception:
                pass

            try:
                throttle = pynvml.nvmlDeviceGetCurrentClocksThrottleReasons(handle)
                metrics[f"{prefix}/throttle_thermal"] = int(
                    bool(throttle & pynvml.nvmlClocksThrottleReasonSwThermalSlowdown)
                )
                metrics[f"{prefix}/throttle_power"] = int(
                    bool(throttle & pynvml.nvmlClocksThrottleReasonSwPowerCap)
                )
                metrics[f"{prefix}/throttle_hw_slowdown"] = int(
                    bool(throttle & pynvml.nvmlClocksThrottleReasonHwSlowdown)
                )
                metrics[f"{prefix}/throttle_apps"] = int(
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
                metrics[f"{prefix}/corrected_memory_errors"] = ecc_corrected
            except Exception:
                pass

            try:
                ecc_uncorrected = pynvml.nvmlDeviceGetTotalEccErrors(
                    handle,
                    pynvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED,
                    pynvml.NVML_VOLATILE_ECC,
                )
                metrics[f"{prefix}/uncorrected_memory_errors"] = ecc_uncorrected
            except Exception:
                pass

        except Exception:
            continue

    if valid_util_count > 0:
        metrics["gpu/mean_utilization"] = total_util / valid_util_count
    if total_mem_used_gib > 0:
        metrics["gpu/total_allocated_memory"] = total_mem_used_gib
    if total_power > 0:
        metrics["gpu/total_power"] = total_power
    if max_temp > 0:
        metrics["gpu/max_temp"] = max_temp

    return metrics


class GpuMonitor:
    def __init__(self, run: "Run", interval: float = 10.0):
        self._run = run
        self._interval = interval
        self._stop_flag = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self):
        count, _ = get_gpu_count()
        if count == 0:
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
                    self._run.log_system(metrics)
            except Exception:
                pass

            self._stop_flag.wait(timeout=self._interval)


def log_gpu(run: "Run | None" = None, device: int | None = None) -> dict:
    """
    Log GPU metrics to the current or specified run as system metrics.

    Args:
        run: Optional Run instance. If None, uses current run from context.
        device: CUDA device index to collect metrics from. If None, collects
                from all GPUs visible to this process (respects CUDA_VISIBLE_DEVICES).

    Returns:
        dict: The GPU metrics that were logged.

    Example:
        ```python
        import trackio

        run = trackio.init(project="my-project")
        trackio.log({"loss": 0.5})
        trackio.log_gpu()  # logs all visible GPUs
        trackio.log_gpu(device=0)  # logs only CUDA device 0
        ```
    """
    from trackio import context_vars

    if run is None:
        run = context_vars.current_run.get()
        if run is None:
            raise RuntimeError("Call trackio.init() before trackio.log_gpu().")

    metrics = collect_gpu_metrics(device=device)
    if metrics:
        run.log_system(metrics)
    return metrics
