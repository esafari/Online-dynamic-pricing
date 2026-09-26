from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pricing_decision.core.metrics import metrics


class DecisionLogger:
    """At-least-once local buffer. Kafka is optional and never blocks the response."""

    def __init__(self, buffer_dir: Path, *, kafka_enabled: bool = False, topic: str = "pricing.decisions.v1"):
        self.buffer_dir = buffer_dir
        self.buffer_dir.mkdir(parents=True, exist_ok=True)
        self.kafka_enabled = kafka_enabled
        self.topic = topic
        self._path = self.buffer_dir / "decisions.jsonl"

    def emit(self, experience: dict[str, Any]) -> bool:
        try:
            line = json.dumps(experience, default=str)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            metrics.inc("pds_log_success_rate")
            return True
        except OSError:
            metrics.inc("pds_log_schema_errors_total", {"reason": "io"})
            return False

    def buffer_size(self) -> int:
        if not self._path.exists():
            return 0
        with self._path.open("r", encoding="utf-8") as fh:
            return sum(1 for _ in fh)
