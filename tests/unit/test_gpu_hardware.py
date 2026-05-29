"""GPU hardware tests.

These tests exercise the real `trackio.gpu` integration against actual NVIDIA
hardware (via pynvml). They are skipped automatically when no CUDA device is
present, so they're safe to include in CPU-only runs — but they're intended
to run in the dedicated `test-gpu.yml` workflow on `hf-jobs-t4-small`.
"""

from __future__ import annotations

import pytest

import trackio
from trackio import gpu as trackio_gpu


def _cuda_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        return False


def _pynvml_available() -> bool:
    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            return pynvml.nvmlDeviceGetCount() > 0
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return False


requires_cuda = pytest.mark.skipif(
    not _cuda_available(), reason="requires a CUDA-capable GPU"
)
requires_nvml = pytest.mark.skipif(
    not _pynvml_available(), reason="requires NVML and at least one GPU device"
)


@pytest.fixture
def isolated_run(tmp_path, monkeypatch):
    """Spin up a trackio run that writes to a temp dir, finish on teardown."""
    monkeypatch.setenv("TRACKIO_DIR", str(tmp_path))
    run = trackio.init(project="gpu-tests")
    try:
        yield run
    finally:
        trackio.finish()


@requires_nvml
def test_pynvml_detects_at_least_one_gpu():
    import pynvml

    pynvml.nvmlInit()
    try:
        n = pynvml.nvmlDeviceGetCount()
        assert n >= 1, f"expected ≥1 GPU, got {n}"
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode()
        assert name, "GPU name should be non-empty"
        print(f"detected GPU 0: {name}")
    finally:
        pynvml.nvmlShutdown()


@requires_nvml
def test_collect_gpu_metrics_returns_real_values():
    metrics = trackio_gpu.collect_gpu_metrics()
    assert isinstance(metrics, dict), "expected a dict of metrics"
    assert len(metrics) > 0, "expected at least one metric collected"

    # We don't know the exact metric names without inspecting trackio.gpu
    # internals, but anything reporting memory in MB / utilization in % should
    # be present. Spot-check by looking for *any* GPU-related key.
    gpu_keys = [k for k in metrics if "gpu" in k.lower() or "memory" in k.lower()]
    assert gpu_keys, f"expected gpu-related metric keys, got {list(metrics)[:5]}"


@requires_nvml
def test_log_gpu_writes_to_run(isolated_run):
    metrics = trackio.log_gpu()
    assert isinstance(metrics, dict)
    assert len(metrics) > 0


@requires_cuda
@requires_nvml
def test_log_gpu_during_torch_workload(isolated_run):
    """Run a small tensor op to ensure utilization registers, then log."""
    import torch

    device = torch.device("cuda:0")
    # Allocate a non-trivial chunk so memory utilization moves above noise.
    a = torch.randn(2048, 2048, device=device)
    b = torch.randn(2048, 2048, device=device)
    for _ in range(20):
        _ = a @ b
    torch.cuda.synchronize()

    metrics = trackio.log_gpu()
    assert metrics, "log_gpu should return non-empty metrics during a workload"

    free, total = torch.cuda.mem_get_info(device)
    used_bytes = total - free
    assert used_bytes > 0, "expected non-zero GPU memory in use during workload"


@requires_cuda
def test_trackio_init_compatible_with_cuda(tmp_path, monkeypatch):
    """Smoke test: importing trackio + initializing a run should work on GPU hosts."""
    monkeypatch.setenv("TRACKIO_DIR", str(tmp_path))
    trackio.init(project="gpu-smoke")
    trackio.log({"step": 1, "loss": 0.5})
    trackio.finish()

    import torch

    # Sanity: trackio's import path didn't pull in anything that breaks CUDA.
    assert torch.cuda.is_available()
