from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from trackio import context_vars, cpu


def _make_mock_psutil():
    mock = MagicMock()

    mock.cpu_percent.side_effect = lambda interval=None, percpu=False: (
        [45.0, 60.0, 30.0, 55.0] if percpu else 47.5
    )
    mock.cpu_freq.return_value = SimpleNamespace(current=3200.0, max=4800.0)
    mock.cpu_count.side_effect = lambda logical=True: 8 if logical else 4

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

    disk_counters = SimpleNamespace(
        read_bytes=1_000_000_000,
        write_bytes=500_000_000,
        read_count=10000,
        write_count=5000,
    )
    mock.disk_io_counters.return_value = disk_counters

    net_counters = SimpleNamespace(
        bytes_sent=200_000_000,
        bytes_recv=800_000_000,
    )
    mock.net_io_counters.return_value = net_counters

    mock.sensors_temperatures.return_value = {
        "coretemp": [
            SimpleNamespace(label="Core 0", current=55.0),
            SimpleNamespace(label="Core 1", current=58.0),
        ]
    }

    mock.sensors_battery.return_value = None

    return mock


@pytest.fixture
def mock_psutil_env():
    old_psutil = cpu.psutil
    old_available = cpu.PSUTIL_AVAILABLE
    mock = _make_mock_psutil()
    cpu.psutil = mock
    cpu.PSUTIL_AVAILABLE = True
    yield mock
    cpu.psutil = old_psutil
    cpu.PSUTIL_AVAILABLE = old_available


def test_cpu_available_without_psutil():
    with patch.dict("sys.modules", {"psutil": None}):
        cpu.PSUTIL_AVAILABLE = False
        cpu.psutil = None

        with pytest.raises(ImportError, match="psutil is required"):
            cpu._ensure_psutil()


def test_log_cpu_no_run():
    context_vars.current_run.set(None)

    with pytest.raises(RuntimeError, match="Call trackio.init\\(\\)"):
        cpu.log_cpu()


def test_collect_cpu_metrics_basic(mock_psutil_env):
    metrics = cpu.collect_cpu_metrics()

    assert "cpu/utilization" in metrics
    assert metrics["cpu/utilization"] == 47.5

    assert "memory/used" in metrics
    assert "memory/total" in metrics
    assert "memory/percent" in metrics
    assert metrics["memory/percent"] == 50.0

    assert "swap/used" in metrics
    assert "swap/percent" in metrics


def test_collect_cpu_metrics_per_core(mock_psutil_env):
    metrics = cpu.collect_cpu_metrics()

    assert "cpu/0/utilization" in metrics
    assert "cpu/1/utilization" in metrics
    assert metrics["cpu/0/utilization"] == 45.0
    assert metrics["cpu/3/utilization"] == 55.0


def test_collect_cpu_metrics_frequency(mock_psutil_env):
    metrics = cpu.collect_cpu_metrics()

    assert "cpu/frequency" in metrics
    assert metrics["cpu/frequency"] == 3200.0
    assert "cpu/frequency_max" in metrics
    assert metrics["cpu/frequency_max"] == 4800.0


def test_collect_cpu_metrics_cpu_count(mock_psutil_env):
    metrics = cpu.collect_cpu_metrics()

    assert metrics["cpu/count_logical"] == 8
    assert metrics["cpu/count_physical"] == 4


def test_collect_cpu_metrics_disk_cumulative(mock_psutil_env):
    metrics = cpu.collect_cpu_metrics()

    assert "disk/read_bytes" in metrics
    assert "disk/write_bytes" in metrics


def test_collect_cpu_metrics_disk_rates(mock_psutil_env):
    prev = SimpleNamespace(
        read_bytes=900_000_000,
        write_bytes=400_000_000,
        read_count=9000,
        write_count=4500,
    )
    elapsed = 10.0
    metrics = cpu.collect_cpu_metrics(prev_disk_counters=prev, elapsed=elapsed)

    assert "disk/read_mb_per_sec" in metrics
    assert "disk/write_mb_per_sec" in metrics
    assert "disk/read_iops" in metrics
    assert "disk/write_iops" in metrics

    expected_read_mb = (1_000_000_000 - 900_000_000) / 10.0 / (1024**2)
    assert metrics["disk/read_mb_per_sec"] == pytest.approx(expected_read_mb)

    expected_read_iops = (10000 - 9000) / 10.0
    assert metrics["disk/read_iops"] == pytest.approx(expected_read_iops)


def test_collect_cpu_metrics_network_cumulative(mock_psutil_env):
    metrics = cpu.collect_cpu_metrics()

    assert "network/sent_bytes" in metrics
    assert "network/recv_bytes" in metrics


def test_collect_cpu_metrics_network_rates(mock_psutil_env):
    prev = SimpleNamespace(
        bytes_sent=100_000_000,
        bytes_recv=600_000_000,
    )
    elapsed = 5.0
    metrics = cpu.collect_cpu_metrics(prev_net_counters=prev, elapsed=elapsed)

    assert "network/sent_mb_per_sec" in metrics
    assert "network/recv_mb_per_sec" in metrics

    expected_sent = (200_000_000 - 100_000_000) / 5.0 / (1024**2)
    assert metrics["network/sent_mb_per_sec"] == pytest.approx(expected_sent)


def test_collect_cpu_metrics_sensors(mock_psutil_env):
    metrics = cpu.collect_cpu_metrics()

    assert "temp/Core 0" in metrics
    assert metrics["temp/Core 0"] == 55.0
    assert "temp/Core 1" in metrics


def test_collect_cpu_metrics_no_rates_when_no_elapsed(mock_psutil_env):
    prev = SimpleNamespace(
        read_bytes=900_000_000,
        write_bytes=400_000_000,
        read_count=9000,
        write_count=4500,
    )
    metrics = cpu.collect_cpu_metrics(prev_disk_counters=prev, elapsed=None)

    assert "disk/read_mb_per_sec" not in metrics
    assert "disk/read_bytes" in metrics


def test_cpu_monitor_starts_and_stops(mock_psutil_env):
    mock_run = MagicMock()
    monitor = cpu.CpuMonitor(mock_run, interval=0.05)
    monitor.start()

    import time

    time.sleep(0.2)

    monitor.stop()

    assert mock_run.log_system.called
    logged_metrics = mock_run.log_system.call_args[0][0]
    assert "cpu/utilization" in logged_metrics
    assert "memory/percent" in logged_metrics


def test_cpu_monitor_without_psutil():
    old_psutil = cpu.psutil
    old_available = cpu.PSUTIL_AVAILABLE
    cpu.PSUTIL_AVAILABLE = False
    cpu.psutil = None

    mock_run = MagicMock()
    monitor = cpu.CpuMonitor(mock_run, interval=10.0)

    with patch.dict("sys.modules", {"psutil": None}):
        with pytest.warns(UserWarning, match="psutil is not installed"):
            monitor.start()

    cpu.psutil = old_psutil
    cpu.PSUTIL_AVAILABLE = old_available


def test_log_cpu_with_run(mock_psutil_env):
    mock_run = MagicMock()
    result = cpu.log_cpu(run=mock_run)

    assert mock_run.log_system.called
    assert isinstance(result, dict)
    assert "cpu/utilization" in result


def test_collect_cpu_metrics_battery(mock_psutil_env):
    mock_psutil_env.sensors_battery.return_value = SimpleNamespace(
        percent=85.0, power_plugged=True
    )
    metrics = cpu.collect_cpu_metrics()

    assert "battery/percent" in metrics
    assert metrics["battery/percent"] == 85.0
    assert metrics["battery/power_plugged"] == 1


def test_collect_cpu_metrics_memory_values(mock_psutil_env):
    metrics = cpu.collect_cpu_metrics()

    assert metrics["memory/used"] == pytest.approx(8.0)
    assert metrics["memory/total"] == pytest.approx(16.0)
    assert metrics["memory/available"] == pytest.approx(8.0)
