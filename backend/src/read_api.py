"""Operator read API.

GET /satellites lists the caller's satellites.
GET /anomalies lists recent gaps for those satellites.
GET /anomalies/{anomalyId} returns one gap and its cause scores.

A missing row and a row owned by someone else both return 404.
The response is an allow-list of ids, times, scores, and evidence.
Telemetry samples are not stored on these rows and are not logged.
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from typing import Any

from scoring import CAUSE_IDS, DISCLAIMER
from store import StoreError
from upload_keys import SATELLITE_ID

logger = logging.getLogger("launchpad.read")

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MAX_SATELLITES = 50
ANOMALY_ID = SATELLITE_ID


def handler(event: dict[str, Any] | None, context: object) -> dict[str, Any]:
    del context
    return handle_request(event or {}, deps_from_env())


def handle_request(event: dict[str, Any], records: Any) -> dict[str, Any]:
    owner = _caller_sub(event)
    if not owner:
        return _response(401, {"error": "unauthorized"})
    method = event.get("httpMethod")
    resource = event.get("resource") or ""
    if method != "GET":
        return _response(404, {"error": "not_found"})
    try:
        if resource == "/satellites":
            body = list_satellites(records, owner)
        elif resource == "/anomalies":
            body = list_anomalies(records, owner, event.get("queryStringParameters") or {})
        elif resource == "/anomalies/{anomalyId}":
            anomaly_id = (event.get("pathParameters") or {}).get("anomalyId")
            body = get_anomaly(records, owner, anomaly_id)
        else:
            return _response(404, {"error": "not_found"})
    except StoreError:
        logger.warning("read_failed error=store_unavailable")
        return _response(503, {"error": "store_unavailable"})
    except ReadError as exc:
        logger.info("read_rejected error=%s", exc.code)
        return _response(exc.status, {"error": exc.code})
    logger.info("read_ok resource=%s", resource)
    return _response(200, body)


class ReadError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


def list_satellites(records: Any, owner: str) -> dict[str, Any]:
    rows = records.satellites_for_owner(owner)[:MAX_SATELLITES]
    return {"satellites": [_public_satellite(row) for row in rows]}


def list_anomalies(records: Any, owner: str, query: dict[str, Any]) -> dict[str, Any]:
    limit = _limit(query.get("limit") if isinstance(query, dict) else None)
    satellite_id = query.get("satelliteId") if isinstance(query, dict) else None
    if satellite_id:
        if not isinstance(satellite_id, str) or SATELLITE_ID.fullmatch(satellite_id) is None:
            raise ReadError(400, "invalid_satellite")
        if not _owns(records, owner, satellite_id):
            raise ReadError(404, "not_found")
        satellite_ids = [satellite_id]
    else:
        satellite_ids = [
            str(row["satelliteId"])
            for row in records.satellites_for_owner(owner)[:MAX_SATELLITES]
            if row.get("satelliteId")
        ]
    found: list[dict[str, Any]] = []
    for satellite in satellite_ids:
        found.extend(records.anomalies_for_satellite(satellite, limit))
    found.sort(key=lambda row: str(row.get("startTime") or ""), reverse=True)
    return {"anomalies": [_public_anomaly(row) for row in found[:limit]]}


def get_anomaly(records: Any, owner: str, anomaly_id: Any) -> dict[str, Any]:
    if not isinstance(anomaly_id, str) or ANOMALY_ID.fullmatch(anomaly_id) is None:
        raise ReadError(400, "invalid_anomaly")
    row = records.anomaly(anomaly_id)
    if row is None:
        raise ReadError(404, "not_found")
    satellite_id = row.get("satelliteId")
    if not isinstance(satellite_id, str) or not _owns(records, owner, satellite_id):
        raise ReadError(404, "not_found")
    scores = [_public_score(item) for item in records.scores_for_anomaly(anomaly_id)]
    scores.sort(key=lambda item: _cause_order(item["causeId"]))
    return {
        "anomaly": _public_anomaly(row),
        "scores": scores,
        "disclaimer": DISCLAIMER,
    }


class DynamoRecords:
    def __init__(self, client: Any, satellites: str, anomalies: str, scores: str) -> None:
        self._client = client
        self._satellites = satellites
        self._anomalies = anomalies
        self._scores = scores

    def satellites_for_owner(self, owner: str) -> list[dict[str, Any]]:
        items = _query(
            self._client,
            {
                "TableName": self._satellites,
                "IndexName": "byOwner",
                "KeyConditionExpression": "ownerSub = :owner",
                "ExpressionAttributeValues": {":owner": {"S": owner}},
            },
        )
        return [_decode(item) for item in items]

    def satellite(self, satellite_id: str) -> dict[str, Any] | None:
        try:
            response = self._client.get_item(
                TableName=self._satellites,
                Key={"satelliteId": {"S": satellite_id}},
                ConsistentRead=True,
            )
        except Exception as exc:
            raise StoreError("dynamodb_get_failed") from exc
        item = response.get("Item")
        if not item:
            return None
        return _decode(item)

    def anomalies_for_satellite(self, satellite_id: str, limit: int) -> list[dict[str, Any]]:
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
        return [_decode(item) for item in items]

    def anomaly(self, anomaly_id: str) -> dict[str, Any] | None:
        items = _query(
            self._client,
            {
                "TableName": self._anomalies,
                "IndexName": "byAnomalyId",
                "KeyConditionExpression": "anomalyId = :anomaly",
                "ExpressionAttributeValues": {":anomaly": {"S": anomaly_id}},
                "Limit": 1,
            },
        )
        if not items:
            return None
        return _decode(items[0])

    def scores_for_anomaly(self, anomaly_id: str) -> list[dict[str, Any]]:
        items = _query(
            self._client,
            {
                "TableName": self._scores,
                "KeyConditionExpression": "anomalyId = :anomaly",
                "ExpressionAttributeValues": {":anomaly": {"S": anomaly_id}},
            },
        )
        return [_decode(item) for item in items]


def deps_from_env() -> DynamoRecords:
    import boto3

    return DynamoRecords(
        boto3.client("dynamodb"),
        _required("SATELLITES_TABLE_NAME"),
        _required("ANOMALIES_TABLE_NAME"),
        _required("CAUSE_SCORES_TABLE_NAME"),
    )


def _owns(records: Any, owner: str, satellite_id: str) -> bool:
    row = records.satellite(satellite_id)
    return isinstance(row, dict) and row.get("ownerSub") == owner


def _public_satellite(row: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {"satelliteId": row.get("satelliteId") or ""}
    if row.get("name"):
        item["name"] = row["name"]
    if row.get("noradId") is not None and row.get("noradId") != "":
        item["noradId"] = _number(row["noradId"]) if not isinstance(row["noradId"], str) else str(row["noradId"])
    return item


def _public_anomaly(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "anomalyId": row.get("anomalyId") or "",
        "satelliteId": row.get("satelliteId") or "",
        "uploadId": row.get("uploadId") or "",
        "startTime": row.get("startTime") or "",
        "endTime": row.get("endTime") or "",
        "gapSeconds": _number(row.get("gapSeconds")),
    }


def _public_score(row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), list) else []
    return {
        "causeId": row.get("causeId") or "",
        "score": int(_number(row.get("score"))),
        "evidence": [str(line) for line in evidence],
    }


def _cause_order(cause_id: str) -> tuple[int, str]:
    try:
        return (CAUSE_IDS.index(cause_id), cause_id)
    except ValueError:
        return (len(CAUSE_IDS), cause_id)


def _limit(value: Any) -> int:
    if value is None or value == "":
        return DEFAULT_LIMIT
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ReadError(400, "invalid_limit") from exc
    if parsed < 1:
        raise ReadError(400, "invalid_limit")
    return min(parsed, MAX_LIMIT)


def _number(value: Any) -> int | float:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    try:
        number = Decimal(str(value))
    except Exception:
        return 0
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _query(client: Any, kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    while len(found) < 200:
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


def _decode(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _decode_attr(value) for key, value in item.items()}


def _decode_attr(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    if "S" in value:
        return value["S"]
    if "N" in value:
        return Decimal(str(value["N"]))
    if "L" in value:
        return [_decode_attr(item) for item in value["L"]]
    return None


def _caller_sub(event: dict[str, Any]) -> str | None:
    claims = ((event.get("requestContext") or {}).get("authorizer") or {}).get("claims") or {}
    sub = claims.get("sub")
    if isinstance(sub, str) and sub.strip():
        return sub.strip()
    return None


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body),
    }


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing_env:{name}")
    return value
