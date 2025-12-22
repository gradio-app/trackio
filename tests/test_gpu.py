import time
from unittest.mock import MagicMock, patch

import pytest


def test_log_gpu_without_pynvml():
    with patch.dict("sys.modules", {"pynvml": None}):
        from trackio import gpu

        gpu.PYNVML_AVAILABLE = False
        gpu.pynvml = None

        with pytest.raises(ImportError, match="nvidia-ml-py is required"):
            gpu._ensure_pynvml()


def test_get_gpu_count_no_nvml():
    from trackio import gpu

    with patch.object(gpu, "_init_nvml", return_value=False):
        assert gpu.get_gpu_count() == 0


def test_collect_gpu_metrics_no_nvml():
    from trackio import gpu

    with patch.object(gpu, "_init_nvml", return_value=False):
        metrics = gpu.collect_gpu_metrics()
        assert metrics == {}


@patch("trackio.gpu.pynvml")
def test_collect_gpu_metrics_single_gpu(mock_pynvml):
    from trackio import gpu

    gpu.PYNVML_AVAILABLE = True
    gpu.pynvml = mock_pynvml

    with patch.object(gpu, "_init_nvml", return_value=True):
        mock_pynvml.nvmlDeviceGetCount.return_value = 1
        mock_handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = mock_handle

        mock_util = MagicMock()
        mock_util.gpu = 75
        mock_util.memory = 50
        mock_pynvml.nvmlDeviceGetUtilizationRates.return_value = mock_util

        mock_mem = MagicMock()
        mock_mem.used = 4 * 1024**3
        mock_mem.total = 8 * 1024**3
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = mock_mem

        mock_pynvml.nvmlDeviceGetPowerUsage.return_value = 150000
        mock_pynvml.nvmlDeviceGetPowerManagementLimit.return_value = 250000
        mock_pynvml.nvmlDeviceGetTemperature.return_value = 65
        mock_pynvml.NVML_TEMPERATURE_GPU = 0
        mock_pynvml.nvmlDeviceGetClockInfo.return_value = 1500
        mock_pynvml.NVML_CLOCK_SM = 0

        mock_pynvml.nvmlDeviceGetCurrentClocksThrottleReasons.return_value = 0
        mock_pynvml.nvmlClocksThrottleReasonSwThermalSlowdown = 1
        mock_pynvml.nvmlClocksThrottleReasonSwPowerCap = 2
        mock_pynvml.nvmlClocksThrottleReasonHwSlowdown = 4
        mock_pynvml.nvmlClocksThrottleReasonApplicationsClocksSetting = 8

        mock_pynvml.NVML_MEMORY_ERROR_TYPE_CORRECTED = 0
        mock_pynvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED = 1
        mock_pynvml.NVML_VOLATILE_ECC = 0
        mock_pynvml.nvmlDeviceGetTotalEccErrors.return_value = 0

        metrics = gpu.collect_gpu_metrics()

        assert metrics["gpu.0.gpu"] == 75
        assert metrics["gpu.0.memory"] == 50
        assert metrics["gpu.0.memoryAllocatedBytes"] == 4 * 1024**3
        assert metrics["gpu.0.memoryTotalBytes"] == 8 * 1024**3
        assert metrics["gpu.0.memoryUsedGiB"] == 4.0
        assert metrics["gpu.0.memoryTotalGiB"] == 8.0
        assert metrics["gpu.0.memoryAllocated"] == 50.0
        assert metrics["gpu.0.powerWatts"] == 150.0
        assert metrics["gpu.0.enforcedPowerLimitWatts"] == 250.0
        assert metrics["gpu.0.powerPercent"] == 60.0
        assert metrics["gpu.0.temp"] == 65
        assert metrics["gpu.0.smClock"] == 1500
        assert metrics["gpu.mean_utilization"] == 75
        assert metrics["gpu.total_power_watts"] == 150.0
        assert metrics["gpu.max_temp"] == 65


@patch("trackio.gpu.get_gpu_count")
@patch("trackio.gpu.collect_gpu_metrics")
def test_gpu_monitor_lifecycle(mock_collect, mock_count):
    from trackio.gpu import GpuMonitor

    mock_count.return_value = 1
    mock_collect.return_value = {"gpu.0.gpu": 50}

    mock_run = MagicMock()

    monitor = GpuMonitor(mock_run, interval=0.1)
    monitor.start()

    time.sleep(0.35)

    monitor.stop()

    assert mock_run.log.call_count >= 2


@patch("trackio.gpu.get_gpu_count")
def test_gpu_monitor_no_gpus_warns(mock_count):
    from trackio.gpu import GpuMonitor

    mock_count.return_value = 0

    mock_run = MagicMock()

    with pytest.warns(UserWarning, match="no NVIDIA GPUs detected"):
        monitor = GpuMonitor(mock_run, interval=0.1)
        monitor.start()

    assert monitor._thread is None


@patch("trackio.gpu.collect_gpu_metrics")
def test_log_gpu_function(mock_collect):
    from trackio import context_vars, gpu

    mock_collect.return_value = {"gpu.0.gpu": 80}

    mock_run = MagicMock()
    context_vars.current_run.set(mock_run)

    try:
        result = gpu.log_gpu()

        assert result == {"gpu.0.gpu": 80}
        mock_run.log.assert_called_once_with({"gpu.0.gpu": 80})
    finally:
        context_vars.current_run.set(None)


def test_log_gpu_no_run():
    from trackio import context_vars, gpu

    context_vars.current_run.set(None)

    with pytest.raises(RuntimeError, match="Call trackio.init\\(\\)"):
        gpu.log_gpu()


@patch("trackio.gpu.collect_gpu_metrics")
def test_log_gpu_empty_metrics(mock_collect):
    from trackio import context_vars, gpu

    mock_collect.return_value = {}

    mock_run = MagicMock()
    context_vars.current_run.set(mock_run)

    try:
        result = gpu.log_gpu()

        assert result == {}
        mock_run.log.assert_not_called()
    finally:
        context_vars.current_run.set(None)
