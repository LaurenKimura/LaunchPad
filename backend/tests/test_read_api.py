"""Operator read API. Other owners and missing rows both look like not_found."""

import json
import logging

from read_api import DynamoRecords, handle_request

OWNER = "owner-1"


class Records:
    def __init__(self):
        self.satellites = {
            "iss": {"satelliteId": "iss", "name": "ISS", "noradId": "25544", "ownerSub": OWNER},
            "other": {"satelliteId": "other", "name": "Other", "noradId": "1", "ownerSub": "someone-else"},
        }
        self.anomalies = [
            {
                "anomalyId": "gap-0002",
                "satelliteId": "iss",
                "uploadId": "upload-1",
                "startTime": "2026-03-01T02:00:00Z",
                "endTime": "2026-03-01T02:01:00Z",
                "gapSeconds": 60,
            },
            {
                "anomalyId": "gap-0001",
                "satelliteId": "iss",
                "uploadId": "upload-1",
                "startTime": "2026-03-01T01:00:00Z",
                "endTime": "2026-03-01T01:10:00Z",
                "gapSeconds": 600,
            },
        ]
        self.scores = {
            "gap-0002": [
                {"causeId": "software_system", "score": 0, "evidence": ["No repeating pattern."]},
                {"causeId": "radiation", "score": 85, "evidence": ["SEP 2026-SEP-1 covers the entire gap."]},
                {"causeId": "eclipse_power", "score": 0, "evidence": ["No TLE was available."]},
                {"causeId": "geomagnetic", "score": 10, "evidence": ["Highest Kp overlapping this gap was 1.3."]},
            ]
        }
        self.anomaly_reads = []

    def satellites_for_owner(self, owner):
        return [row for row in self.satellites.values() if row["ownerSub"] == owner]

    def satellite(self, satellite_id):
        return self.satellites.get(satellite_id)

    def anomalies_for_satellite(self, satellite_id, limit):
        self.anomaly_reads.append(satellite_id)
        return [row for row in self.anomalies if row["satelliteId"] == satellite_id][:limit]

    def anomaly(self, anomaly_id):
        for row in self.anomalies:
            if row["anomalyId"] == anomaly_id:
                return row
        return None

    def scores_for_anomaly(self, anomaly_id):
        return self.scores.get(anomaly_id, [])


def event(resource, owner=OWNER, query=None, anomaly_id=None):
    payload = {
        "httpMethod": "GET",
        "resource": resource,
        "requestContext": {"authorizer": {"claims": {"sub": owner}}},
        "queryStringParameters": query,
        "pathParameters": {"anomalyId": anomaly_id} if anomaly_id else None,
    }
    return payload


def body(response):
    return json.loads(response["body"])


def test_lists_only_the_callers_satellites():
    response = handle_request(event("/satellites"), Records())
    assert response["statusCode"] == 200
    assert body(response) == {"satellites": [{"satelliteId": "iss", "name": "ISS", "noradId": "25544"}]}


def test_lists_recent_anomalies_newest_first():
    response = handle_request(event("/anomalies", query={"limit": "10"}), Records())
    anomalies = body(response)["anomalies"]
    assert [row["anomalyId"] for row in anomalies] == ["gap-0002", "gap-0001"]
    assert "ownerSub" not in anomalies[0]


def test_other_owners_satellite_is_not_found_and_is_not_queried():
    records = Records()
    response = handle_request(event("/anomalies", query={"satelliteId": "other"}), records)
    assert response["statusCode"] == 404
    assert records.anomaly_reads == []


def test_one_anomaly_includes_scores_in_cause_order_and_the_disclaimer():
    response = handle_request(event("/anomalies/{anomalyId}", anomaly_id="gap-0002"), Records())
    payload = body(response)
    assert response["statusCode"] == 200
    assert [score["causeId"] for score in payload["scores"]] == [
        "radiation",
        "eclipse_power",
        "geomagnetic",
        "software_system",
    ]
    assert payload["scores"][0]["score"] == 85
    assert "SEP 2026-SEP-1" in payload["scores"][0]["evidence"][0]
    assert payload["disclaimer"].startswith("These scores are estimates")
    assert payload["anomaly"]["gapSeconds"] == 60


def test_another_owners_anomaly_is_not_found(caplog):
    records = Records()
    records.anomalies.append(
        {
            "anomalyId": "gap-0099",
            "satelliteId": "other",
            "uploadId": "upload-9",
            "startTime": "2026-03-01T03:00:00Z",
            "endTime": "2026-03-01T03:01:00Z",
            "gapSeconds": 60,
        }
    )
    caplog.set_level(logging.INFO)
    response = handle_request(event("/anomalies/{anomalyId}", anomaly_id="gap-0099"), records)
    assert response["statusCode"] == 404
    assert "SEP 2026-SEP-1" not in caplog.text


def test_missing_caller_is_unauthorized():
    response = handle_request({"httpMethod": "GET", "resource": "/satellites"}, Records())
    assert response["statusCode"] == 401


def test_query_uses_owner_and_anomaly_indexes():
    class Client:
        def __init__(self):
            self.calls = []

        def query(self, **kwargs):
            self.calls.append(kwargs)
            return {"Items": []}

        def get_item(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "Item": {
                    "satelliteId": {"S": "iss"},
                    "ownerSub": {"S": OWNER},
                    "name": {"S": "ISS"},
                }
            }

    client = Client()
    records = DynamoRecords(client, "Satellites", "Anomalies", "CauseScores")
    assert records.satellites_for_owner(OWNER) == []
    assert records.anomaly("gap-0001") is None
    assert client.calls[0]["IndexName"] == "byOwner"
    assert client.calls[1]["IndexName"] == "byAnomalyId"
    owned = records.satellite("iss")
    assert owned["ownerSub"] == OWNER
    assert client.calls[2]["ConsistentRead"] is True
