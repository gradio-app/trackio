"""
Test script to simulate a single GPU locally using mocks.
Run this, then open `trackio show --project single-gpu-test` to verify
the System Metrics page matches prior single-GPU behavior.
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import trackio
from trackio import gpu

mock_pynvml = MagicMock()
mock_pynvml.nvmlDeviceGetCount.return_value = 1
mock_pynvml.nvmlDeviceGetHandleByIndex.side_effect = lambda i: f"handle_{i}"
mock_pynvml.nvmlDeviceGetUtilizationRates.return_value = SimpleNamespace(
    gpu=72, memory=45
)
mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = SimpleNamespace(
    used=6 * (1024**3), total=16 * (1024**3)
)
mock_pynvml.nvmlDeviceGetPowerUsage.return_value = 180000
mock_pynvml.nvmlDeviceGetPowerManagementLimit.return_value = 300000
mock_pynvml.nvmlDeviceGetTemperature.return_value = 68
mock_pynvml.NVML_TEMPERATURE_GPU = 0
mock_pynvml.nvmlDeviceGetClockInfo.return_value = 1800
mock_pynvml.NVML_CLOCK_SM = 0
mock_pynvml.NVML_CLOCK_MEM = 1
mock_pynvml.nvmlDeviceGetFanSpeed.return_value = 55
mock_pynvml.nvmlDeviceGetPerformanceState.return_value = 0
mock_pynvml.nvmlDeviceGetTotalEnergyConsumption.return_value = 8000
mock_pynvml.nvmlDeviceGetPcieThroughput.return_value = 4096
mock_pynvml.NVML_PCIE_UTIL_TX_BYTES = 0
mock_pynvml.NVML_PCIE_UTIL_RX_BYTES = 1
mock_pynvml.nvmlDeviceGetCurrentClocksThrottleReasons.return_value = 0
mock_pynvml.nvmlClocksThrottleReasonSwThermalSlowdown = 0x20
mock_pynvml.nvmlClocksThrottleReasonSwPowerCap = 0x4
mock_pynvml.nvmlClocksThrottleReasonHwSlowdown = 0x8
mock_pynvml.nvmlClocksThrottleReasonApplicationsClocksSetting = 0x2
mock_pynvml.nvmlDeviceGetTotalEccErrors.return_value = 0
mock_pynvml.NVML_MEMORY_ERROR_TYPE_CORRECTED = 0
mock_pynvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED = 1
mock_pynvml.NVML_VOLATILE_ECC = 0

gpu.pynvml = mock_pynvml
gpu._nvml_initialized = True
gpu.PYNVML_AVAILABLE = True

with (
    patch("trackio.run.gpu_available", return_value=True),
    patch("trackio.run.apple_gpu_available", return_value=False),
):
    trackio.init(project="single-gpu-test", auto_log_gpu=True, gpu_log_interval=1)
    for i in range(30):
        trackio.log({"loss": 1 / (i + 1)})
        time.sleep(1)
    trackio.finish()

print("Done. Run `trackio show --project single-gpu-test` to view results.")
