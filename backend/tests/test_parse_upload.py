"""Parser orchestration with mocked S3 and DynamoDB."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from parse_upload import ParserDeps, parse_event

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "telemetry"
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
UPLOAD_ID = "abc123" + "0" * 26
UPLOADED_AT = "2026-03-01T12:00:00Z"
KEY = f"uploads/iss/{UPLOAD_ID}/{UPLOADED_AT}/telemetry.csv"
BUCKET = "uploads-bucket"


class Objects:
    def __init__(self, body):
        self.body = body
        self.reads = []

    def get_bytes(self, bucket, key):
        self.reads.append((bucket, key))
        return self.body


class Uploads:
    def __init__(self, status="pending"):
        self.status = status
        self.rejected = []
        self.parsed = []

    def get_upload(self, satellite_id, sort_key):
        del satellite_id, sort_key
        if self.status is None:
            return None
        return {"status": self.status}

    def mark_rejected(self, satellite_id, sort_key, *, parsed_at, error_code):
        self.rejected.append(error_code)
        self.status = "rejected"

    def mark_parsed(self, satellite_id, sort_key, *, parsed_at, sample_count, gap_count):
        self.parsed.append({"samples": sample_count, "gaps": gap_count, "at": parsed_at})
        self.status = "parsed"


class Anomalies:
    def __init__(self):
        self.items = []

    def put_all(self, items):
        self.items.extend(items)


def deps(body, uploads=None, objects=None):
    return ParserDeps(
        objects=objects or Objects(body),
        uploads=uploads or Uploads(),
        anomalies=Anomalies(),
        now=lambda: NOW,
        bucket=BUCKET,
        max_bytes=5000,
        max_rows=1000,
        multiplier=2,
    )


def event(key=KEY, size=None, bucket=BUCKET):
    obj = {"key": key}
    if size is not None:
        obj["size"] = size
    return {"detail": {"bucket": {"name": bucket}, "object": obj}}


def test_one_gap_sample_is_stored_and_the_note_is_not_logged(caplog):
    body = (SAMPLES / "one-gap.csv").read_bytes()
    parser = deps(body)
    caplog.set_level(logging.INFO)
    result = parse_event(event(size=len(body)), parser)

    assert result["status"] == "parsed"
    assert result["gaps"] == 1
    assert result["samples"] == 7
    assert parser.anomalies.items[0]["startTime"] == "2026-03-01T00:00:30Z"
    assert parser.anomalies.items[0]["endTime"] == "2026-03-01T00:01:30Z"
    assert parser.anomalies.items[0]["uploadId"] == UPLOAD_ID
    assert parser.anomalies.items[0]["startTimeAnomalyId"].endswith("#gap-0001")
    assert parser.uploads.parsed[0]["gaps"] == 1
    assert "DO-NOT-LOG-7f3a" not in caplog.text
    assert "3.30" not in caplog.text


def test_steady_file_writes_no_anomaly_rows():
    body = (SAMPLES / "steady.csv").read_bytes()
    parser = deps(body)
    result = parse_event(event(size=len(body)), parser)
    assert result == {"status": "parsed", "uploadId": UPLOAD_ID, "samples": 5, "gaps": 0}
    assert parser.anomalies.items == []


def test_oversized_event_does_not_download_the_object():
    objects = Objects(b"timestamp\n2026-03-01T00:00:00Z\n")
    parser = deps(b"", uploads=Uploads(), objects=objects)
    parser.max_bytes = 10
    result = parse_event(event(size=9999), parser)
    assert result["error"] == "too_large"
    assert objects.reads == []
    assert parser.uploads.rejected == ["too_large"]


def test_invalid_csv_is_rejected_without_logging_the_cell(caplog):
    body = b"timestamp\nnot-a-time\n"
    parser = deps(body)
    caplog.set_level(logging.INFO)
    result = parse_event(event(size=len(body)), parser)
    assert result["error"] == "invalid_timestamp"
    assert parser.anomalies.items == []
    assert "not-a-time" not in caplog.text


def test_unknown_key_is_ignored_and_not_read():
    objects = Objects(b"timestamp\n2026-03-01T00:00:00Z\n")
    parser = deps(b"", objects=objects)
    result = parse_event(event(key="uploads/other-file.csv", size=10), parser)
    assert result["status"] == "ignored"
    assert objects.reads == []


def test_missing_upload_row_does_not_read_the_object():
    objects = Objects(b"timestamp\n2026-03-01T00:00:00Z\n")
    parser = deps(b"", uploads=Uploads(status=None), objects=objects)
    result = parse_event(event(size=20), parser)
    assert result["error"] == "upload_not_found"
    assert objects.reads == []


def test_encoded_key_is_accepted():
    body = (SAMPLES / "steady.csv").read_bytes()
    encoded = KEY.replace(":", "%3A")
    parser = deps(body)
    result = parse_event(event(key=encoded, size=len(body)), parser)
    assert result["status"] == "parsed"
    assert parser.objects.reads[0][1] == KEY
