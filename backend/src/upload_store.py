"""DynamoDB reads and writes for the upload flow.

Item attributes are encoded here so the handlers can be tested without boto3.
A missing upload is not an error to retry. A service failure is.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


class UploadMissing(Exception):
    """The pending upload row is not in the table."""


class StoreError(Exception):
    """DynamoDB or S3 failed in a way the caller should retry."""


class ObjectReader:
    def __init__(self, s3_client: Any) -> None:
        self._s3 = s3_client

    def get_bytes(self, bucket: str, key: str) -> bytes:
        try:
            obj = self._s3.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read()
        except Exception as exc:
            raise StoreError("s3_get_failed") from exc


class UploadDirectory:
    def __init__(self, client: Any, uploads_table: str, satellites_table: str = "") -> None:
        self._client = client
        self._uploads = uploads_table
        self._satellites = satellites_table

    def satellite_owner(self, satellite_id: str) -> str | None:
        item = self._get(self._satellites, {"satelliteId": {"S": satellite_id}})
        if item is None:
            return None
        owner = item.get("ownerSub")
        if isinstance(owner, dict) and owner.get("S"):
            return str(owner["S"])
        return None

    def put_pending(self, item: dict[str, Any]) -> None:
        try:
            self._client.put_item(TableName=self._uploads, Item=_encode(item))
        except Exception as exc:
            raise StoreError("upload_put_failed") from exc

    def get_upload(self, satellite_id: str, sort_key: str) -> dict[str, str] | None:
        item = self._get(
            self._uploads,
            {"satelliteId": {"S": satellite_id}, "uploadedAtUploadId": {"S": sort_key}},
        )
        if item is None:
            return None
        status = item.get("status")
        if not isinstance(status, dict) or "S" not in status:
            return {"status": ""}
        return {"status": str(status["S"])}

    def mark_parsed(
        self,
        satellite_id: str,
        sort_key: str,
        *,
        parsed_at: str,
        sample_count: int,
        gap_count: int,
    ) -> None:
        self._update(
            satellite_id,
            sort_key,
            (
                "SET #status = :status, parsedAt = :parsedAt, "
                "sampleCount = :sampleCount, gapCount = :gapCount REMOVE errorCode"
            ),
            {
                ":status": {"S": "parsed"},
                ":parsedAt": {"S": parsed_at},
                ":sampleCount": {"N": str(sample_count)},
                ":gapCount": {"N": str(gap_count)},
            },
        )

    def mark_rejected(self, satellite_id: str, sort_key: str, *, parsed_at: str, error_code: str) -> None:
        self._update(
            satellite_id,
            sort_key,
            "SET #status = :status, parsedAt = :parsedAt, errorCode = :errorCode",
            {
                ":status": {"S": "rejected"},
                ":parsedAt": {"S": parsed_at},
                ":errorCode": {"S": error_code},
            },
        )

    def _get(self, table: str, key: dict[str, Any]) -> dict[str, Any] | None:
        try:
            response = self._client.get_item(TableName=table, Key=key, ConsistentRead=True)
        except Exception as exc:
            raise StoreError("dynamodb_get_failed") from exc
        return response.get("Item")

    def _update(
        self,
        satellite_id: str,
        sort_key: str,
        expression: str,
        values: dict[str, Any],
    ) -> None:
        try:
            self._client.update_item(
                TableName=self._uploads,
                Key={
                    "satelliteId": {"S": satellite_id},
                    "uploadedAtUploadId": {"S": sort_key},
                },
                ConditionExpression="attribute_exists(satelliteId)",
                UpdateExpression=expression,
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=values,
            )
        except Exception as exc:
            if _condition_failed(exc):
                raise UploadMissing() from exc
            raise StoreError("upload_update_failed") from exc


def _encode(item: dict[str, Any]) -> dict[str, dict[str, str]]:
    encoded: dict[str, dict[str, str]] = {}
    for key, value in item.items():
        if value is None or value == "":
            continue
        if isinstance(value, str):
            encoded[key] = {"S": value}
        elif isinstance(value, Decimal):
            encoded[key] = {"N": format(value, "f")}
        elif isinstance(value, int) and not isinstance(value, bool):
            encoded[key] = {"N": str(value)}
        else:
            raise StoreError("unsupported_attribute")
    return encoded


def _condition_failed(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return (response.get("Error") or {}).get("Code") == "ConditionalCheckFailedException"
    return False
