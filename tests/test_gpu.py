from unittest.mock import patch

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
