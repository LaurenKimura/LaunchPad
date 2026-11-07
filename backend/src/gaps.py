"""Find gaps in a telemetry timeline.

A gap is a pair of neighboring samples whose separation is more than
`multiplier` times the median positive sampling interval. The default
multiplier is 2. Duplicate timestamps are not sampling intervals, so they
do not pull the median down to zero.

The window starts at the last sample before the hole and ends at the next
sample. These functions do not read files or write scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class GapWindow:
    start: datetime
    end: datetime
    gap_seconds: Decimal
    median_seconds: Decimal
    threshold_seconds: Decimal


def find_gaps(timestamps: list[datetime], *, multiplier: float) -> tuple[Decimal | None, list[GapWindow]]:
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    ordered = sorted(stamp.astimezone(timezone.utc) for stamp in timestamps)
    intervals: list[tuple[datetime, datetime, int]] = []
    for previous, following in zip(ordered, ordered[1:]):
        delta = following - previous
        if delta <= timedelta(0):
            continue
        intervals.append((previous, following, _microseconds(delta)))
    if not intervals:
        return None, []
    median_us = _median([delta for _, _, delta in intervals])
    threshold_us = median_us * Decimal(str(multiplier))
    windows: list[GapWindow] = []
    for previous, following, delta_us in intervals:
        if Decimal(delta_us) > threshold_us:
            windows.append(
                GapWindow(
                    start=previous,
                    end=following,
                    gap_seconds=_seconds(delta_us),
                    median_seconds=_seconds(median_us),
                    threshold_seconds=_seconds(threshold_us),
                )
            )
    return _seconds(median_us), windows


def anomaly_items(
    *,
    upload_id: str,
    satellite_id: str,
    windows: list[GapWindow],
    parsed_at: str,
) -> list[dict[str, Any]]:
    """One DynamoDB item per window. The sort key is `{start}#{anomalyId}`."""

    items = []
    for index, window in enumerate(windows, start=1):
        anomaly_id = f"gap-{index:04d}"
        start = iso_utc(window.start)
        items.append(
            {
                "uploadId": upload_id,
                "startTimeAnomalyId": f"{start}#{anomaly_id}",
                "anomalyId": anomaly_id,
                "satelliteId": satellite_id,
                "startTime": start,
                "endTime": iso_utc(window.end),
                "gapSeconds": window.gap_seconds,
                "medianIntervalSeconds": window.median_seconds,
                "thresholdSeconds": window.threshold_seconds,
                "parsedAt": parsed_at,
            }
        )
    return items


def iso_utc(stamp: datetime) -> str:
    utc = stamp.astimezone(timezone.utc)
    if utc.microsecond:
        millis = utc.microsecond // 1000
        return utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _microseconds(delta: timedelta) -> int:
    return delta // timedelta(microseconds=1)


def _median(values: list[int]) -> Decimal:
    ordered = sorted(values)
    count = len(ordered)
    mid = count // 2
    if count % 2 == 1:
        return Decimal(ordered[mid])
    return (Decimal(ordered[mid - 1]) + Decimal(ordered[mid])) / Decimal(2)


def _seconds(microseconds: Decimal | int) -> Decimal:
    return (Decimal(microseconds) / Decimal(1_000_000)).quantize(Decimal("0.001"))
