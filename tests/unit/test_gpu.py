from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from trackio import context_vars, gpu


def test_log_gpu_without_pynvml():
    with patch.dict("sys.modules", {"pynvml": None}):
        gpu.PYNVML_AVAILABLE = False
        gpu.pynvml = None

        with pytest.raises(ImportError, match="nvidia-ml-py is required"):
            gpu._ensure_pynvml()


def test_log_gpu_no_run():
    context_vars.current_run.set(None)

    with pytest.raises(RuntimeError, match="Call trackio.init\\(\\)"):
        gpu.log_gpu()


def test_reset_energy_baseline():
    gpu._energy_baseline = {0: 1000.0, 1: 2000.0}
    gpu.reset_energy_baseline()
    assert gpu._energy_baseline == {}


def _make_mock_pynvml(num_gpus=4):
    mock = MagicMock()
    mock.nvmlInit.return_value = None
    mock.nvmlDeviceGetCount.return_value = num_gpus

    def make_handle(idx):
        return f"handle_{idx}"

    mock.nvmlDeviceGetHandleByIndex.side_effect = make_handle
    mock.nvmlDeviceGetUtilizationRates.side_effect = lambda h: SimpleNamespace(
        gpu=50 + int(h.split("_")[1]) * 10, memory=30
    )
    mock.nvmlDeviceGetMemoryInfo.side_effect = lambda h: SimpleNamespace(
        used=4 * (1024**3), total=16 * (1024**3)
    )
    mock.nvmlDeviceGetPowerUsage.return_value = 150000
    mock.nvmlDeviceGetPowerManagementLimit.return_value = 300000
    mock.nvmlDeviceGetTemperature.return_value = 65
    mock.NVML_TEMPERATURE_GPU = 0
    mock.nvmlDeviceGetClockInfo.return_value = 1500
    mock.NVML_CLOCK_SM = 0
    mock.NVML_CLOCK_MEM = 1
    mock.nvmlDeviceGetFanSpeed.return_value = 40
    mock.nvmlDeviceGetPerformanceState.return_value = 0
    mock.nvmlDeviceGetTotalEnergyConsumption.return_value = 5000
    mock.nvmlDeviceGetPcieThroughput.return_value = 2048
    mock.NVML_PCIE_UTIL_TX_BYTES = 0
    mock.NVML_PCIE_UTIL_RX_BYTES = 1
    mock.nvmlDeviceGetCurrentClocksThrottleReasons.return_value = 0
    mock.nvmlClocksThrottleReasonSwThermalSlowdown = 0x20
    mock.nvmlClocksThrottleReasonSwPowerCap = 0x4
    mock.nvmlClocksThrottleReasonHwSlowdown = 0x8
    mock.nvmlClocksThrottleReasonApplicationsClocksSetting = 0x2
    mock.nvmlDeviceGetTotalEccErrors.return_value = 0
    mock.NVML_MEMORY_ERROR_TYPE_CORRECTED = 0
    mock.NVML_MEMORY_ERROR_TYPE_UNCORRECTED = 1
    mock.NVML_VOLATILE_ECC = 0
    return mock


def test_get_all_gpu_count_ignores_cuda_visible_devices():
    mock_pynvml = _make_mock_pynvml(4)
    old_pynvml = gpu.pynvml
    old_initialized = gpu._nvml_initialized
    gpu.pynvml = mock_pynvml
    gpu._nvml_initialized = True

    try:
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": "2"}):
            all_count, all_indices = gpu.get_all_gpu_count()
            assert all_count == 4
            assert all_indices == [0, 1, 2, 3]

            vis_count, vis_indices = gpu.get_gpu_count()
            assert vis_count == 1
            assert vis_indices == [2]
    finally:
        gpu.pynvml = old_pynvml
        gpu._nvml_initialized = old_initialized


def test_collect_gpu_metrics_all_gpus():
    mock_pynvml = _make_mock_pynvml(4)
    old_pynvml = gpu.pynvml
    old_initialized = gpu._nvml_initialized
    gpu.pynvml = mock_pynvml
    gpu._nvml_initialized = True
    gpu._energy_baseline = {}

    try:
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": "2"}):
            metrics = gpu.collect_gpu_metrics(all_gpus=True)
            for i in range(4):
                assert f"gpu/{i}/utilization" in metrics
            assert "gpu/mean_utilization" in metrics
    finally:
        gpu.pynvml = old_pynvml
        gpu._nvml_initialized = old_initialized


def test_collect_gpu_metrics_default_respects_cuda_visible():
    mock_pynvml = _make_mock_pynvml(4)
    old_pynvml = gpu.pynvml
    old_initialized = gpu._nvml_initialized
    gpu.pynvml = mock_pynvml
    gpu._nvml_initialized = True
    gpu._energy_baseline = {}

    try:
        with patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": "2"}):
            metrics = gpu.collect_gpu_metrics()
            assert "gpu/0/utilization" in metrics
            assert "gpu/1/utilization" not in metrics
            assert "gpu/2/utilization" not in metrics
            assert "gpu/3/utilization" not in metrics
    finally:
        gpu.pynvml = old_pynvml
        gpu._nvml_initialized = old_initialized
