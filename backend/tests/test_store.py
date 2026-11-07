"""S3 cache metadata and DynamoDB batch writes, with in-memory clients."""

import io
from decimal import Decimal

import pytest

from store import DynamoWriter, RawStore, SatelliteDirectory, StoreError


class Missing(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3:
    def __init__(self):
        self.objects = {}

    def get_object(self, Bucket, Key):
        del Bucket
        if Key not in self.objects:
            raise Missing()
        body, metadata = self.objects[Key]
        return {"Body": io.BytesIO(body), "Metadata": metadata}

    def put_object(self, Bucket, Key, Body, ContentType, Metadata):
        del Bucket, ContentType
        self.objects[Key] = (Body, Metadata)


class FakeDynamo:
    def __init__(self):
        self.written = []
        self.calls = 0
        self.hold_back = True

    def batch_write_item(self, RequestItems):
        self.calls += 1
        table, requests = next(iter(RequestItems.items()))
        if self.hold_back:
            self.hold_back = False
            self.written.extend(requests[1:])
            return {"UnprocessedItems": {table: requests[:1]}}
        self.written.extend(requests)
        return {"UnprocessedItems": {}}


def test_cache_round_trip_keeps_validators_and_hash():
    s3 = FakeS3()
    store = RawStore(s3, "bucket")
    store.save_cache(
        "cache/noaa/kp.json",
        b"{}",
        "application/json",
        etag='"abc"',
        last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
        fetched_at="2026-11-07T12:00:00Z",
    )

    loaded = store.load("cache/noaa/kp.json")

    assert loaded is not None
    assert loaded.body == b"{}"
    assert loaded.etag == '"abc"'
    assert loaded.last_modified == "Mon, 01 Jan 2024 00:00:00 GMT"
    assert loaded.body_sha256
    assert store.load("cache/missing.json") is None


def test_batch_write_retries_unprocessed_items_and_encodes_decimals():
    dynamo = FakeDynamo()
    writer = DynamoWriter(dynamo, "SpaceWeather")
    items = [
        {"dataset": "noaa_kp", "observedAt": "2026-10-31T00:00:00Z", "kp": Decimal("3.00")},
        {"dataset": "noaa_kp", "observedAt": "2026-10-31T03:00:00Z", "kp": Decimal("6")},
    ]

    writer.put_all(items)

    assert dynamo.calls == 2
    stored = [entry["PutRequest"]["Item"] for entry in dynamo.written]
    assert {"S": "noaa_kp"} in [item["dataset"] for item in stored]
    assert {"N": "3.00"} in [item["kp"] for item in stored]


def test_unprocessed_items_that_never_clear_raise():
    class Stuck(FakeDynamo):
        def batch_write_item(self, RequestItems):
            self.calls += 1
            table, requests = next(iter(RequestItems.items()))
            return {"UnprocessedItems": {table: requests}}

    with pytest.raises(StoreError, match="dynamodb_unprocessed_items"):
        DynamoWriter(Stuck(), "SpaceWeather").put_all([{"dataset": "noaa_kp", "observedAt": "t"}])


def test_satellite_scan_keeps_rows_that_have_a_catalog_number():
    pages = [
        {
            "Items": [
                {"satelliteId": {"S": "iss"}, "noradId": {"S": "25544"}},
                {"satelliteId": {"S": "no-catalog"}, "name": {"S": "unused"}},
            ],
            "LastEvaluatedKey": {"satelliteId": {"S": "iss"}},
        },
        {
            "Items": [
                {"satelliteId": {"S": "noaa-19"}, "noradId": {"N": "33591"}},
            ]
        },
    ]

    class Paged:
        def scan(self, **kwargs):
            del kwargs
            return pages.pop(0)

    found = SatelliteDirectory(Paged(), "Satellites").tracked()

    assert found == [
        {"satelliteId": "iss", "noradId": "25544"},
        {"satelliteId": "noaa-19", "noradId": "33591"},
    ]
