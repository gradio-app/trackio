from unittest.mock import MagicMock, patch

import trackio
from trackio import context_vars


def test_log_gpu_calls_nvidia_when_available():
    mock_run = MagicMock()
    context_vars.current_run.set(mock_run)

    with patch("trackio.gpu_available", return_value=True):
        with patch(
            "trackio._log_nvidia_gpu", return_value={"gpu/0/utilization": 50}
        ) as mock_nvidia:
            result = trackio.log_gpu()
            mock_nvidia.assert_called_once_with(run=mock_run, device=None)
            assert result == {"gpu/0/utilization": 50}


def test_log_gpu_calls_apple_when_no_nvidia():
    mock_run = MagicMock()
    context_vars.current_run.set(mock_run)

    with patch("trackio.gpu_available", return_value=False):
        with patch("trackio.apple_gpu_available", return_value=True):
            with patch(
                "trackio._log_apple_gpu", return_value={"cpu/utilization": 30}
            ) as mock_apple:
                result = trackio.log_gpu()
                mock_apple.assert_called_once_with(run=mock_run)
                assert result == {"cpu/utilization": 30}


def test_log_gpu_warns_when_no_gpu():
    mock_run = MagicMock()
    context_vars.current_run.set(mock_run)

    with patch("trackio.gpu_available", return_value=False):
        with patch("trackio.apple_gpu_available", return_value=False):
            with patch("warnings.warn") as mock_warn:
                result = trackio.log_gpu()
                mock_warn.assert_called_once()
                assert "No GPU detected" in mock_warn.call_args[0][0]
                assert result == {}


def test_log_gpu_passes_device_parameter_to_nvidia():
    mock_run = MagicMock()
    context_vars.current_run.set(mock_run)

    with patch("trackio.gpu_available", return_value=True):
        with patch("trackio._log_nvidia_gpu", return_value={}) as mock_nvidia:
            trackio.log_gpu(device=1)
            mock_nvidia.assert_called_once_with(run=mock_run, device=1)


def test_log_gpu_no_run_raises_error():
    context_vars.current_run.set(None)

    with patch("trackio.gpu_available", return_value=True):
        try:
            trackio.log_gpu()
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "Call trackio.init() before trackio.log_gpu()" in str(e)
