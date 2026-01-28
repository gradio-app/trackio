from unittest.mock import MagicMock, patch

import pytest

from trackio import apple_gpu, context_vars


def test_log_apple_gpu_without_psutil():
    with patch.dict("sys.modules", {"psutil": None}):
        apple_gpu.PSUTIL_AVAILABLE = False
        apple_gpu.psutil = None

        with pytest.raises(ImportError, match="psutil is required"):
            apple_gpu._ensure_psutil()


def test_log_apple_gpu_no_run():
    context_vars.current_run.set(None)

    with pytest.raises(RuntimeError, match="Call trackio.init\\(\\)"):
        apple_gpu.log_apple_gpu()


def test_is_apple_silicon_non_darwin():
    with patch("platform.system", return_value="Linux"):
        assert not apple_gpu.is_apple_silicon()


def test_is_apple_silicon_darwin_intel():
    with patch("platform.system", return_value="Darwin"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz\n"
            )
            assert not apple_gpu.is_apple_silicon()


def test_is_apple_silicon_darwin_apple():
    with patch("platform.system", return_value="Darwin"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="Apple M1\n")
            assert apple_gpu.is_apple_silicon()


def test_apple_gpu_available_no_psutil():
    with patch.dict("sys.modules", {"psutil": None}):
        apple_gpu.PSUTIL_AVAILABLE = False
        apple_gpu.psutil = None
        assert not apple_gpu.apple_gpu_available()


def test_collect_apple_metrics_no_psutil():
    with patch.dict("sys.modules", {"psutil": None}):
        apple_gpu.PSUTIL_AVAILABLE = False
        apple_gpu.psutil = None
        metrics = apple_gpu.collect_apple_metrics()
        assert metrics == {}


def test_get_gpu_info_ioreg_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="+-o IOAccelerator  <class IOAccelerator, id 0x100000123>\n",
        )
        info = apple_gpu.get_gpu_info()
        assert info["detected"] is True
        assert info["type"] == "Apple GPU"


def test_get_gpu_info_system_profiler_success():
    with patch("subprocess.run") as mock_run:

        def run_side_effect(*args, **kwargs):
            if "ioreg" in args[0]:
                return MagicMock(returncode=1, stdout="")
            elif "system_profiler" in args[0]:
                return MagicMock(
                    returncode=0, stdout="Chipset Model: Apple M1 Pro\nVRAM: 16 GB\n"
                )

        mock_run.side_effect = run_side_effect
        info = apple_gpu.get_gpu_info()
        assert info["detected"] is True
        assert info["type"] == "Apple M1 Pro"


def test_get_gpu_info_not_detected():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        info = apple_gpu.get_gpu_info()
        assert info["detected"] is False
