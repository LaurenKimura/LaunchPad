"""S3 raw-body cache and DynamoDB writes.

The archive key keeps every new body for 30 days (the bucket lifecycle does
the expiry). The cache key is the last body we successfully normalized. A
later outage does not delete either object.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

NOT_FOUND = {"NoSuchKey", "404", "NotFound"}


class StoreError(Exception):
    """S3 or DynamoDB refused a write we need in order to finish a source."""


@dataclass(frozen=True)
class CacheRecord:
    body: bytes
    etag: str | None
    last_modified: str | None
    fetched_at: str | None
    body_sha256: str


class RawStore:
    def __init__(self, s3_client: Any, bucket: str) -> None:
        self._s3 = s3_client
        self._bucket = bucket

    def load(self, key: str) -> CacheRecord | None:
        try:
            obj = self._s3.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise
        body = obj["Body"].read()
        meta = obj.get("Metadata") or {}
        return CacheRecord(
            body=body,
            etag=meta.get("upstream-etag") or None,
            last_modified=meta.get("upstream-last-modified") or None,
            fetched_at=meta.get("fetched-at") or None,
            body_sha256=meta.get("body-sha256") or hashlib.sha256(body).hexdigest(),
        )

    def save_archive(self, key: str, body: bytes, content_type: str) -> None:
        self._put(key, body, content_type, {})

    def save_cache(
        self,
        key: str,
        body: bytes,
        content_type: str,
        *,
        etag: str | None,
        last_modified: str | None,
        fetched_at: str,
    ) -> None:
        meta = {
            "fetched-at": fetched_at,
            "body-sha256": hashlib.sha256(body).hexdigest(),
        }
        if etag:
            # S3 metadata must be ASCII and must not include some quote styles
            # unescaped. Store the etag as the upstream sent it.
            meta["upstream-etag"] = etag
        if last_modified:
            meta["upstream-last-modified"] = last_modified
        self._put(key, body, content_type, meta)

    def _put(self, key: str, body: bytes, content_type: str, metadata: dict[str, str]) -> None:
        try:
            self._s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                Metadata=metadata,
            )
        except Exception as exc:
            raise StoreError("s3_put_failed") from exc

    @property
    def bucket(self) -> str:
        return self._bucket


class DynamoWriter:
    """Batch PutItem. Callers must already have removed duplicate keys."""

    def __init__(self, client: Any, table_name: str) -> None:
        self._client = client
        self._table_name = table_name

    def put_all(self, items: list[dict[str, Any]]) -> None:
        for chunk in _chunks(items, 25):
            pending = [_attribute_map(item) for item in chunk]
            for _attempt in range(5):
                if not pending:
                    break
                try:
                    response = self._client.batch_write_item(
                        RequestItems={self._table_name: [{"PutRequest": {"Item": item}} for item in pending]}
                    )
                except Exception as exc:
                    raise StoreError("dynamodb_batch_failed") from exc
                unprocessed = (response.get("UnprocessedItems") or {}).get(self._table_name) or []
                pending = [entry["PutRequest"]["Item"] for entry in unprocessed if "PutRequest" in entry]
            if pending:
                raise StoreError("dynamodb_unprocessed_items")


class SatelliteDirectory:
    """Read norad ids off the Satellites table.

    The table's access pattern for operators is get-by-id and list-by-owner.
    This hourly job is the one Scan: it needs every satellite that has a
    catalog number, and there is no key for that list.
    """

    def __init__(self, client: Any, table_name: str) -> None:
        self._client = client
        self._table_name = table_name

    def tracked(self) -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        kwargs: dict[str, Any] = {
            "TableName": self._table_name,
            "ProjectionExpression": "satelliteId, noradId",
        }
        while True:
            try:
                response = self._client.scan(**kwargs)
            except Exception as exc:
                raise StoreError("satellites_scan_failed") from exc
            for item in response.get("Items") or []:
                satellite_id = _attr_text(item.get("satelliteId"))
                norad_id = _norad(item.get("noradId"))
                if satellite_id and norad_id:
                    found.append({"satelliteId": satellite_id, "noradId": norad_id})
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return found
            kwargs["ExclusiveStartKey"] = last_key


def _attribute_map(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for key, value in item.items():
        encoded = _attribute_value(value)
        if encoded is not None:
            mapped[key] = encoded
    return mapped


def _attribute_value(value: Any) -> dict[str, Any] | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        if value == "":
            return None
        return {"S": value}
    if isinstance(value, Decimal):
        return {"N": format(value, "f")}
    if isinstance(value, int):
        return {"N": str(value)}
    if isinstance(value, list):
        encoded = [child for item in value if (child := _attribute_value(item)) is not None]
        return {"L": encoded}
    raise StoreError("unsupported_attribute")


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _is_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = (response.get("Error") or {}).get("Code")
        return code in NOT_FOUND
    return False


def _attr_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    if "S" in value and str(value["S"]).strip():
        return str(value["S"]).strip()
    if "N" in value and str(value["N"]).strip():
        return str(value["N"]).strip()
    return None


def _norad(value: Any) -> str | None:
    text = _attr_text(value)
    if text is None:
        return None
    number = text.split(".", 1)[0]
    if number.isdigit() and 1 <= len(number) <= 9:
        return str(int(number))
    return None
