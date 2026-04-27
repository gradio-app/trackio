from trackio.watchers import MetricWatcher, WatcherManager


def test_nan_inf_triggers_stop():
    w = MetricWatcher("loss", nan=True)
    alerts = w.check(float("nan"), step=10)
    assert len(alerts) == 1
    assert alerts[0]["data"]["reason"] == "nan_inf"
    assert w.should_stop

    w2 = MetricWatcher("loss", nan=False)
    assert len(w2.check(float("nan"), step=0)) == 0


def test_max_value_with_dedup():
    w = MetricWatcher("loss", max_value=10.0)
    assert len(w.check(5.0, step=0)) == 0
    alerts = w.check(15.0, step=1)
    assert len(alerts) == 1
    assert alerts[0]["data"]["reason"] == "max_exceeded"
    assert w.should_stop
    assert len(w.check(15.0, step=2)) == 0
    w.check(5.0, step=3)
    assert len(w.check(15.0, step=4)) == 1


def test_min_value_with_dedup():
    w = MetricWatcher("acc", min_value=0.5)
    assert len(w.check(0.8, step=0)) == 0
    assert len(w.check(0.3, step=1)) == 1
    assert len(w.check(0.3, step=2)) == 0
    w.check(0.8, step=3)
    assert len(w.check(0.3, step=4)) == 1


def test_spike_detection_with_dedup_and_reset():
    w = MetricWatcher("loss", spike_factor=3.0, window=3)
    for i in range(3):
        w.check(1.0, step=i)
    alerts = w.check(10.0, step=3)
    assert len(alerts) == 1
    assert alerts[0]["data"]["reason"] == "spike"
    assert len(w.check(10.0, step=4)) == 0
    for i in range(3):
        w.check(1.0, step=5 + i)
    assert len(w.check(10.0, step=8)) == 1


def test_patience_min_mode():
    w = MetricWatcher("loss", patience=3, mode="min")
    w.check(1.0, step=0)
    w.check(0.9, step=1)
    w.check(0.95, step=2)
    w.check(0.95, step=3)
    alerts = w.check(0.95, step=4)
    assert len(alerts) == 1
    assert alerts[0]["data"]["reason"] == "stagnation"
    assert w.should_stop
    assert len(w.check(0.95, step=5)) == 0


def test_patience_max_mode():
    w = MetricWatcher("accuracy", patience=3, mode="max")
    w.check(0.5, step=0)
    w.check(0.6, step=1)
    w.check(0.55, step=2)
    w.check(0.55, step=3)
    assert len(w.check(0.55, step=4)) == 1
    assert w.should_stop

    w2 = MetricWatcher("accuracy", patience=3, mode="max")
    w2.check(0.5, step=0)
    w2.check(0.6, step=1)
    w2.check(0.55, step=2)
    w2.check(0.7, step=3)
    assert len(w2.check(0.65, step=4)) == 0
    assert not w2.should_stop


def test_window_bounds_memory():
    w = MetricWatcher("loss", window=5)
    for i in range(100):
        w.check(float(i), step=i)
    assert len(w._values) == 5


def test_manager_should_stop_and_clear():
    mgr = WatcherManager()
    mgr.add(MetricWatcher("loss", max_value=10.0))
    mgr.add(MetricWatcher("acc", min_value=0.5))
    assert not mgr.should_stop
    mgr.check({"loss": 15.0, "acc": 0.8}, step=0)
    assert mgr.should_stop
    mgr.clear()
    assert not mgr.should_stop
    assert len(mgr._watchers) == 0


def test_non_numeric_ignored():
    w = MetricWatcher("loss", max_value=10.0)
    assert len(w.check("not a number", step=0)) == 0
