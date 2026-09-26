from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def uuid7() -> str:
    """Time-ordered UUID (RFC 9562 style) without requiring Python 3.13."""
    if hasattr(uuid, "uuid7"):
        return str(uuid.uuid7())

    unix_ts_ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    time_hi = unix_ts_ms & 0xFFFFFFFFFFFF
    uuid_int = (time_hi << 80) | (0x7 << 76) | ((rand >> 62) << 64) | (0b10 << 62) | (rand & ((1 << 62) - 1))
    return str(uuid.UUID(int=uuid_int))


def new_trace_ids() -> tuple[str, str]:
    return uuid.uuid4().hex, uuid.uuid4().hex[:16]
