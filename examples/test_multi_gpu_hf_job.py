# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "trackio",
#     "nvidia-ml-py",
#     "torch",
# ]
# ///
"""
Test multi-GPU system metrics on real multi-GPU hardware via HF Jobs,
with actual GPU load to produce interesting charts.

Run:
  hf jobs uv run --flavor a10g-largex2 --timeout 10m -s HF_TOKEN examples/test_multi_gpu_hf_job.py
"""

import threading
import time

import pynvml
import torch


def get_all_gpu_count():
    pynvml.nvmlInit()
    total = pynvml.nvmlDeviceGetCount()
    return total, list(range(total))


print("=" * 60)
print("Multi-GPU System Metrics Test (GPU stress)")
print("=" * 60)

all_count, all_indices = get_all_gpu_count()
print(f"Physical GPUs: count={all_count}, indices={all_indices}")
for i in range(all_count):
    print(f"  GPU {i}: {torch.cuda.get_device_name(i)}")

import trackio
from trackio import gpu

gpu.get_all_gpu_count = get_all_gpu_count

original_collect = gpu.collect_gpu_metrics


def patched_collect(device=None, all_gpus=False):
    if not gpu._init_nvml():
        return {}
    if all_gpus and device is None:
        gpu_count, visible_gpus = get_all_gpu_count()
    else:
        gpu_count, visible_gpus = gpu.get_gpu_count()
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
            handle = gpu.pynvml.nvmlDeviceGetHandleByIndex(physical_idx)
            try:
                util = gpu.pynvml.nvmlDeviceGetUtilizationRates(handle)
                metrics[f"{prefix}/utilization"] = util.gpu
                metrics[f"{prefix}/memory_utilization"] = util.memory
                total_util += util.gpu
                valid_util_count += 1
            except Exception:
                pass
            try:
                mem = gpu.pynvml.nvmlDeviceGetMemoryInfo(handle)
                mem_used_gib = mem.used / (1024**3)
                metrics[f"{prefix}/allocated_memory"] = mem_used_gib
                metrics[f"{prefix}/total_memory"] = mem.total / (1024**3)
                total_mem_used_gib += mem_used_gib
            except Exception:
                pass
            try:
                power_mw = gpu.pynvml.nvmlDeviceGetPowerUsage(handle)
                metrics[f"{prefix}/power"] = power_mw / 1000.0
                total_power += power_mw / 1000.0
            except Exception:
                pass
            try:
                temp = gpu.pynvml.nvmlDeviceGetTemperature(
                    handle, gpu.pynvml.NVML_TEMPERATURE_GPU
                )
                metrics[f"{prefix}/temp"] = temp
                max_temp = max(max_temp, temp)
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


gpu.collect_gpu_metrics = patched_collect


def patched_start(self):
    count, _ = get_all_gpu_count()
    if count == 0:
        import warnings

        warnings.warn("auto_log_gpu=True but no NVIDIA GPUs detected.")
        return
    gpu.reset_energy_baseline()
    self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
    self._thread.start()


def patched_monitor_loop(self):
    while not self._stop_flag.is_set():
        try:
            metrics = patched_collect(all_gpus=True)
            if metrics:
                self._run.log_system(metrics)
        except Exception:
            pass
        self._stop_flag.wait(timeout=self._interval)


gpu.GpuMonitor.start = patched_start
gpu.GpuMonitor._monitor_loop = patched_monitor_loop


def gpu_stress(device_id, duration, matrix_size=4096):
    torch.cuda.set_device(device_id)
    a = torch.randn(matrix_size, matrix_size, device=f"cuda:{device_id}")
    b = torch.randn(matrix_size, matrix_size, device=f"cuda:{device_id}")
    end = time.time() + duration
    while time.time() < end:
        torch.mm(a, b)
    del a, b
    torch.cuda.empty_cache()


run = trackio.init(
    project="multi-gpu-hw-test",
    name="2xA10G-stress",
    space_id="saba9/multi-gpu-test",
    auto_log_gpu=True,
    gpu_log_interval=2,
)

print("\n--- Phase 1: Idle (15s) ---")
for i in range(15):
    trackio.log({"loss": 1.0, "phase": 0})
    time.sleep(1)

print("--- Phase 2: GPU 0 only (20s) ---")
t0 = threading.Thread(target=gpu_stress, args=(0, 20, 4096))
t0.start()
for i in range(20):
    trackio.log({"loss": 0.8 - i * 0.01, "phase": 1})
    time.sleep(1)
t0.join()

print("--- Phase 3: Both GPUs (20s) ---")
t0 = threading.Thread(target=gpu_stress, args=(0, 20, 4096))
t1 = threading.Thread(target=gpu_stress, args=(1, 20, 6144))
t0.start()
t1.start()
for i in range(20):
    trackio.log({"loss": 0.6 - i * 0.01, "phase": 2})
    time.sleep(1)
t0.join()
t1.join()

print("--- Phase 4: GPU 1 only (20s) ---")
t1 = threading.Thread(target=gpu_stress, args=(1, 20, 4096))
t1.start()
for i in range(20):
    trackio.log({"loss": 0.4 - i * 0.005, "phase": 3})
    time.sleep(1)
t1.join()

print("--- Phase 5: Cooldown (15s) ---")
for i in range(15):
    trackio.log({"loss": 0.3 - i * 0.005, "phase": 4})
    time.sleep(1)

trackio.finish()
print("\nDone! View dashboard at: https://huggingface.co/spaces/saba9/multi-gpu-test")
