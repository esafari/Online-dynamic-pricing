from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any


class MetricsRegistry:
    """Lightweight in-process counters/histograms. Prometheus is optional."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.counters: dict[str, float] = defaultdict(float)
        self.histograms: dict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, labels: dict[str, Any] | None = None, value: float = 1.0) -> None:
        key = self._key(name, labels)
        with self._lock:
            self.counters[key] += value

    def observe(self, name: str, value: float, labels: dict[str, Any] | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self.histograms[key].append(value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self.counters),
                "histograms": {k: self._summary(v) for k, v in self.histograms.items()},
            }

    @staticmethod
    def _key(name: str, labels: dict[str, Any] | None) -> str:
        if not labels:
            return name
        parts = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{parts}}}"

    @staticmethod
    def _summary(values: list[float]) -> dict[str, float]:
        if not values:
            return {"count": 0, "avg": 0.0}
        ordered = sorted(values)
        n = len(ordered)
        p99_idx = min(n - 1, int(n * 0.99))
        return {
            "count": n,
            "avg": sum(ordered) / n,
            "p50": ordered[n // 2],
            "p99": ordered[p99_idx],
        }


metrics = MetricsRegistry()
