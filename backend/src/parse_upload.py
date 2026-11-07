"""Parse a telemetry object after S3 creates it.

EventBridge delivers the Object Created event. Permanent problems (bad CSV,
file too large) are saved on the upload row and are not raised, so the event
is not retried. A DynamoDB or S3 outage is raised so EventBridge can retry.
Raw file bytes are never logged.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import unquote_plus

from gaps import anomaly_items, find_gaps, iso_utc
from parse_config import gap_multiplier, max_upload_bytes, max_upload_rows
from store import DynamoWriter
from telemetry import TelemetryError, parse_telemetry
from upload_keys import parse_object_key, sort_key
from upload_store import ObjectReader, StoreError, UploadDirectory, UploadMissing

logger = logging.getLogger("launchpad.upload")


@dataclass
class ParserDeps:
    objects: ObjectReader
    uploads: UploadDirectory
    anomalies: DynamoWriter
    now: Callable[[], datetime]
    bucket: str
    max_bytes: int
    max_rows: int
    multiplier: float
    request_correlation: Callable[[str, str], None] | None = None


def handler(event: dict[str, Any] | None, context: object) -> dict[str, Any]:
    del context
    return parse_event(event or {}, deps_from_env())


def parse_event(event: dict[str, Any], deps: ParserDeps) -> dict[str, Any]:
    located = _locate(event)
    if located is None:
        return {"status": "ignored", "error": "invalid_event"}
    bucket, key, size, satellite_id, upload_id, uploaded_at, filename = located
    if bucket != deps.bucket:
        logger.info("upload_ignored error=unexpected_bucket")
        return {"status": "ignored", "error": "unexpected_bucket"}
    table_key = sort_key(uploaded_at, upload_id)
    record = deps.uploads.get_upload(satellite_id, table_key)
    if record is None:
        logger.warning("upload_missing uploadId=%s", upload_id)
        return {"status": "rejected", "error": "upload_not_found", "uploadId": upload_id}
    if record.get("status") in {"parsed", "rejected"}:
        logger.info("upload_duplicate uploadId=%s status=%s", upload_id, record.get("status"))
        return {"status": record.get("status"), "duplicate": True, "uploadId": upload_id}
    if size is not None and size > deps.max_bytes:
        return _reject(deps, satellite_id, table_key, upload_id, "too_large")

    body = deps.objects.get_bytes(bucket, key)
    if len(body) > deps.max_bytes:
        return _reject(deps, satellite_id, table_key, upload_id, "too_large")
    try:
        timestamps = parse_telemetry(body, filename, max_rows=deps.max_rows)
    except TelemetryError as exc:
        return _reject(deps, satellite_id, table_key, upload_id, exc.code)

    _median, windows = find_gaps(timestamps, multiplier=deps.multiplier)
    parsed_at = iso_utc(deps.now())
    items = anomaly_items(
        upload_id=upload_id,
        satellite_id=satellite_id,
        windows=windows,
        parsed_at=parsed_at,
    )
    if items:
        deps.anomalies.put_all(items)
        if deps.request_correlation is not None:
            deps.request_correlation(upload_id, satellite_id)
    try:
        deps.uploads.mark_parsed(
            satellite_id,
            table_key,
            parsed_at=parsed_at,
            sample_count=len(timestamps),
            gap_count=len(windows),
        )
    except UploadMissing:
        logger.warning("upload_missing uploadId=%s", upload_id)
        return {"status": "rejected", "error": "upload_not_found", "uploadId": upload_id}
    logger.info(
        "upload_parsed uploadId=%s satelliteId=%s samples=%s gaps=%s",
        upload_id,
        satellite_id,
        len(timestamps),
        len(windows),
    )
    return {
        "status": "parsed",
        "uploadId": upload_id,
        "samples": len(timestamps),
        "gaps": len(windows),
    }


def deps_from_env() -> ParserDeps:
    import boto3

    s3 = boto3.client("s3")
    dynamodb = boto3.client("dynamodb")
    function_name = os.environ.get("CORRELATE_FUNCTION_NAME", "").strip()
    request = None
    if function_name:
        functions = boto3.client("lambda")

        def request(upload_id: str, satellite_id: str) -> None:
            functions.invoke(
                FunctionName=function_name,
                InvocationType="Event",
                Payload=json.dumps(correlation_payload(upload_id, satellite_id)).encode(),
            )

    return ParserDeps(
        objects=ObjectReader(s3),
        uploads=UploadDirectory(dynamodb, _required("UPLOADS_TABLE_NAME")),
        anomalies=DynamoWriter(dynamodb, _required("ANOMALIES_TABLE_NAME")),
        now=lambda: datetime.now(timezone.utc),
        bucket=_required("UPLOADS_BUCKET_NAME"),
        max_bytes=max_upload_bytes(),
        max_rows=max_upload_rows(),
        multiplier=gap_multiplier(),
        request_correlation=request,
    )


def correlation_payload(upload_id: str, satellite_id: str) -> dict[str, str]:
    """Ids only. The correlation function reads the gap from DynamoDB."""

    return {"uploadId": upload_id, "satelliteId": satellite_id}


def _locate(
    event: dict[str, Any],
) -> tuple[str, str, int | None, str, str, str, str] | None:
    detail = event.get("detail") or {}
    bucket = (detail.get("bucket") or {}).get("name")
    obj = detail.get("object") or {}
    raw_key = obj.get("key")
    if not isinstance(bucket, str) or not isinstance(raw_key, str):
        return None
    key = unquote_plus(raw_key)
    parsed = parse_object_key(key)
    if parsed is None:
        logger.info("upload_ignored error=invalid_key")
        return None
    satellite_id, upload_id, uploaded_at, filename = parsed
    size = obj.get("size")
    if not isinstance(size, int):
        size = None
    return bucket, key, size, satellite_id, upload_id, uploaded_at, filename


def _reject(
    deps: ParserDeps,
    satellite_id: str,
    table_key: str,
    upload_id: str,
    code: str,
) -> dict[str, Any]:
    try:
        deps.uploads.mark_rejected(
            satellite_id,
            table_key,
            parsed_at=iso_utc(deps.now()),
            error_code=code,
        )
    except UploadMissing:
        logger.warning("upload_missing uploadId=%s", upload_id)
        return {"status": "rejected", "error": "upload_not_found", "uploadId": upload_id}
    logger.warning("upload_rejected uploadId=%s error=%s", upload_id, code)
    return {"status": "rejected", "error": code, "uploadId": upload_id}


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing_env:{name}")
    return value
