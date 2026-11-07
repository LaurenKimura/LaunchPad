"""Correlation Lambda: one SEP-covered gap becomes four CauseScores rows."""

import logging
from datetime import datetime, timezone

from correlate import CorrelateDeps, DynamoRecords, handle_event
from scoring import load_weights

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


class Records:
    def __init__(self, anomalies, history=None, weather=None, tle=None):
        self.anomalies = anomalies
        self.history = history or []
        self.weather = weather or []
        self.tle = tle

    def anomalies_for_upload(self, upload_id):
        return [row for row in self.anomalies if row["uploadId"] == upload_id]

    def recent_anomalies(self, satellite_id, limit):
        return [row for row in self.history if row.get("satelliteId") == satellite_id][:limit]

    def weather_between(self, start, end):
        del start, end
        return self.weather

    def tle_before(self, satellite_id, at_iso):
        del satellite_id, at_iso
        return self.tle


class Writer:
    def __init__(self):
        self.items = []

    def put_all(self, items):
        self.items.extend(items)


def anomaly():
    return {
        "uploadId": "upload-1",
        "satelliteId": "iss",
        "anomalyId": "gap-0001",
        "startTime": "2026-03-01T01:00:00Z",
        "endTime": "2026-03-01T01:10:00Z",
        "gapSeconds": 600,
        "startTimeAnomalyId": "2026-03-01T01:00:00Z#gap-0001",
    }


def test_full_sep_overlap_is_saved_with_evidence_and_is_not_logged(caplog):
    records = Records(
        [anomaly()],
        weather=[
            {
                "dataset": "donki_sep",
                "eventId": "2026-SEP-1",
                "eventTime": "2026-03-01T00:00:00Z",
                "observedAt": "2026-03-01T00:00:00Z#2026-SEP-1",
            }
        ],
    )
    stored = Writer()
    bundle = CorrelateDeps(records, stored, load_weights(), lambda: NOW)
    caplog.set_level(logging.INFO)
    result = handle_event(
        {"uploadId": "upload-1", "satelliteId": "iss", "telemetry": "DO-NOT-LOG-TELEMETRY"},
        bundle,
    )
    by_cause = {item["causeId"]: item for item in stored.items}
    weights = load_weights()

    assert result == {"status": "scored", "uploadId": "upload-1", "anomalies": 1, "scores": 4}
    assert by_cause["radiation"]["score"] == weights["radiation"]["sep_full_overlap"]
    assert by_cause["radiation"]["score"] >= 80
    assert "2026-SEP-1" in by_cause["radiation"]["evidence"][0]
    assert by_cause["eclipse_power"]["score"] == 0
    assert by_cause["geomagnetic"]["score"] == 0
    assert by_cause["software_system"]["score"] == 0
    assert by_cause["radiation"]["anomalyIdCauseId"] == "gap-0001#radiation"
    assert by_cause["radiation"]["disclaimer"].startswith("These scores are estimates")
    assert "DO-NOT-LOG-TELEMETRY" not in caplog.text
    assert "2026-SEP-1" not in caplog.text


def test_upload_query_is_consistent_and_history_uses_the_satellite_index():
    class Client:
        def __init__(self):
            self.calls = []

        def query(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("IndexName") == "bySatellite":
                return {"Items": []}
            if kwargs["TableName"] == "Anomalies":
                return {
                    "Items": [
                        {
                            "uploadId": {"S": "upload-1"},
                            "anomalyId": {"S": "gap-0001"},
                            "satelliteId": {"S": "iss"},
                            "startTime": {"S": "2026-03-01T01:00:00Z"},
                            "endTime": {"S": "2026-03-01T01:10:00Z"},
                            "gapSeconds": {"N": "600"},
                        }
                    ]
                }
            return {"Items": []}

    client = Client()
    records = DynamoRecords(client, "Anomalies", "Weather", "Tle")
    rows = records.anomalies_for_upload("upload-1")
    records.recent_anomalies("iss", 50)

    assert rows[0]["anomalyId"] == "gap-0001"
    assert rows[0]["gapSeconds"] == 600
    assert client.calls[0]["ConsistentRead"] is True
    assert client.calls[1]["IndexName"] == "bySatellite"
    assert client.calls[1]["Limit"] == 50
