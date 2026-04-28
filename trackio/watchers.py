"""
Metric watchers for automatic alert firing during training.

Provides reusable patterns for detecting common training issues:
- NaN/Inf values
- Loss spikes
- Stagnation (no improvement for N steps)
- Threshold violations

Usage:
    import trackio

    trackio.init(project="my_exp", name="run-1")
    trackio.watch("train/loss", nan=True, spike_factor=3.0, patience=100, max_value=50.0)
    trackio.watch("val/accuracy", patience=200, mode="max")

    for step in range(1000):
        loss = train_step()
        trackio.log({"train/loss": loss}, step=step)
        if trackio.should_stop():
            break
"""

import math
from collections import deque
from typing import Literal

from trackio.alerts import AlertLevel


class AlertReason:
    """String constants for the ``reason`` field in watcher-generated alert data.

    Use these to match alerts programmatically::

        for alert in run.alerts():
            if alert.get("data", {}).get("reason") == trackio.AlertReason.NAN_INF:
                ...
    """

    NAN_INF = "nan_inf"
    MAX_EXCEEDED = "max_exceeded"
    MIN_EXCEEDED = "min_exceeded"
    SPIKE = "spike"
    STAGNATION = "stagnation"


class MetricWatcher:
    def __init__(
        self,
        metric_name: str,
        nan: bool = True,
        spike_factor: float | None = None,
        patience: int | None = None,
        min_delta: float = 0.0,
        max_value: float | None = None,
        min_value: float | None = None,
        window: int = 5,
        mode: Literal["min", "max"] = "min",
    ):
        self.metric_name = metric_name
        self.check_nan = nan
        self.spike_factor = spike_factor
        self.patience = patience
        self.min_delta = min_delta
        self.max_value = max_value
        self.min_value = min_value
        self.window = window
        self.mode = mode

        self._values: deque[float] = deque(maxlen=window)
        self._best_value: float | None = None
        self._steps_without_improvement = 0
        self._triggered_stop = False
        self._stagnation_alerted = False
        self._spike_alerted = False
        self._max_alerted = False
        self._min_alerted = False

    def _is_improvement(self, value: float) -> bool:
        if self._best_value is None:
            return True
        if self.mode == "min":
            return value < self._best_value - self.min_delta
        return value > self._best_value + self.min_delta

    def check(self, value, step: int | None = None) -> list[dict]:
        alerts = []

        if not isinstance(value, (int, float)):
            return alerts

        if self.check_nan and (math.isnan(value) or math.isinf(value)):
            alerts.append(
                {
                    "title": f"NaN/Inf detected in {self.metric_name}",
                    "text": f"{self.metric_name} became {value} at step {step}",
                    "level": AlertLevel.ERROR,
                    "data": {
                        "metric": self.metric_name,
                        "value": value,
                        "step": step,
                        "reason": AlertReason.NAN_INF,
                    },
                }
            )
            self._triggered_stop = True
            return alerts

        if self.max_value is not None and value > self.max_value:
            if not self._max_alerted:
                alerts.append(
                    {
                        "title": f"{self.metric_name} exceeded threshold",
                        "text": f"{self.metric_name}={value:.4f} > max_value={self.max_value} at step {step}",
                        "level": AlertLevel.ERROR,
                        "data": {
                            "metric": self.metric_name,
                            "value": value,
                            "threshold": self.max_value,
                            "step": step,
                            "reason": AlertReason.MAX_EXCEEDED,
                        },
                    }
                )
                self._max_alerted = True
                self._triggered_stop = True
        elif self.max_value is not None:
            self._max_alerted = False

        if self.min_value is not None and value < self.min_value:
            if not self._min_alerted:
                alerts.append(
                    {
                        "title": f"{self.metric_name} below threshold",
                        "text": f"{self.metric_name}={value:.4f} < min_value={self.min_value} at step {step}",
                        "level": AlertLevel.WARN,
                        "data": {
                            "metric": self.metric_name,
                            "value": value,
                            "threshold": self.min_value,
                            "step": step,
                            "reason": AlertReason.MIN_EXCEEDED,
                        },
                    }
                )
                self._min_alerted = True
        elif self.min_value is not None:
            self._min_alerted = False

        if self.spike_factor is not None and len(self._values) >= self.window:
            recent_avg = sum(self._values) / len(self._values)
            abs_avg = abs(recent_avg)
            if abs_avg > 0 and abs(value - recent_avg) > abs_avg * (
                self.spike_factor - 1
            ):
                if not self._spike_alerted:
                    alerts.append(
                        {
                            "title": f"Spike detected in {self.metric_name}",
                            "text": f"{self.metric_name}={value:.4f} deviated {abs(value - recent_avg) / abs_avg:.1f}x from the recent average ({recent_avg:.4f}) at step {step}",
                            "level": AlertLevel.WARN,
                            "data": {
                                "metric": self.metric_name,
                                "value": value,
                                "recent_avg": recent_avg,
                                "factor": abs(value - recent_avg) / abs_avg,
                                "step": step,
                                "reason": AlertReason.SPIKE,
                            },
                        }
                    )
                    self._spike_alerted = True
            else:
                self._spike_alerted = False

        if self.patience is not None:
            if self._is_improvement(value):
                self._best_value = value
                self._steps_without_improvement = 0
                self._stagnation_alerted = False
            else:
                self._steps_without_improvement += 1

            if (
                self._steps_without_improvement >= self.patience
                and not self._stagnation_alerted
            ):
                alerts.append(
                    {
                        "title": f"{self.metric_name} stagnated",
                        "text": f"No improvement in {self.metric_name} for {self._steps_without_improvement} steps. Best: {self._best_value:.4f}, Current: {value:.4f}",
                        "level": AlertLevel.WARN,
                        "data": {
                            "metric": self.metric_name,
                            "value": value,
                            "best_value": self._best_value,
                            "steps_without_improvement": self._steps_without_improvement,
                            "step": step,
                            "reason": AlertReason.STAGNATION,
                        },
                    }
                )
                self._stagnation_alerted = True
                self._triggered_stop = True

        self._values.append(value)
        return alerts

    @property
    def should_stop(self) -> bool:
        return self._triggered_stop


class WatcherManager:
    def __init__(self):
        self._watchers: list[MetricWatcher] = []

    def add(self, watcher: MetricWatcher):
        self._watchers.append(watcher)

    def check(self, metrics: dict, step: int | None = None) -> list[dict]:
        all_alerts = []
        for watcher in self._watchers:
            if watcher.metric_name in metrics:
                alerts = watcher.check(metrics[watcher.metric_name], step)
                all_alerts.extend(alerts)
        return all_alerts

    @property
    def should_stop(self) -> bool:
        return any(w.should_stop for w in self._watchers)

    def clear(self):
        self._watchers.clear()
