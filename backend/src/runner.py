"""Fetch each external source, archive the body, and store normalized rows.

One source failing does not stop the others. Existing S3 cache objects and
DynamoDB rows are left in place when an upstream call fails, so the dashboard
keeps the last good sample through an outage.

A run returns its summary and does not raise for an upstream outage. The next
hour tries that source again. A missing environment variable still raises,
because that is a deploy error rather than an outage.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from http_client import Conditional, HttpClient, HttpFailed, HttpResult
from normalize import UnexpectedPayload, loads_json, normalize_donki, normalize_kp, normalize_protons, normalize_tle
from sources import DONKI_KINDS, NOAA_KP_URL, NOAA_PROTON_URL, celestrak_tle_url, donki_url
from store import CacheRecord, DynamoWriter, RawStore, SatelliteDirectory, StoreError

logger = logging.getLogger("launchpad.fetch")

SUCCESS = {"ok", "cached", "skipped"}
_SECRET_IN_URL = re.compile(r"(api_key=)[^&\s]+", re.IGNORECASE)


@dataclass
class Deps:
    http: HttpClient
    raw: RawStore
    space_weather: DynamoWriter
    tle: DynamoWriter
    satellites: SatelliteDirectory
    secret_reader: Callable[[], str]
    now: Callable[[], datetime]
    lookback_days: int = 7


def run(deps: Deps) -> dict[str, Any]:
    # Read the key once and reuse it for every DONKI catalog. A missing key
    # does not block NOAA or CelesTrak.
    api_key, key_error = _read_api_key(deps)
    secret = api_key or ""
    results = [
        _guard("noaa_kp", lambda: _refresh_json(
            deps,
            source="noaa_kp",
            url=NOAA_KP_URL,
            cache_key="cache/noaa/kp.json",
            normalize=normalize_kp,
            writer=deps.space_weather,
        ), secret),
        _guard("noaa_proton", lambda: _refresh_json(
            deps,
            source="noaa_proton",
            url=NOAA_PROTON_URL,
            cache_key="cache/noaa/protons-1-day.json",
            normalize=normalize_protons,
            writer=deps.space_weather,
        ), secret),
    ]
    for kind in DONKI_KINDS:
        source = f"donki_{kind.lower()}"
        if key_error:
            results.append({"source": source, "status": "outage", "items": 0, "error": key_error})
            logger.warning("external_fetch_outage source=%s error=%s", source, key_error)
            continue
        results.append(_guard(source, lambda kind=kind: _refresh_donki(deps, kind, secret), secret))
    results.append(_guard("celestrak_tle", lambda: _refresh_tles(deps, secret), secret))
    return {
        "ok": all(item["status"] in SUCCESS for item in results),
        "results": results,
    }


def _refresh_json(
    deps: Deps,
    *,
    source: str,
    url: str,
    cache_key: str,
    normalize: Callable[..., list[dict[str, Any]]],
    writer: DynamoWriter,
) -> dict[str, Any]:
    cache = _load_cache(deps, cache_key)
    fetched = deps.http.fetch(url, _conditional(cache))
    if _unchanged(cache, fetched):
        return {"source": source, "status": "cached", "items": 0}
    stamp = _stamp(deps.now())
    archive_key = f"raw/{source}/{stamp[:10]}/{stamp}.json"
    # Archive first so the raw body is kept even if normalization rejects it.
    deps.raw.save_archive(archive_key, fetched.body, "application/json")
    try:
        payload = loads_json(fetched.body)
        items = normalize(payload, raw_s3_key=archive_key, fetched_at=stamp)
    except UnexpectedPayload as exc:
        raise HttpFailed(str(exc)) from exc
    writer.put_all(items)
    # The cache key moves only after the rows are stored. A bad body or a
    # failed write leaves the previous cache in place for the next hour.
    deps.raw.save_cache(
        cache_key,
        fetched.body,
        "application/json",
        etag=fetched.etag,
        last_modified=fetched.last_modified,
        fetched_at=stamp,
    )
    return {"source": source, "status": "ok", "items": len(items)}


def _refresh_donki(deps: Deps, kind: str, api_key: str) -> dict[str, Any]:
    today = deps.now().astimezone(timezone.utc).date()
    url = donki_url(kind, api_key=api_key, today=today, lookback_days=deps.lookback_days)
    source = f"donki_{kind.lower()}"
    try:
        return _refresh_json(
            deps,
            source=source,
            url=url,
            cache_key=f"cache/donki/{kind}.json",
            normalize=lambda payload, raw_s3_key, fetched_at: normalize_donki(
                kind, payload, raw_s3_key=raw_s3_key, fetched_at=fetched_at
            ),
            writer=deps.space_weather,
        )
    except HttpFailed as exc:
        raise HttpFailed(_redact(str(exc), api_key)) from exc


def _refresh_tles(deps: Deps, secret: str) -> dict[str, Any]:
    tracked = deps.satellites.tracked()
    if not tracked:
        return {"source": "celestrak_tle", "status": "skipped", "items": 0, "reason": "no_tracked_satellites"}

    written = 0
    cached = 0
    failed: list[dict[str, str]] = []
    for satellite in tracked:
        satellite_id = satellite["satelliteId"]
        norad_id = satellite["noradId"]
        try:
            outcome = _refresh_one_tle(deps, satellite_id, norad_id)
        except (HttpFailed, UnexpectedPayload, StoreError) as exc:
            message = _redact(str(exc), secret)
            failed.append({"satelliteId": satellite_id, "error": message})
            logger.warning(
                "external_fetch_outage source=celestrak_tle satelliteId=%s error=%s",
                satellite_id,
                message,
            )
            continue
        if outcome == "cached":
            cached += 1
        else:
            written += outcome
    if failed and written == 0 and cached == 0:
        return {"source": "celestrak_tle", "status": "outage", "items": 0, "failed": len(failed)}
    status = "partial" if failed else ("cached" if written == 0 else "ok")
    return {
        "source": "celestrak_tle",
        "status": status,
        "items": written,
        "cached": cached,
        "failed": len(failed),
    }


def _refresh_one_tle(deps: Deps, satellite_id: str, norad_id: str) -> int | str:
    cache_key = f"cache/celestrak/{norad_id}.tle"
    cache = _load_cache(deps, cache_key)
    fetched = deps.http.fetch(celestrak_tle_url(norad_id), _conditional(cache))
    if _unchanged(cache, fetched):
        return "cached"
    if not fetched.body.strip():
        raise UnexpectedPayload("tle_empty")
    stamp = _stamp(deps.now())
    archive_key = f"raw/celestrak/{norad_id}/{stamp[:10]}/{stamp}.tle"
    deps.raw.save_archive(archive_key, fetched.body, "text/plain")
    items = normalize_tle(satellite_id, fetched.body, raw_s3_key=archive_key, fetched_at=stamp)
    # Refuse a body whose catalog number is not the one we asked for.
    for item in items:
        if item.get("noradId") != norad_id:
            raise UnexpectedPayload("norad_mismatch")
    deps.tle.put_all(items)
    deps.raw.save_cache(
        cache_key,
        fetched.body,
        "text/plain",
        etag=fetched.etag,
        last_modified=fetched.last_modified,
        fetched_at=stamp,
    )
    return len(items)


def _load_cache(deps: Deps, key: str) -> CacheRecord | None:
    try:
        return deps.raw.load(key)
    except Exception:
        # A cache miss because S3 had a hiccup is not a reason to skip the fetch.
        logger.warning("external_fetch_cache_miss key=%s", key)
        return None


def _conditional(cache: CacheRecord | None) -> Conditional | None:
    if cache is None:
        return None
    if not cache.etag and not cache.last_modified:
        return None
    return Conditional(etag=cache.etag, last_modified=cache.last_modified)


def _unchanged(cache: CacheRecord | None, fetched: HttpResult) -> bool:
    if fetched.not_modified:
        return True
    if cache is None:
        return False
    return cache.body_sha256 == hashlib.sha256(fetched.body).hexdigest()


def _read_api_key(deps: Deps) -> tuple[str | None, str | None]:
    try:
        key = deps.secret_reader().strip()
    except Exception:
        return None, "nasa_secret_unreadable"
    if not key:
        return None, "nasa_api_key_missing"
    if key.startswith("{") or key.startswith("["):
        parsed = _key_from_json(key)
        if not parsed:
            return None, "nasa_api_key_missing"
        return parsed, None
    return key, None


def _key_from_json(text: str) -> str:
    import json

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    value = payload.get("api_key") or payload.get("NASA_API_KEY") or ""
    return str(value).strip()


def _guard(source: str, action: Callable[[], dict[str, Any]], secret: str) -> dict[str, Any]:
    try:
        result = action()
    except (HttpFailed, UnexpectedPayload, StoreError) as exc:
        message = _redact(str(exc), secret)
        logger.warning("external_fetch_outage source=%s error=%s", source, message)
        return {"source": source, "status": "outage", "items": 0, "error": message}
    except Exception as exc:
        # Keep the class name only. The message might echo a request URL.
        logger.warning("external_fetch_outage source=%s error=%s", source, type(exc).__name__)
        return {"source": source, "status": "outage", "items": 0, "error": type(exc).__name__}
    logger.info(
        "external_fetch_done source=%s status=%s items=%s",
        result.get("source", source),
        result.get("status"),
        result.get("items", 0),
    )
    return result


def _stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact(text: str, secret: str) -> str:
    cleaned = _SECRET_IN_URL.sub(r"\1REDACTED", text)
    if secret:
        cleaned = cleaned.replace(secret, "REDACTED")
    return cleaned


def lookback_from_env() -> int:
    raw = os.environ.get("DONKI_LOOKBACK_DAYS", "7").strip()
    try:
        return min(max(int(raw), 1), 30)
    except ValueError:
        return 7
