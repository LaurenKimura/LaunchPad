"""Presigned POST policy and ownership checks."""

import json
import logging
from datetime import datetime, timezone

from presign import PresignDeps, handle_request, presign_params


NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
OWNER = "owner-sub-1"


class Directory:
    def __init__(self, owner):
        self.owner = owner
        self.pending = []

    def satellite_owner(self, satellite_id):
        del satellite_id
        return self.owner

    def put_pending(self, item):
        self.pending.append(item)


def deps(directory, signed):
    return PresignDeps(
        uploads=directory,
        signer=lambda params: signed.append(params) or {
            "url": "https://uploads.example/SIGNED-URL-SECRET",
            "fields": {"key": params["Key"], "policy": "SIGNED-POLICY"},
        },
        now=lambda: NOW,
        new_id=lambda: "abc123" + "0" * 26,
        max_bytes=1000,
        expires_seconds=900,
        bucket="uploads-bucket",
    )


def event(body, sub=OWNER):
    return {
        "body": json.dumps(body),
        "requestContext": {"authorizer": {"claims": {"sub": sub}}},
    }


def test_policy_pins_key_type_encryption_and_size():
    params = presign_params(
        bucket="uploads-bucket",
        key="uploads/iss/abc/2026-03-01T12:00:00Z/telemetry.csv",
        content_type="text/csv",
        max_bytes=1000,
        expires_seconds=900,
    )
    assert ["content-length-range", 1, 1000] in params["Conditions"]
    assert ["eq", "$key", params["Key"]] in params["Conditions"]
    assert ["eq", "$Content-Type", "text/csv"] in params["Conditions"]
    assert ["eq", "$x-amz-server-side-encryption", "AES256"] in params["Conditions"]
    assert params["Fields"]["x-amz-server-side-encryption"] == "AES256"
    assert params["ExpiresIn"] == 900


def test_owner_receives_a_post_and_the_url_is_not_logged(caplog):
    directory = Directory(OWNER)
    signed = []
    caplog.set_level(logging.INFO)
    response = handle_request(
        event({"satelliteId": "iss", "contentType": "text/csv"}),
        deps(directory, signed),
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["method"] == "POST"
    assert body["maxBytes"] == 1000
    assert body["key"].endswith("/telemetry.csv")
    assert directory.pending[0]["status"] == "pending"
    assert directory.pending[0]["s3Key"] == body["key"]
    assert signed[0]["Key"] == body["key"]
    assert "SIGNED-URL-SECRET" not in caplog.text
    assert "SIGNED-POLICY" not in caplog.text


def test_other_owner_is_not_found_and_nothing_is_signed():
    signed = []
    response = handle_request(
        event({"satelliteId": "iss", "contentType": "application/json"}, sub="someone-else"),
        deps(Directory(OWNER), signed),
    )
    assert response["statusCode"] == 404
    assert json.loads(response["body"]) == {"error": "satellite_not_found"}
    assert signed == []


def test_missing_satellite_is_not_found():
    response = handle_request(
        event({"satelliteId": "iss", "contentType": "text/csv"}),
        deps(Directory(None), []),
    )
    assert response["statusCode"] == 404


def test_unsupported_content_type_is_rejected():
    response = handle_request(
        event({"satelliteId": "iss", "contentType": "text/plain"}),
        deps(Directory(OWNER), []),
    )
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "invalid_content_type"


def test_missing_caller_is_unauthorized():
    response = handle_request({"body": '{"satelliteId":"iss","contentType":"text/csv"}'}, deps(Directory(OWNER), []))
    assert response["statusCode"] == 401
