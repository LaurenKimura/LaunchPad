"""Limits for telemetry uploads.

Defaults apply when the Lambda environment does not override them.
MAX_UPLOAD_BYTES cannot be raised above HARD_MAX_UPLOAD_BYTES.
"""

from __future__ import annotations

import os

# 5 MiB is enough for a dense CSV of timestamps and stays small in the parser.
DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
HARD_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_UPLOAD_ROWS = 100_000
DEFAULT_GAP_MULTIPLIER = 2.0
DEFAULT_PRESIGN_EXPIRES_SECONDS = 900


def max_upload_bytes() -> int:
    return _bounded_int(
        "MAX_UPLOAD_BYTES",
        DEFAULT_MAX_UPLOAD_BYTES,
        low=1024,
        high=HARD_MAX_UPLOAD_BYTES,
    )


def max_upload_rows() -> int:
    return _bounded_int("MAX_UPLOAD_ROWS", DEFAULT_MAX_UPLOAD_ROWS, low=2, high=500_000)


def gap_multiplier() -> float:
    raw = os.environ.get("GAP_INTERVAL_MULTIPLIER", "").strip()
    if not raw:
        return DEFAULT_GAP_MULTIPLIER
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_GAP_MULTIPLIER
    if value <= 0:
        return DEFAULT_GAP_MULTIPLIER
    return value


def presign_expires_seconds() -> int:
    return _bounded_int(
        "PRESIGN_EXPIRES_SECONDS",
        DEFAULT_PRESIGN_EXPIRES_SECONDS,
        low=60,
        high=3600,
    )


def _bounded_int(name: str, default: int, *, low: int, high: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(max(value, low), high)
