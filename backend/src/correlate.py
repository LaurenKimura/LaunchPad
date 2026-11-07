"""Score every anomaly window for one upload.

The parser invokes this function with the upload id and satellite id only.
Scores are written to CauseScores. Raw telemetry is not an input and is not
logged. A missing TLE still produces the four scores; eclipse and SAA stay at
zero and the evidence says why.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from gaps import iso_utc
from propagate import propagate_window, settings_from_weights
from scoring import (
    DISCLAIMER,
    CauseScore,
    FluxSample,
    GapFacts,
    OrbitSummary,
    interval_from_record,
    load_weights,
    samples_in_effect,
    score_window,
)
from store import DynamoWriter, StoreError

logger = logging.getLogger("launchpad.correlate")


@dataclass
class CorrelateDeps:
    records: Any
    writer: DynamoWriter
    weights: dict[str, Any]
    now: Callable[[], datetime]


def handler(event: dict[str, Any] | None, context: object) -> dict[str, Any]:
    del context
    return handle_event(event or {}, deps_from_env())


def handle_event(event: dict[str, Any], deps: CorrelateDeps) -> dict[str, Any]:
    upload_id = event.get("uploadId")
    satellite_id = event.get("satelliteId")
    if not isinstance(upload_id, str) or not upload_id.strip():
        logger.info("correlate_ignored error=invalid_event")
        return {"status": "ignored"}
    if not isinstance(satellite_id, str) or not satellite_id.strip():
        logger.info("correlate_ignored error=invalid_event")
        return {"status": "ignored"}
    return correlate_upload(upload_id.strip(), satellite_id.strip(), deps)


def correlate_upload(upload_id: str, satellite_id: str, deps: CorrelateDeps) -> dict[str, Any]:
    rows = [
        row
        for row in deps.records.anomalies_for_upload(upload_id)
        if row.get("satelliteId") == satellite_id and row.get("anomalyId")
    ]
    if not rows:
        logger.info("correlate_empty uploadId=%s", upload_id)
        return {"status": "empty", "uploadId": upload_id, "anomalies": 0, "scores": 0}

    windows = [_gap(row) for row in rows]
    history = _history_gaps(deps, satellite_id, windows)
    weather = deps.records.weather_between(*_query_span(windows, deps.weights))
    events = [event for row in weather if (event := interval_from_record(row, deps.weights["association_hours"]))]
    protons = _flux_samples(weather, "noaa_proton_10mev", "flux")
    kp_samples = _flux_samples(weather, "noaa_kp", "kp")
    settings = settings_from_weights(deps.weights)
    lookback = deps.weights["association_hours"]
    scored_at = iso_utc(deps.now())
    version = str(deps.weights.get("version") or "")
    items: list[dict[str, Any]] = []

    for window in windows:
        tle = deps.records.tle_before(satellite_id, iso_utc(window.start))
        orbit = _orbit(tle, window, settings)
        others = [gap for gap in history if gap.anomaly_id != window.anomaly_id]
        scores = score_window(
            window,
            events,
            samples_in_effect(protons, window.start, window.end, float(lookback["proton"])),
            samples_in_effect(kp_samples, window.start, window.end, float(lookback["kp"])),
            orbit,
            others,
            deps.weights,
        )
        items.extend(_score_items(upload_id, satellite_id, window.anomaly_id, scores, scored_at, version))
        logger.info(
            "anomaly_scored uploadId=%s anomalyId=%s radiation=%s eclipse_power=%s geomagnetic=%s software_system=%s",
            upload_id,
            window.anomaly_id,
            scores[0].score,
            scores[1].score,
            scores[2].score,
            scores[3].score,
        )

    deps.writer.put_all(items)
    logger.info("scores_written uploadId=%s anomalies=%s scores=%s", upload_id, len(windows), len(items))
    return {"status": "scored", "uploadId": upload_id, "anomalies": len(windows), "scores": len(items)}


def deps_from_env() -> CorrelateDeps:
    import boto3

    dynamodb = boto3.client("dynamodb")
    return CorrelateDeps(
        records=DynamoRecords(
            dynamodb,
            anomalies_table=_required("ANOMALIES_TABLE_NAME"),
            space_weather_table=_required("SPACE_WEATHER_TABLE_NAME"),
            tle_table=_required("TLE_TABLE_NAME"),
        ),
        writer=DynamoWriter(dynamodb, _required("CAUSE_SCORES_TABLE_NAME")),
        weights=load_weights(),
        now=lambda: datetime.now(timezone.utc),
    )


class DynamoRecords:
    """Queries used by correlation. The upload read is consistent so a just-written gap is visible."""

    def __init__(self, client: Any, anomalies_table: str, space_weather_table: str, tle_table: str) -> None:
        self._client = client
        self._anomalies = anomalies_table
        self._weather = space_weather_table
        self._tle = tle_table

    def anomalies_for_upload(self, upload_id: str) -> list[dict[str, Any]]:
        items = _query(
            self._client,
            {
                "TableName": self._anomalies,
                "KeyConditionExpression": "uploadId = :upload",
                "ExpressionAttributeValues": {":upload": {"S": upload_id}},
                "ConsistentRead": True,
            },
        )
        return [from_dynamo(item) for item in items]

    def recent_anomalies(self, satellite_id: str, limit: int) -> list[dict[str, Any]]:
        items = _query(
            self._client,
            {
                "TableName": self._anomalies,
                "IndexName": "bySatellite",
                "KeyConditionExpression": "satelliteId = :satellite",
                "ExpressionAttributeValues": {":satellite": {"S": satellite_id}},
                "ScanIndexForward": False,
                "Limit": limit,
            },
        )
        return [from_dynamo(item) for item in items]

    def weather_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        start_key = iso_utc(start)
        end_key = iso_utc(end) + "~"
        found: list[dict[str, Any]] = []
        for dataset in (
            "donki_sep",
            "donki_flr",
            "donki_cme",
            "donki_gst",
            "noaa_kp",
            "noaa_proton_10mev",
        ):
            items = _query(
                self._client,
                {
                    "TableName": self._weather,
                    "KeyConditionExpression": "dataset = :dataset AND observedAt BETWEEN :start AND :end",
                    "ExpressionAttributeValues": {
                        ":dataset": {"S": dataset},
                        ":start": {"S": start_key},
                        ":end": {"S": end_key},
                    },
                },
            )
            found.extend(from_dynamo(item) for item in items)
        return found

    def tle_before(self, satellite_id: str, at_iso: str) -> dict[str, Any] | None:
        items = _query(
            self._client,
            {
                "TableName": self._tle,
                "KeyConditionExpression": "satelliteId = :satellite AND epoch <= :at",
                "ExpressionAttributeValues": {
                    ":satellite": {"S": satellite_id},
                    ":at": {"S": at_iso},
                },
                "ScanIndexForward": False,
                "Limit": 1,
            },
        )
        if not items:
            return None
        return from_dynamo(items[0])


def from_dynamo(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _from_attr(value) for key, value in item.items()}


def _history_gaps(deps: CorrelateDeps, satellite_id: str, windows: list[GapFacts]) -> list[GapFacts]:
    limit = int(deps.weights["software_system"]["history_limit"])
    by_id = {window.anomaly_id: window for window in windows}
    for row in deps.records.recent_anomalies(satellite_id, limit):
        if row.get("anomalyId") and row.get("startTime") and row.get("endTime"):
            gap = _gap(row)
            by_id.setdefault(gap.anomaly_id, gap)
    return list(by_id.values())


def _orbit(tle: dict[str, Any] | None, window: GapFacts, settings: Any) -> OrbitSummary:
    if not tle or not tle.get("line1") or not tle.get("line2"):
        return OrbitSummary(available=False)
    result = propagate_window(str(tle["line1"]), str(tle["line2"]), window.start, window.end, settings)
    usable = [sample for sample in result.samples if sample.ok]
    if result.failure or not usable:
        return OrbitSummary(available=False)
    return OrbitSummary(
        available=True,
        ok_count=len(usable),
        saa_count=sum(1 for sample in usable if sample.in_saa),
        eclipse_count=sum(1 for sample in usable if sample.in_eclipse),
    )


def _score_items(
    upload_id: str,
    satellite_id: str,
    anomaly_id: str,
    scores: list[CauseScore],
    scored_at: str,
    version: str,
) -> list[dict[str, Any]]:
    items = []
    for score in scores:
        items.append(
            {
                "anomalyId": anomaly_id,
                "causeId": score.cause_id,
                "uploadId": upload_id,
                "satelliteId": satellite_id,
                "anomalyIdCauseId": f"{anomaly_id}#{score.cause_id}",
                "score": score.score,
                "evidence": score.evidence,
                "weightsVersion": version,
                "scoredAt": scored_at,
                "disclaimer": DISCLAIMER,
            }
        )
    return items


def _gap(row: dict[str, Any]) -> GapFacts:
    start = _required_time(row.get("startTime"))
    end = _required_time(row.get("endTime"))
    duration = row.get("gapSeconds")
    if isinstance(duration, Decimal):
        seconds = float(duration)
    elif isinstance(duration, (int, float)) and not isinstance(duration, bool):
        seconds = float(duration)
    else:
        seconds = (end - start).total_seconds()
    return GapFacts(str(row["anomalyId"]), start, end, seconds)


def _flux_samples(rows: list[dict[str, Any]], dataset: str, field: str) -> list[FluxSample]:
    samples = []
    for row in rows:
        if row.get("dataset") != dataset:
            continue
        moment = _required_time(str(row.get("observedAt") or "").split("#", 1)[0])
        value = row.get(field)
        if isinstance(value, Decimal):
            number = float(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
        else:
            continue
        samples.append(FluxSample(moment, number))
    return samples


def _query_span(windows: list[GapFacts], weights: dict[str, Any]) -> tuple[datetime, datetime]:
    lookback = float(weights["association_hours"]["query_lookback"])
    start = min(window.start for window in windows) - timedelta(hours=lookback)
    end = max(window.end for window in windows)
    return start, end


def _query(client: Any, kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    while len(found) < 500:
        try:
            response = client.query(**kwargs)
        except Exception as exc:
            raise StoreError("dynamodb_query_failed") from exc
        found.extend(response.get("Items") or [])
        last = response.get("LastEvaluatedKey")
        if not last:
            return found
        kwargs["ExclusiveStartKey"] = last
    return found


def _required_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise StoreError("anomaly_time")
    text = value.split("#", 1)[0]
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise StoreError("anomaly_time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _from_attr(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    if "S" in value:
        return value["S"]
    if "N" in value:
        return Decimal(str(value["N"]))
    if "L" in value:
        return [_from_attr(item) for item in value["L"]]
    return None


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing_env:{name}")
    return value
