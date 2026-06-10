from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from trackio import context_vars, cpu
from trackio.run import Run


def _make_mock_psutil():
    mock = MagicMock()
    mock.cpu_percent.return_value = [45.0, 60.0]
    mock.cpu_freq.return_value = SimpleNamespace(current=3200.0, max=4800.0)
    mock.cpu_count.side_effect = lambda logical=True: 4 if logical else 2
    mock.virtual_memory.return_value = SimpleNamespace(
        used=8 * (1024**3),
        total=16 * (1024**3),
        available=8 * (1024**3),
        percent=50.0,
    )
    mock.swap_memory.return_value = SimpleNamespace(
        used=0.5 * (1024**3),
        total=4 * (1024**3),
        percent=12.5,
    )
    mock.disk_io_counters.return_value = SimpleNamespace(
        read_bytes=1_000_000_000,
        write_bytes=500_000_000,
        read_count=10000,
        write_count=5000,
    )
    mock.net_io_counters.return_value = SimpleNamespace(
        bytes_sent=200_000_000,
        bytes_recv=800_000_000,
    )
    mock.sensors_temperatures.return_value = {
        "coretemp": [SimpleNamespace(label="Core 0", current=55.0)]
    }
    mock.sensors_battery.return_value = SimpleNamespace(
        percent=85.0, power_plugged=True
    )
    return mock


@pytest.fixture
def mock_psutil_env():
    old_psutil = cpu.psutil
    old_available = cpu.PSUTIL_AVAILABLE
    cpu.psutil = _make_mock_psutil()
    cpu.PSUTIL_AVAILABLE = True
    yield cpu.psutil
    cpu.psutil = old_psutil
    cpu.PSUTIL_AVAILABLE = old_available


def test_cpu_available_without_psutil():
    with patch.dict("sys.modules", {"psutil": None}):
        cpu.PSUTIL_AVAILABLE = False
        cpu.psutil = None

        with pytest.raises(ImportError, match="psutil is required"):
            cpu._ensure_psutil()


def test_collect_cpu_metrics_covers_supported_groups(mock_psutil_env):
    metrics = cpu.collect_cpu_metrics()

    assert metrics["cpu/utilization"] == pytest.approx(52.5)
    assert metrics["cpu/0/utilization"] == 45.0
    assert metrics["cpu/frequency"] == 3200.0
    assert metrics["cpu/count_logical"] == 4
    assert metrics["memory/used"] == pytest.approx(8.0)
    assert metrics["memory/percent"] == 50.0
    assert metrics["swap/percent"] == 12.5
    assert "disk/read_bytes" in metrics
    assert "network/recv_bytes" in metrics
    assert metrics["temp/Core 0"] == 55.0
    assert metrics["battery/power_plugged"] == 1


def test_collect_cpu_metrics_rates_and_static_toggle(mock_psutil_env):
    disk_prev = SimpleNamespace(
        read_bytes=900_000_000,
        write_bytes=400_000_000,
        read_count=9000,
        write_count=4500,
    )
    net_prev = SimpleNamespace(bytes_sent=100_000_000, bytes_recv=600_000_000)

    metrics = cpu.collect_cpu_metrics(
        prev_disk_counters=disk_prev,
        prev_net_counters=net_prev,
        elapsed=10.0,
        include_static=False,
    )

    assert metrics["disk/read_mb_per_sec"] == pytest.approx(
        100_000_000 / 10.0 / (1024**2)
    )
    assert metrics["disk/read_iops"] == pytest.approx(100.0)
    assert metrics["network/sent_mb_per_sec"] == pytest.approx(
        100_000_000 / 10.0 / (1024**2)
    )
    assert "cpu/frequency" not in metrics
    assert "cpu/count_logical" not in metrics


def test_log_cpu_requires_run():
    context_vars.current_run.set(None)

    with pytest.raises(RuntimeError, match=r"Call trackio.init\(\)"):
        cpu.log_cpu()


def test_log_cpu_warns_without_psutil():
    old_psutil = cpu.psutil
    old_available = cpu.PSUTIL_AVAILABLE
    cpu.PSUTIL_AVAILABLE = False
    cpu.psutil = None

    with patch.dict("sys.modules", {"psutil": None}):
        with pytest.warns(UserWarning, match=r"trackio.log_cpu\(\) requires psutil"):
            assert cpu.log_cpu(run=MagicMock()) == {}

    cpu.psutil = old_psutil
    cpu.PSUTIL_AVAILABLE = old_available


def test_log_cpu_with_run(mock_psutil_env):
    mock_run = MagicMock()
    result = cpu.log_cpu(run=mock_run)

    mock_run.log_system.assert_called_once()
    assert result["cpu/utilization"] == pytest.approx(52.5)


def test_cpu_monitor_starts_and_stops(mock_psutil_env):
    mock_run = MagicMock()
    monitor = cpu.CpuMonitor(mock_run, interval=0.01)
    monitor.start()
    monitor.stop()

    assert monitor._thread is not None
    assert not monitor._thread.is_alive()


def test_auto_log_cpu_warns_without_psutil():
    old_psutil = cpu.psutil
    old_available = cpu.PSUTIL_AVAILABLE
    cpu.PSUTIL_AVAILABLE = False
    cpu.psutil = None

    with patch.dict("sys.modules", {"psutil": None}):
        with pytest.warns(UserWarning, match="psutil is not installed"):
            run = Run(
                url=None,
                project="test-project",
                client=MagicMock(),
                auto_log_cpu=True,
            )
        run.finish()

    cpu.psutil = old_psutil
    cpu.PSUTIL_AVAILABLE = old_available
