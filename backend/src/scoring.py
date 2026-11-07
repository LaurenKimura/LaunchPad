"""Independent 0-100 cause scores for one anomaly window.

Each function scores one cause and ignores the others. A result is clamped
to 0-100 on its own. The four numbers are not rescaled to sum to 100.
Weights come from scoring_weights.json. These functions do not read
telemetry, call Bedrock, or write to AWS.

These are estimates, not confirmed root causes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DISCLAIMER = "These scores are estimates, not confirmed root causes."
CAUSE_IDS = ("radiation", "eclipse_power", "geomagnetic", "software_system")


@dataclass(frozen=True)
class GapFacts:
    anomaly_id: str
    start: datetime
    end: datetime
    duration_seconds: float


@dataclass(frozen=True)
class IntervalEvent:
    """A space-weather interval already expanded to the times it can affect."""

    kind: str
    start: datetime
    end: datetime
    label: str
    flare_class: str | None = None


@dataclass(frozen=True)
class FluxSample:
    at: datetime
    value: float


@dataclass(frozen=True)
class OrbitSummary:
    """Counts from SGP4 samples. available is false when no TLE could be used."""

    available: bool
    ok_count: int = 0
    saa_count: int = 0
    eclipse_count: int = 0

    @property
    def saa_fraction(self) -> float:
        if self.ok_count <= 0:
            return 0.0
        return self.saa_count / self.ok_count

    @property
    def eclipse_fraction(self) -> float:
        if self.ok_count <= 0:
            return 0.0
        return self.eclipse_count / self.ok_count


@dataclass(frozen=True)
class CauseScore:
    cause_id: str
    score: int
    evidence: list[str]


def load_weights(path: str | Path | None = None) -> dict[str, Any]:
    chosen = Path(path) if path else Path(os.environ.get("SCORING_WEIGHTS_PATH", _default_weights()))
    with chosen.open(encoding="utf-8") as handle:
        return json.load(handle)


def score_window(
    window: GapFacts,
    events: list[IntervalEvent],
    protons: list[FluxSample],
    kp_samples: list[FluxSample],
    orbit: OrbitSummary,
    other_gaps: list[GapFacts],
    weights: dict[str, Any],
) -> list[CauseScore]:
    """Four scores. The list order is stable and each score is independent."""

    return [
        score_radiation(window, events, protons, orbit, weights),
        score_eclipse(window, orbit, weights),
        score_geomagnetic(window, events, kp_samples, weights),
        score_software(window, other_gaps, weights),
    ]


def score_radiation(
    window: GapFacts,
    events: list[IntervalEvent],
    protons: list[FluxSample],
    orbit: OrbitSummary,
    weights: dict[str, Any],
) -> CauseScore:
    """SEP, >=10 MeV flux, flare class, CME overlap, and time inside the SAA."""

    block = weights["radiation"]
    points = 0.0
    evidence: list[str] = []

    sep_fraction, sep_label = _best_overlap(window, events, "sep")
    if sep_fraction > 0 and sep_label:
        points += sep_fraction * float(block["sep_full_overlap"])
        evidence.append(f"SEP {sep_label} {_coverage(sep_fraction)}.")

    peak = _peak(protons)
    storm = float(block["proton_storm_pfu"])
    if peak is not None and peak >= storm:
        factor = min(1.0, peak / float(block["proton_flux_ceiling_pfu"]))
        points += factor * float(block["proton_flux_points"])
        evidence.append(f"Peak >=10 MeV proton flux in this gap was {peak:.0f} pfu.")

    flare_points, flare_label = _best_flare(window, events, block)
    if flare_points > 0 and flare_label:
        points += flare_points
        evidence.append(f"Flare {flare_label} overlaps this gap.")

    cme_fraction, cme_label = _best_overlap(window, events, "cme")
    if cme_fraction > 0 and cme_label:
        points += cme_fraction * float(block["cme_full_overlap"])
        evidence.append(f"CME {cme_label} {_coverage(cme_fraction)}.")

    if orbit.available and orbit.saa_fraction > 0:
        points += orbit.saa_fraction * float(block["saa_full"])
        evidence.append(
            "The satellite was inside the South Atlantic Anomaly for "
            f"{_percent(orbit.saa_fraction)} of the propagated samples "
            f"({orbit.saa_count} of {orbit.ok_count})."
        )

    if not evidence:
        evidence.append(
            "No SEP, elevated proton flux, flare, CME, or South Atlantic Anomaly time overlapped this gap."
        )
    return CauseScore("radiation", _clamp(points), evidence)


def score_eclipse(window: GapFacts, orbit: OrbitSummary, weights: dict[str, Any]) -> CauseScore:
    """Fraction of propagated samples in cylindrical Earth shadow."""

    del window
    if not orbit.available or orbit.ok_count == 0:
        return CauseScore(
            "eclipse_power",
            0,
            ["No TLE was available, so Earth-shadow time was not computed."],
        )
    fraction = orbit.eclipse_fraction
    points = fraction * float(weights["eclipse_power"]["full_eclipse"])
    if fraction <= 0:
        evidence = ["The satellite was in sunlight for every propagated sample in this gap."]
    else:
        evidence = [
            "The satellite was in Earth shadow for "
            f"{_percent(fraction)} of the propagated samples "
            f"({orbit.eclipse_count} of {orbit.ok_count})."
        ]
    return CauseScore("eclipse_power", _clamp(points), evidence)


def score_geomagnetic(
    window: GapFacts,
    events: list[IntervalEvent],
    kp_samples: list[FluxSample],
    weights: dict[str, Any],
) -> CauseScore:
    """Highest Kp in the window, plus a geomagnetic storm that overlaps it."""

    block = weights["geomagnetic"]
    points = 0.0
    evidence: list[str] = []
    peak = _peak(kp_samples)
    if peak is not None and peak > 0:
        points += min(1.0, peak / 9.0) * float(block["kp_at_9"])
        evidence.append(f"Highest Kp overlapping this gap was {_number(peak)}.")
    storms = [event for event in events if event.kind == "gst" and overlap_fraction(window, event) > 0]
    if storms:
        points += float(block["gst_overlap"])
        evidence.append(f"Geomagnetic storm {storms[0].label} overlaps this gap.")
    if not evidence:
        evidence.append("No elevated Kp sample and no geomagnetic storm overlapped this gap.")
    return CauseScore("geomagnetic", _clamp(points), evidence)


def score_software(window: GapFacts, other_gaps: list[GapFacts], weights: dict[str, Any]) -> CauseScore:
    """Repeating gap duration or spacing. This cause does not use space weather or orbit."""

    block = weights["software_system"]
    tolerance = float(block["duration_tolerance"])
    similar = [
        other
        for other in other_gaps
        if other.anomaly_id != window.anomaly_id and _similar_duration(window.duration_seconds, other.duration_seconds, tolerance)
    ]
    points = min(
        float(block["similar_cap"]),
        len(similar) * float(block["points_per_similar_gap"]),
    )
    evidence: list[str] = []
    if similar:
        evidence.append(
            f"{len(similar)} other gaps on this satellite lasted within {round(tolerance * 100)}% "
            f"of this {_duration(window.duration_seconds)} gap."
        )
    cadence = _cadence_seconds(window, other_gaps, block)
    if cadence is not None:
        points += float(block["cadence_points"])
        evidence.append(f"Gap starts on this satellite repeat about every {_duration(cadence)}.")
    if not evidence:
        evidence.append("No other gap on this satellite has a similar duration or a regular spacing.")
    return CauseScore("software_system", _clamp(points), evidence)


def interval_from_record(record: dict[str, Any], association_hours: dict[str, Any]) -> IntervalEvent | None:
    """Turn one stored space-weather row into the interval used for overlap.

    Flares use their begin and end. SEP, CME, and GST rows only have a start,
    so the association window in the config is how long that start still counts.
    """

    dataset = str(record.get("dataset") or "")
    if not dataset.startswith("donki_"):
        return None
    kind = dataset.removeprefix("donki_")
    start_text = record.get("beginTime") or record.get("startTime") or record.get("eventTime")
    if not isinstance(start_text, str):
        observed = str(record.get("observedAt") or "")
        start_text = observed.split("#", 1)[0]
    start = _parse_time(start_text)
    if start is None:
        return None
    end_text = record.get("endTime")
    if isinstance(end_text, str) and _parse_time(end_text) is not None:
        end = _parse_time(end_text)
    else:
        hours = float(association_hours.get(kind) or 0)
        end = start + timedelta(hours=hours)
    if end is None or end <= start:
        return None
    label = str(record.get("eventId") or kind)
    flare_class = _flare_letter(record.get("classType")) if kind == "flr" else None
    mapped = {"flr": "flare"}.get(kind, kind)
    return IntervalEvent(kind=mapped, start=start, end=end, label=label, flare_class=flare_class)


def samples_in_effect(
    samples: list[FluxSample],
    start: datetime,
    end: datetime,
    lookback_hours: float,
) -> list[FluxSample]:
    """Samples inside the gap, plus the latest sample in the lookback before it."""

    inside = [sample for sample in samples if start <= sample.at <= end]
    prior = [sample for sample in samples if start - timedelta(hours=lookback_hours) <= sample.at < start]
    if prior:
        inside.append(max(prior, key=lambda sample: sample.at))
    return inside


def overlap_fraction(window: GapFacts, event: IntervalEvent) -> float:
    duration = (window.end - window.start).total_seconds()
    if duration <= 0:
        return 0.0
    latest = max(window.start, event.start)
    earliest = min(window.end, event.end)
    overlap = (earliest - latest).total_seconds()
    if overlap <= 0:
        return 0.0
    return min(1.0, overlap / duration)


def _best_overlap(window: GapFacts, events: list[IntervalEvent], kind: str) -> tuple[float, str | None]:
    best = 0.0
    label = None
    for event in events:
        if event.kind != kind:
            continue
        fraction = overlap_fraction(window, event)
        if fraction > best:
            best = fraction
            label = event.label
    return best, label


def _best_flare(window: GapFacts, events: list[IntervalEvent], block: dict[str, Any]) -> tuple[float, str | None]:
    points = {"C": float(block["flare_c"]), "M": float(block["flare_m"]), "X": float(block["flare_x"])}
    best = 0.0
    label = None
    for event in events:
        if event.kind != "flare" or overlap_fraction(window, event) <= 0:
            continue
        earned = points.get(event.flare_class or "", 0.0)
        if earned > best:
            best = earned
            label = event.label
    return best, label


def _peak(samples: list[FluxSample]) -> float | None:
    if not samples:
        return None
    return max(sample.value for sample in samples)


def _similar_duration(left: float, right: float, tolerance: float) -> bool:
    if left <= 0 or right <= 0:
        return False
    return abs(left - right) / max(left, right) <= tolerance


def _cadence_seconds(window: GapFacts, other_gaps: list[GapFacts], block: dict[str, Any]) -> float | None:
    gaps = [window, *[other for other in other_gaps if other.anomaly_id != window.anomaly_id]]
    minimum = int(block["minimum_gaps_for_cadence"])
    if len(gaps) < minimum:
        return None
    ordered = sorted(gaps, key=lambda gap: gap.start)
    deltas = [
        (following.start - previous.start).total_seconds()
        for previous, following in zip(ordered, ordered[1:])
        if following.start > previous.start
    ]
    if len(deltas) < minimum - 1:
        return None
    median = sorted(deltas)[len(deltas) // 2]
    if median <= 0:
        return None
    tolerance = float(block["cadence_tolerance"])
    if all(abs(delta - median) / median <= tolerance for delta in deltas):
        return median
    return None


def _flare_letter(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    letter = value.strip().upper()[:1]
    if letter in {"C", "M", "X"}:
        return letter
    return None


def _parse_time(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _coverage(fraction: float) -> str:
    if fraction >= 0.999:
        return "covers the entire gap"
    return f"covers {_percent(fraction)} of this gap"


def _percent(fraction: float) -> str:
    return f"{round(fraction * 100)}%"


def _duration(seconds: float) -> str:
    if seconds >= 120:
        return f"{round(seconds / 60)} minutes"
    return f"{round(seconds)} seconds"


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _clamp(points: float) -> int:
    if points <= 0:
        return 0
    if points >= 100:
        return 100
    return int(points + 0.5)


def _default_weights() -> Path:
    return Path(__file__).with_name("scoring_weights.json")
