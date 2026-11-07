"""Object keys for telemetry uploads.

The key is assigned by the presign Lambda. The original filename is not used,
so a client cannot put `../` or a second object under the same prefix.

    uploads/{satelliteId}/{uploadId}/{uploadedAt}/telemetry.csv
"""

from __future__ import annotations

import re

SATELLITE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")
UPLOADED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
FILENAMES = {"text/csv": "telemetry.csv", "application/json": "telemetry.json"}


def object_key(satellite_id: str, upload_id: str, uploaded_at: str, content_type: str) -> str:
    filename = FILENAMES[content_type]
    return f"uploads/{satellite_id}/{upload_id}/{uploaded_at}/{filename}"


def sort_key(uploaded_at: str, upload_id: str) -> str:
    """Uploads table sort key: `{ISO-8601}#{uploadId}`."""

    return f"{uploaded_at}#{upload_id}"


def parse_object_key(key: str) -> tuple[str, str, str, str] | None:
    parts = key.split("/")
    if len(parts) != 5 or parts[0] != "uploads":
        return None
    _, satellite_id, upload_id, uploaded_at, filename = parts
    if filename not in FILENAMES.values():
        return None
    if SATELLITE_ID.fullmatch(satellite_id) is None:
        return None
    if UPLOAD_ID.fullmatch(upload_id) is None:
        return None
    if UPLOADED_AT.fullmatch(uploaded_at) is None:
        return None
    return satellite_id, upload_id, uploaded_at, filename
