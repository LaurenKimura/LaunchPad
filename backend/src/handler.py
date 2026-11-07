"""Lambda entry point for the hourly external-data fetch.

EventBridge invokes `handler` with a scheduled event. The event body is not
used. boto3 is imported here so unit tests can run `runner.run` without AWS
libraries installed.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from http_client import HttpClient
from runner import Deps, lookback_from_env, run
from store import DynamoWriter, RawStore, SatelliteDirectory


def handler(event: dict[str, Any] | None, context: object) -> dict[str, Any]:
    del event, context
    return run(deps_from_env())


def deps_from_env() -> Deps:
    import boto3

    bucket = _required("RAW_BUCKET_NAME")
    space_weather_table = _required("SPACE_WEATHER_TABLE_NAME")
    tle_table = _required("TLE_TABLE_NAME")
    satellites_table = _required("SATELLITES_TABLE_NAME")
    secret_arn = _required("NASA_SECRET_ARN")

    s3 = boto3.client("s3")
    dynamodb = boto3.client("dynamodb")
    secrets = boto3.client("secretsmanager")

    def read_secret() -> str:
        response = secrets.get_secret_value(SecretId=secret_arn)
        return str(response.get("SecretString") or "")

    return Deps(
        http=HttpClient(),
        raw=RawStore(s3, bucket),
        space_weather=DynamoWriter(dynamodb, space_weather_table),
        tle=DynamoWriter(dynamodb, tle_table),
        satellites=SatelliteDirectory(dynamodb, satellites_table),
        secret_reader=read_secret,
        now=lambda: datetime.now(timezone.utc),
        lookback_days=lookback_from_env(),
    )


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing_env:{name}")
    return value
