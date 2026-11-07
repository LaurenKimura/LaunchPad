"""Issue a presigned POST for one telemetry file.

S3 enforces the size limit with a content-length-range condition. The Lambda
writes the pending upload row before it signs, so the parser can find the
row when the object arrives. The signed URL is not logged.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from parse_config import max_upload_bytes, presign_expires_seconds
from upload_keys import SATELLITE_ID, object_key, sort_key
from upload_store import StoreError, UploadDirectory

logger = logging.getLogger("launchpad.upload")

CONTENT_TYPES = {"text/csv": "telemetry.csv", "application/json": "telemetry.json"}
Signer = Callable[[dict[str, Any]], dict[str, Any]]


class UploadError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


@dataclass
class PresignDeps:
    uploads: UploadDirectory
    signer: Signer
    now: Callable[[], datetime]
    new_id: Callable[[], str]
    max_bytes: int
    expires_seconds: int
    bucket: str


def handler(event: dict[str, Any] | None, context: object) -> dict[str, Any]:
    del context
    return handle_request(event or {}, deps_from_env())


def handle_request(event: dict[str, Any], deps: PresignDeps) -> dict[str, Any]:
    owner = _caller_sub(event)
    if not owner:
        return _response(401, {"error": "unauthorized"})
    body, error = _body(event)
    if error:
        return _response(400, {"error": error})
    try:
        result = issue_upload(deps, owner, body)
    except UploadError as exc:
        logger.warning("upload_url_denied error=%s", exc.code)
        return _response(exc.status, {"error": exc.code})
    except StoreError:
        logger.warning("upload_url_failed error=store_unavailable")
        return _response(503, {"error": "store_unavailable"})
    logger.info(
        "upload_url_issued uploadId=%s satelliteId=%s",
        result["uploadId"],
        result["satelliteId"],
    )
    return _response(200, result)


def issue_upload(deps: PresignDeps, owner_sub: str, body: dict[str, Any]) -> dict[str, Any]:
    satellite_id = body.get("satelliteId")
    if not isinstance(satellite_id, str) or SATELLITE_ID.fullmatch(satellite_id) is None:
        raise UploadError(400, "invalid_satellite")
    content_type = _content_type(body.get("contentType"))
    if content_type is None:
        raise UploadError(400, "invalid_content_type")
    owner = deps.uploads.satellite_owner(satellite_id)
    # The same response for a missing satellite and a satellite owned by
    # someone else, so callers cannot probe ids.
    if owner is None or owner != owner_sub:
        raise UploadError(404, "satellite_not_found")

    uploaded_at = deps.now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    upload_id = deps.new_id()
    key = object_key(satellite_id, upload_id, uploaded_at, content_type)
    deps.uploads.put_pending(
        {
            "satelliteId": satellite_id,
            "uploadedAtUploadId": sort_key(uploaded_at, upload_id),
            "uploadId": upload_id,
            "ownerSub": owner_sub,
            "contentType": content_type,
            "s3Key": key,
            "status": "pending",
            "maxBytes": deps.max_bytes,
            "createdAt": uploaded_at,
        }
    )
    signed = deps.signer(
        presign_params(
            bucket=deps.bucket,
            key=key,
            content_type=content_type,
            max_bytes=deps.max_bytes,
            expires_seconds=deps.expires_seconds,
        )
    )
    return {
        "uploadId": upload_id,
        "satelliteId": satellite_id,
        "method": "POST",
        "url": signed["url"],
        "fields": signed["fields"],
        "key": key,
        "maxBytes": deps.max_bytes,
        "expiresInSeconds": deps.expires_seconds,
    }


def presign_params(
    *,
    bucket: str,
    key: str,
    content_type: str,
    max_bytes: int,
    expires_seconds: int,
) -> dict[str, Any]:
    """Arguments for S3 generate_presigned_post. The policy pins the key, type, and size."""

    fields = {
        "Content-Type": content_type,
        "x-amz-server-side-encryption": "AES256",
        "success_action_status": "204",
    }
    return {
        "Bucket": bucket,
        "Key": key,
        "Fields": fields,
        "Conditions": [
            {"bucket": bucket},
            ["eq", "$key", key],
            ["eq", "$Content-Type", content_type],
            ["content-length-range", 1, max_bytes],
            ["eq", "$x-amz-server-side-encryption", "AES256"],
            ["eq", "$success_action_status", "204"],
        ],
        "ExpiresIn": expires_seconds,
    }


def deps_from_env() -> PresignDeps:
    import boto3

    bucket = _required("UPLOADS_BUCKET_NAME")
    uploads_table = _required("UPLOADS_TABLE_NAME")
    satellites_table = _required("SATELLITES_TABLE_NAME")
    s3 = boto3.client("s3")
    dynamodb = boto3.client("dynamodb")

    def sign(params: dict[str, Any]) -> dict[str, Any]:
        signed = s3.generate_presigned_post(
            Bucket=params["Bucket"],
            Key=params["Key"],
            Fields=params["Fields"],
            Conditions=params["Conditions"],
            ExpiresIn=params["ExpiresIn"],
        )
        return {"url": signed["url"], "fields": signed["fields"]}

    return PresignDeps(
        uploads=UploadDirectory(dynamodb, uploads_table, satellites_table),
        signer=sign,
        now=lambda: datetime.now(timezone.utc),
        new_id=lambda: uuid.uuid4().hex,
        max_bytes=max_upload_bytes(),
        expires_seconds=presign_expires_seconds(),
        bucket=bucket,
    )


def _caller_sub(event: dict[str, Any]) -> str | None:
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    claims = authorizer.get("claims") or {}
    sub = claims.get("sub")
    if isinstance(sub, str) and sub.strip():
        return sub.strip()
    return None


def _body(event: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    raw = event.get("body") or ""
    if not isinstance(raw, str):
        return {}, "invalid_request"
    if event.get("isBase64Encoded"):
        import base64

        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (UnicodeError, ValueError):
            return {}, "invalid_request"
    if len(raw) > 4096:
        return {}, "invalid_request"
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}, "invalid_request"
    if not isinstance(payload, dict):
        return {}, "invalid_request"
    return payload, None


def _content_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    base = value.split(";", 1)[0].strip().lower()
    if base in CONTENT_TYPES:
        return base
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
