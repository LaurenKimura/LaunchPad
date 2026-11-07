"""Read timestamps from a CSV or JSON telemetry file.

The functions are pure. They return UTC timestamps and never include the
file body in an error. Other columns are ignored, so a voltage or a note
cannot leak into a log or a DynamoDB row.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

TIMESTAMP_FIELDS = ("timestamp", "time", "ts")


class TelemetryError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def parse_telemetry(body: bytes, filename: str, *, max_rows: int) -> list[datetime]:
    if not body:
        raise TelemetryError("empty")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeError as exc:
        raise TelemetryError("unreadable") from exc
    if filename.endswith(".json"):
        return _parse_json(text, max_rows=max_rows)
    if filename.endswith(".csv"):
        return _parse_csv(text, max_rows=max_rows)
    raise TelemetryError("invalid_format")


def parse_timestamp(value: Any) -> datetime:
    """Accept ISO-8601 with a zone, naive ISO as UTC, or a Unix epoch."""

    if isinstance(value, bool) or value is None:
        raise TelemetryError("invalid_timestamp")
    if isinstance(value, (int, float)):
        return _from_epoch(float(value))
    text = str(value).strip()
    if not text:
        raise TelemetryError("invalid_timestamp")
    if text.isdigit() or _is_decimal(text):
        return _from_epoch(float(text))
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    if " " in candidate and "T" not in candidate:
        candidate = candidate.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise TelemetryError("invalid_timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_csv(text: str, *, max_rows: int) -> list[datetime]:
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise TelemetryError("invalid_format")
        field = _timestamp_field(reader.fieldnames)
        stamps: list[datetime] = []
        for row in reader:
            if row is None or not any((cell or "").strip() for cell in row.values()):
                continue
            _guard_row_count(len(stamps), max_rows)
            stamps.append(parse_timestamp(row.get(field)))
    except csv.Error as exc:
        raise TelemetryError("invalid_format") from exc
    if not stamps:
        raise TelemetryError("no_timestamps")
    return stamps


def _parse_json(text: str, *, max_rows: int) -> list[datetime]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TelemetryError("invalid_format") from exc
    rows = _json_rows(payload)
    stamps: list[datetime] = []
    for row in rows:
        _guard_row_count(len(stamps), max_rows)
        stamps.append(_json_timestamp(row))
    if not stamps:
        raise TelemetryError("no_timestamps")
    return stamps


def _json_rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("samples", "records", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise TelemetryError("invalid_format")


def _json_timestamp(row: Any) -> datetime:
    if isinstance(row, dict):
        for field in TIMESTAMP_FIELDS:
            if field in row:
                return parse_timestamp(row[field])
        lowered = {str(key).lower(): value for key, value in row.items()}
        for field in TIMESTAMP_FIELDS:
            if field in lowered:
                return parse_timestamp(lowered[field])
        raise TelemetryError("invalid_timestamp")
    return parse_timestamp(row)


def _timestamp_field(fieldnames: list[str]) -> str:
    by_lower = {name.strip().lower(): name for name in fieldnames if name}
    for field in TIMESTAMP_FIELDS:
        if field in by_lower:
            return by_lower[field]
    raise TelemetryError("invalid_format")


def _guard_row_count(count: int, max_rows: int) -> None:
    if count >= max_rows:
        raise TelemetryError("too_many_rows")


def _from_epoch(value: float) -> datetime:
    # 13-digit values are milliseconds. Seconds stay in the 10-digit range.
    seconds = value / 1000.0 if abs(value) >= 1_000_000_000_000 else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise TelemetryError("invalid_timestamp") from exc


def _is_decimal(text: str) -> bool:
    if text.count(".") != 1:
        return False
    left, right = text.split(".", 1)
    return left.isdigit() and right.isdigit()
