"""Turn upstream payloads into DynamoDB items.

These functions are pure: the same payload always produces the same items.
They do not fetch, score, or talk to AWS.

Space-weather sort keys:
- NOAA samples use a plain ISO-8601 UTC timestamp, so "latest at or before T"
  is a reverse query on `observedAt <= T`.
- DONKI events use `{timestamp}#{eventId}`. Two events can start at the same
  second, and a plain timestamp would keep only one of them. A query whose
  end bound is `{end}~` still includes those ids, because `~` sorts after `#`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

# NOAA integral-proton channels we expect. Unknown labels still get a dataset
# name, so a new channel is stored instead of dropped.
PROTON_DATASETS = {
    ">=1 MeV": "noaa_proton_1mev",
    ">=5 MeV": "noaa_proton_5mev",
    ">=10 MeV": "noaa_proton_10mev",
    ">=30 MeV": "noaa_proton_30mev",
    ">=50 MeV": "noaa_proton_50mev",
    ">=60 MeV": "noaa_proton_60mev",
    ">=100 MeV": "noaa_proton_100mev",
    ">=500 MeV": "noaa_proton_500mev",
}

DONKI_ID_FIELDS = {
    "SEP": "sepID",
    "FLR": "flrID",
    "CME": "activityID",
    "GST": "gstID",
}

DONKI_TIME_FIELDS = {
    "SEP": ("eventTime",),
    "FLR": ("beginTime", "peakTime"),
    "CME": ("startTime",),
    "GST": ("startTime",),
}


class UnexpectedPayload(Exception):
    """The body parsed, but it is not a shape we can store."""


def normalize_kp(payload: Any, *, raw_s3_key: str, fetched_at: str) -> list[dict[str, Any]]:
    rows = _as_list(payload, "kp")
    if not rows:
        return []
    if isinstance(rows[0], dict):
        items = [_kp_from_object(row, raw_s3_key, fetched_at) for row in rows]
    elif isinstance(rows[0], list):
        items = [_kp_from_legacy_row(row, raw_s3_key, fetched_at) for row in rows]
    else:
        raise UnexpectedPayload("kp_row")
    return _dedupe([item for item in items if item], ("dataset", "observedAt"))


def normalize_protons(payload: Any, *, raw_s3_key: str, fetched_at: str) -> list[dict[str, Any]]:
    rows = _as_list(payload, "proton")
    items = []
    for row in rows:
        if not isinstance(row, dict):
            raise UnexpectedPayload("proton_row")
        observed = _time_text(row.get("time_tag"))
        energy = _text(row.get("energy"))
        flux = _decimal(row.get("flux"))
        if observed is None or energy is None or flux is None:
            continue
        items.append(
            _clean(
                {
                    "dataset": _proton_dataset(energy),
                    "observedAt": observed,
                    "source": "noaa_swpc",
                    "energy": energy,
                    "flux": flux,
                    "satellite": _decimal(row.get("satellite")),
                    "rawS3Key": raw_s3_key,
                    "fetchedAt": fetched_at,
                }
            )
        )
    return _dedupe(items, ("dataset", "observedAt"))


def normalize_donki(kind: str, payload: Any, *, raw_s3_key: str, fetched_at: str) -> list[dict[str, Any]]:
    kind = kind.upper()
    if kind not in DONKI_ID_FIELDS:
        raise UnexpectedPayload(f"donki_kind_{kind}")
    events = _donki_events(payload, kind)
    items = []
    for event in events:
        if not isinstance(event, dict):
            continue
        observed = _first_time(event, DONKI_TIME_FIELDS[kind])
        if observed is None:
            continue
        event_id = _text(event.get(DONKI_ID_FIELDS[kind])) or _synthetic_id(kind, event)
        item: dict[str, Any] = {
            "dataset": f"donki_{kind.lower()}",
            "observedAt": f"{observed}#{event_id.replace('#', '-')}",
            "eventId": event_id,
            "source": "nasa_donki",
            "rawS3Key": raw_s3_key,
            "fetchedAt": fetched_at,
        }
        if kind == "FLR":
            item.update(
                {
                    "beginTime": _time_text(event.get("beginTime")),
                    "peakTime": _time_text(event.get("peakTime")),
                    "endTime": _time_text(event.get("endTime")),
                    "classType": _text(event.get("classType")),
                    "sourceLocation": _text(event.get("sourceLocation")),
                    "activeRegion": _text(event.get("activeRegionNum")),
                }
            )
        elif kind == "SEP":
            item["eventTime"] = observed
        elif kind == "CME":
            item["startTime"] = observed
            item["sourceLocation"] = _text(event.get("sourceLocation"))
            speed = _cme_speed(event.get("cmeAnalyses"))
            if speed is not None:
                item["speedKmPerSec"] = speed
        elif kind == "GST":
            item["startTime"] = observed
            max_kp = _max_kp(event.get("allKpIndex"))
            if max_kp is not None:
                item["maxKp"] = max_kp
        names = _instrument_names(event.get("instruments"))
        if names:
            item["instruments"] = names
        linked = event.get("linkedEvents")
        if isinstance(linked, list):
            item["linkedEventCount"] = Decimal(len(linked))
        items.append(_clean(item))
    return _dedupe(items, ("dataset", "observedAt"))


def normalize_tle(satellite_id: str, body: bytes, *, raw_s3_key: str, fetched_at: str) -> list[dict[str, Any]]:
    """Parse a CelesTrak 3LE / TLE body into one cache item per element set."""

    records = parse_tle_text(body.decode("utf-8", errors="replace"))
    if not records:
        raise UnexpectedPayload("tle_empty")
    items = []
    for record in records:
        items.append(
            _clean(
                {
                    "satelliteId": satellite_id,
                    "epoch": record["epoch"],
                    "noradId": record["noradId"],
                    "objectName": record["name"],
                    "line1": record["line1"],
                    "line2": record["line2"],
                    "source": "celestrak",
                    "rawS3Key": raw_s3_key,
                    "fetchedAt": fetched_at,
                }
            )
        )
    return _dedupe(items, ("satelliteId", "epoch"))


def parse_tle_text(text: str) -> list[dict[str, str]]:
    """Group a 3LE document into name, line 1, and line 2.

    A line that does not start a element pair is the object name that belongs
    to the next pair. Catalog numbers come from line 1, columns 3-7.
    """

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records: list[dict[str, str]] = []
    name = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        has_pair = (
            line.startswith("1 ")
            and index + 1 < len(lines)
            and lines[index + 1].startswith("2 ")
            and len(line) >= 69
            and len(lines[index + 1]) >= 69
        )
        if not has_pair:
            name = line
            index += 1
            continue
        line1 = line
        line2 = lines[index + 1]
        try:
            norad_id = str(int(line1[2:7].strip()))
            epoch = tle_epoch_iso(line1)
        except (ValueError, IndexError) as exc:
            raise UnexpectedPayload("tle_unreadable") from exc
        records.append(
            {
                "name": name,
                "line1": line1,
                "line2": line2,
                "noradId": norad_id,
                "epoch": epoch,
            }
        )
        name = ""
        index += 2
    return records


def tle_epoch_iso(line1: str) -> str:
    """Convert TLE epoch columns 19-32 to an ISO-8601 UTC timestamp.

    Years 57-99 are 1957-1999. Years 00-56 are 2000-2056. The day number is
    the day of the year, and day 1 is January 1.
    """

    year_two = int(line1[18:20])
    year = 2000 + year_two if year_two < 57 else 1900 + year_two
    day_of_year = float(line1[20:32])
    stamp = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_of_year - 1)
    # The cache key is whole seconds. Sub-second TLE fractions round to the
    # nearest second so a repeat fetch hits the same item.
    if stamp.microsecond >= 500_000:
        stamp += timedelta(seconds=1)
    stamp = stamp.replace(microsecond=0)
    return _iso(stamp)


def loads_json(body: bytes) -> Any:
    """Parse JSON with Decimal numbers so DynamoDB gets exact decimal text."""

    try:
        return json.loads(body.decode("utf-8"), parse_float=Decimal, parse_int=Decimal)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UnexpectedPayload("invalid_json") from exc


def _donki_events(payload: Any, kind: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error")
        if message:
            raise UnexpectedPayload(str(message)[:200])
        for key in (kind, kind.lower(), "events"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise UnexpectedPayload(f"{kind}_type")


def _kp_from_object(row: Any, raw_s3_key: str, fetched_at: str) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    observed = _time_text(row.get("time_tag"))
    kp = _decimal(row.get("Kp", row.get("kp")))
    if observed is None or kp is None:
        return None
    return _clean(
        {
            "dataset": "noaa_kp",
            "observedAt": observed,
            "source": "noaa_swpc",
            "kp": kp,
            "aRunning": _decimal(row.get("a_running")),
            "stationCount": _decimal(row.get("station_count")),
            "rawS3Key": raw_s3_key,
            "fetchedAt": fetched_at,
        }
    )


def _kp_from_legacy_row(row: Any, raw_s3_key: str, fetched_at: str) -> dict[str, Any] | None:
    # Older SWPC files were arrays of arrays, with a header row first.
    if not isinstance(row, list) or len(row) < 2:
        return None
    if str(row[0]).strip() == "time_tag":
        return None
    observed = _time_text(row[0])
    kp = _decimal(row[1])
    if observed is None or kp is None:
        return None
    return _clean(
        {
            "dataset": "noaa_kp",
            "observedAt": observed,
            "source": "noaa_swpc",
            "kp": kp,
            "aRunning": _decimal(row[2]) if len(row) > 2 else None,
            "stationCount": _decimal(row[3]) if len(row) > 3 else None,
            "rawS3Key": raw_s3_key,
            "fetchedAt": fetched_at,
        }
    )


def _cme_speed(analyses: Any) -> Decimal | None:
    if not isinstance(analyses, list):
        return None
    chosen = None
    for analysis in analyses:
        if not isinstance(analysis, dict):
            continue
        if analysis.get("isMostAccurate") is True:
            chosen = analysis
            break
        if chosen is None:
            chosen = analysis
    if chosen is None:
        return None
    return _decimal(chosen.get("speed"))


def _max_kp(samples: Any) -> Decimal | None:
    if not isinstance(samples, list):
        return None
    values = [_decimal(sample.get("kpIndex")) for sample in samples if isinstance(sample, dict)]
    numbers = [value for value in values if value is not None]
    if not numbers:
        return None
    return max(numbers)


def _instrument_names(instruments: Any) -> str | None:
    if not isinstance(instruments, list):
        return None
    names: list[str] = []
    for instrument in instruments:
        if isinstance(instrument, dict) and instrument.get("displayName"):
            names.append(str(instrument["displayName"]))
        elif isinstance(instrument, str):
            names.append(instrument)
    if not names:
        return None
    return ",".join(names)[:500]


def _proton_dataset(energy: str) -> str:
    known = PROTON_DATASETS.get(energy)
    if known:
        return known
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in energy).strip("_")
    return f"noaa_proton_{slug or 'unknown'}"


def _synthetic_id(kind: str, event: dict[str, Any]) -> str:
    encoded = json.dumps(event, sort_keys=True, default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]
    return f"{kind}-{digest}"


def _first_time(event: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        parsed = _time_text(event.get(field))
        if parsed:
            return parsed
    return None


def _time_text(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    candidate = text.replace("Z", "+00:00")
    if " " in candidate and "T" not in candidate:
        candidate = candidate.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # SWPC timestamps that omit a zone are UTC.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _iso(parsed.astimezone(timezone.utc).replace(microsecond=0))


def _iso(stamp: datetime) -> str:
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:500]


def _as_list(payload: Any, label: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error")
        if message:
            raise UnexpectedPayload(str(message)[:200])
    raise UnexpectedPayload(f"{label}_type")


def _clean(item: dict[str, Any]) -> dict[str, Any]:
    """DynamoDB rejects empty strings. Leave those attributes off the item."""

    cleaned = {}
    for key, value in item.items():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        cleaned[key] = value
    return cleaned


def _dedupe(items: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    # A BatchWriteItem call rejects two puts of the same key. Last row wins.
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in items:
        by_key[tuple(item[field] for field in key_fields)] = item
    return list(by_key.values())
