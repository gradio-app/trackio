import time
from unittest.mock import MagicMock, patch

import pytest

from trackio import context_vars, gpu
from trackio.gpu import GpuMonitor


def test_gpu_available_no_pynvml():
    with patch.object(gpu, "_ensure_pynvml", side_effect=ImportError("no pynvml")):
        assert gpu.gpu_available() is False


@patch("trackio.gpu.pynvml")
def test_gpu_available_with_gpu(mock_pynvml):
    gpu.PYNVML_AVAILABLE = True
    gpu.pynvml = mock_pynvml

    with patch.object(gpu, "_init_nvml", return_value=True):
        mock_pynvml.nvmlDeviceGetCount.return_value = 2
        assert gpu.gpu_available() is True


@patch("trackio.gpu.pynvml")
def test_gpu_available_no_gpu(mock_pynvml):
    gpu.PYNVML_AVAILABLE = True
    gpu.pynvml = mock_pynvml

    with patch.object(gpu, "_init_nvml", return_value=True):
        mock_pynvml.nvmlDeviceGetCount.return_value = 0
        assert gpu.gpu_available() is False


def test_log_gpu_without_pynvml():
    with patch.dict("sys.modules", {"pynvml": None}):
        gpu.PYNVML_AVAILABLE = False
        gpu.pynvml = None

        with pytest.raises(ImportError, match="nvidia-ml-py is required"):
            gpu._ensure_pynvml()


def test_get_gpu_count_no_nvml():
    with patch.object(gpu, "_init_nvml", return_value=False):
        count, indices = gpu.get_gpu_count()
        assert count == 0
        assert indices == []


def test_collect_gpu_metrics_no_nvml():
    with patch.object(gpu, "_init_nvml", return_value=False):
        metrics = gpu.collect_gpu_metrics()
        assert metrics == {}


@patch("trackio.gpu.pynvml")
def test_collect_gpu_metrics_single_gpu(mock_pynvml):
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
        mock_pynvml.NVML_CLOCK_MEM = 1

        mock_pynvml.nvmlDeviceGetFanSpeed.return_value = 45
        mock_pynvml.nvmlDeviceGetPerformanceState.return_value = 0
        mock_pynvml.nvmlDeviceGetTotalEnergyConsumption.return_value = 5000000
        mock_pynvml.nvmlDeviceGetPcieThroughput.return_value = 1024
        mock_pynvml.NVML_PCIE_UTIL_TX_BYTES = 0
        mock_pynvml.NVML_PCIE_UTIL_RX_BYTES = 1

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

        assert metrics["gpu/0/utilization"] == 75
        assert metrics["gpu/0/memory_utilization"] == 50
        assert metrics["gpu/0/allocated_memory"] == 4.0
        assert metrics["gpu/0/total_memory"] == 8.0
        assert metrics["gpu/0/memory_usage"] == 0.5
        assert metrics["gpu/0/power"] == 150.0
        assert metrics["gpu/0/power_limit"] == 250.0
        assert metrics["gpu/0/power_percent"] == 60.0
        assert metrics["gpu/0/temp"] == 65
        assert metrics["gpu/0/sm_clock"] == 1500
        assert metrics["gpu/0/memory_clock"] == 1500
        assert metrics["gpu/0/fan_speed"] == 45
        assert metrics["gpu/0/performance_state"] == 0
        assert metrics["gpu/0/energy_consumed"] == 0.0
        assert metrics["gpu/0/pcie_tx"] == 1.0
        assert metrics["gpu/0/pcie_rx"] == 1.0
        assert metrics["gpu/mean_utilization"] == 75
        assert metrics["gpu/total_allocated_memory"] == 4.0
        assert metrics["gpu/total_power"] == 150.0
        assert metrics["gpu/max_temp"] == 65


@patch("trackio.gpu.get_gpu_count")
@patch("trackio.gpu.collect_gpu_metrics")
def test_gpu_monitor_lifecycle(mock_collect, mock_count):
    mock_count.return_value = (1, [0])
    mock_collect.return_value = {"gpu/0/utilization": 50}

    mock_run = MagicMock()

    monitor = GpuMonitor(mock_run, interval=0.1)
    monitor.start()

    time.sleep(0.35)

    monitor.stop()

    assert mock_run.log_system.call_count >= 2


@patch("trackio.gpu.get_gpu_count")
def test_gpu_monitor_no_gpus_warns(mock_count):
    mock_count.return_value = (0, [])

    mock_run = MagicMock()

    with pytest.warns(UserWarning, match="no NVIDIA GPUs detected"):
        monitor = GpuMonitor(mock_run, interval=0.1)
        monitor.start()

    assert monitor._thread is None


@patch("trackio.gpu.collect_gpu_metrics")
def test_log_gpu_function(mock_collect):
    mock_collect.return_value = {"gpu/0/utilization": 80}

    mock_run = MagicMock()
    context_vars.current_run.set(mock_run)

    try:
        result = gpu.log_gpu()

        assert result == {"gpu/0/utilization": 80}
        mock_run.log_system.assert_called_once_with({"gpu/0/utilization": 80})
    finally:
        context_vars.current_run.set(None)


def test_log_gpu_no_run():
    context_vars.current_run.set(None)

    with pytest.raises(RuntimeError, match="Call trackio.init\\(\\)"):
        gpu.log_gpu()


@patch("trackio.gpu.collect_gpu_metrics")
def test_log_gpu_empty_metrics(mock_collect):
    mock_collect.return_value = {}

    mock_run = MagicMock()
    context_vars.current_run.set(mock_run)

    try:
        result = gpu.log_gpu()

        assert result == {}
        mock_run.log_system.assert_not_called()
    finally:
        context_vars.current_run.set(None)


def test_reset_energy_baseline():
    gpu._energy_baseline = {0: 1000.0, 1: 2000.0}
    gpu.reset_energy_baseline()
    assert gpu._energy_baseline == {}


@patch("trackio.gpu.pynvml")
def test_get_gpu_count_respects_cuda_visible_devices(mock_pynvml):
    gpu.PYNVML_AVAILABLE = True
    gpu.pynvml = mock_pynvml

    with patch.object(gpu, "_init_nvml", return_value=True):
        mock_pynvml.nvmlDeviceGetCount.return_value = 4

        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": "2,3"}):
            count, indices = gpu.get_gpu_count()
            assert count == 2
            assert indices == [2, 3]


@patch("trackio.gpu.pynvml")
def test_get_gpu_count_no_cuda_visible_devices(mock_pynvml):
    gpu.PYNVML_AVAILABLE = True
    gpu.pynvml = mock_pynvml

    with patch.object(gpu, "_init_nvml", return_value=True):
        mock_pynvml.nvmlDeviceGetCount.return_value = 4

        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
            count, indices = gpu.get_gpu_count()
            assert count == 4
            assert indices == [0, 1, 2, 3]


@patch("trackio.gpu.collect_gpu_metrics")
def test_log_gpu_with_device(mock_collect):
    mock_collect.return_value = {"gpu/0/utilization": 80}

    mock_run = MagicMock()
    context_vars.current_run.set(mock_run)

    try:
        result = gpu.log_gpu(device=0)

        assert result == {"gpu/0/utilization": 80}
        mock_collect.assert_called_once_with(device=0)
        mock_run.log_system.assert_called_once_with({"gpu/0/utilization": 80})
    finally:
        context_vars.current_run.set(None)


@patch("trackio.gpu.pynvml")
def test_energy_consumed_calculation(mock_pynvml):
    gpu.PYNVML_AVAILABLE = True
    gpu.pynvml = mock_pynvml
    gpu._energy_baseline = {}

    with patch.object(gpu, "_init_nvml", return_value=True):
        mock_pynvml.nvmlDeviceGetCount.return_value = 1
        mock_handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = mock_handle
        mock_pynvml.nvmlDeviceGetUtilizationRates.side_effect = Exception()
        mock_pynvml.nvmlDeviceGetMemoryInfo.side_effect = Exception()
        mock_pynvml.nvmlDeviceGetPowerUsage.side_effect = Exception()
        mock_pynvml.nvmlDeviceGetPowerManagementLimit.side_effect = Exception()
        mock_pynvml.nvmlDeviceGetTemperature.side_effect = Exception()
        mock_pynvml.nvmlDeviceGetClockInfo.side_effect = Exception()
        mock_pynvml.nvmlDeviceGetFanSpeed.side_effect = Exception()
        mock_pynvml.nvmlDeviceGetPerformanceState.side_effect = Exception()
        mock_pynvml.nvmlDeviceGetPcieThroughput.side_effect = Exception()
        mock_pynvml.nvmlDeviceGetCurrentClocksThrottleReasons.side_effect = Exception()
        mock_pynvml.nvmlDeviceGetTotalEccErrors.side_effect = Exception()

        mock_pynvml.nvmlDeviceGetTotalEnergyConsumption.return_value = 10000000

        metrics1 = gpu.collect_gpu_metrics()
        assert metrics1["gpu/0/energy_consumed"] == 0.0

        mock_pynvml.nvmlDeviceGetTotalEnergyConsumption.return_value = 15000000

        metrics2 = gpu.collect_gpu_metrics()
        assert metrics2["gpu/0/energy_consumed"] == 5000.0
