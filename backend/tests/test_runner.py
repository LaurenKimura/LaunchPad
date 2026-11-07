"""The hourly run, with mocked HTTP, S3, DynamoDB, and Secrets Manager."""

import json
from datetime import datetime, timezone

from http_client import HttpFailed, HttpResult
from runner import Deps, run
from store import CacheRecord, StoreError


NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
KP_BODY = json.dumps(
    [{"time_tag": "2026-11-07T00:00:00", "Kp": 4.0, "a_running": 27, "station_count": 8}]
).encode()
PROTON_BODY = json.dumps(
    [{"time_tag": "2026-11-07T00:00:00Z", "satellite": 18, "flux": 0.2, "energy": ">=10 MeV"}]
).encode()
FLR_BODY = json.dumps(
    [{"flrID": "2026-11-07T00:00:00-FLR-001", "beginTime": "2026-11-07T00:00:00Z", "classType": "M2.0"}]
).encode()
LINE1 = "1 25544U 98067A   24279.50000000  .00016717  00000-0  10270-3 0  9993"
LINE2 = "2 25544  51.6400 123.4567 0006789  12.3456 347.6543 15.50000000123456"
TLE_BODY = f"ISS (ZARYA)\n{LINE1}\n{LINE2}\n".encode()


class ScriptedHttp:
    def __init__(self, by_host_contains):
        self.by_host_contains = by_host_contains
        self.urls = []

    def fetch(self, url, conditional=None):
        self.urls.append(url)
        for needle, action in self.by_host_contains:
            if needle in url:
                if isinstance(action, Exception):
                    raise action
                if callable(action):
                    return action(url, conditional)
                return action
        raise AssertionError(f"unexpected url {url}")


class MemoryRaw:
    def __init__(self):
        self.archive = {}
        self.cache = {}

    def load(self, key):
        return self.cache.get(key)

    def save_archive(self, key, body, content_type):
        del content_type
        self.archive[key] = body

    def save_cache(self, key, body, content_type, *, etag, last_modified, fetched_at):
        del content_type
        self.cache[key] = CacheRecord(
            body=body,
            etag=etag,
            last_modified=last_modified,
            fetched_at=fetched_at,
            body_sha256=__import__("hashlib").sha256(body).hexdigest(),
        )


class MemoryTable:
    def __init__(self):
        self.items = []

    def put_all(self, items):
        self.items.extend(items)


class Satellites:
    def __init__(self, rows):
        self.rows = rows

    def tracked(self):
        return self.rows


def http_ok(body, etag='"v1"'):
    return HttpResult(status=200, body=body, etag=etag, last_modified=None, not_modified=False)


def build(http, satellites, secret="test-nasa-key", space_weather=None, tle=None, raw=None):
    return Deps(
        http=http,
        raw=raw or MemoryRaw(),
        space_weather=space_weather or MemoryTable(),
        tle=tle or MemoryTable(),
        satellites=satellites,
        secret_reader=lambda: secret,
        now=lambda: NOW,
        lookback_days=7,
    )


def responses(**overrides):
    mapping = {
        "noaa-planetary-k-index": http_ok(KP_BODY),
        "integral-protons": http_ok(PROTON_BODY),
        "/DONKI/SEP": http_ok(b"[]"),
        "/DONKI/FLR": http_ok(FLR_BODY),
        "/DONKI/CME": http_ok(b"[]"),
        "/DONKI/GST": http_ok(b"[]"),
        "celestrak.org": http_ok(TLE_BODY, etag='"tle"'),
    }
    mapping.update(overrides)
    return [(needle, action) for needle, action in mapping.items()]


def test_happy_path_writes_rows_and_archives_without_the_api_key():
    raw = MemoryRaw()
    space = MemoryTable()
    tle = MemoryTable()
    http = ScriptedHttp(responses())
    summary = run(build(http, Satellites([{"satelliteId": "iss", "noradId": "25544"}]), raw=raw, space_weather=space, tle=tle))

    assert summary["ok"] is True
    datasets = {item["dataset"] for item in space.items}
    assert datasets == {"noaa_kp", "noaa_proton_10mev", "donki_flr"}
    assert tle.items[0]["satelliteId"] == "iss"
    assert tle.items[0]["line1"] == LINE1
    donki_urls = [url for url in http.urls if "DONKI" in url]
    assert donki_urls
    assert all("api_key=test-nasa-key" in url for url in donki_urls)
    assert all("startDate=2026-10-31" in url and "endDate=2026-11-07" in url for url in donki_urls)
    archived = b"".join(raw.archive.values())
    assert b"test-nasa-key" not in archived
    assert all("test-nasa-key" not in json.dumps(item, default=str) for item in space.items)


def test_cache_hit_does_not_write_again():
    raw = MemoryRaw()
    space = MemoryTable()
    deps = build(
        ScriptedHttp(responses()),
        Satellites([]),
        raw=raw,
        space_weather=space,
    )
    first = run(deps)
    assert first["ok"] is True
    written = len(space.items)

    def same_body(url, conditional):
        del conditional
        for needle, action in responses():
            if needle in url and isinstance(action, HttpResult):
                return http_ok(action.body, etag=action.etag)
        raise AssertionError(url)

    second_http = ScriptedHttp([(needle, same_body) for needle, _action in responses()])
    deps.http = second_http
    second = run(deps)

    assert second["ok"] is True
    assert len(space.items) == written
    assert any(item["status"] == "cached" for item in second["results"])


def test_donki_outage_still_saves_noaa_and_hides_the_key():
    space = MemoryTable()
    http = ScriptedHttp(
        responses(
            **{
                "/DONKI/SEP": HttpFailed("status_503 for https://api.nasa.gov/DONKI/SEP?api_key=test-nasa-key"),
                "/DONKI/FLR": HttpFailed("status_503 for https://api.nasa.gov/DONKI/FLR?api_key=test-nasa-key"),
                "/DONKI/CME": HttpFailed("status_503"),
                "/DONKI/GST": HttpFailed("status_503"),
            }
        )
    )
    summary = run(build(http, Satellites([]), space_weather=space))

    assert summary["ok"] is False
    by_source = {item["source"]: item for item in summary["results"]}
    assert by_source["noaa_kp"]["status"] == "ok"
    assert by_source["noaa_proton"]["status"] == "ok"
    assert by_source["donki_sep"]["status"] == "outage"
    assert "test-nasa-key" not in by_source["donki_sep"]["error"]
    assert "REDACTED" in by_source["donki_sep"]["error"]
    assert {item["dataset"] for item in space.items} == {"noaa_kp", "noaa_proton_10mev"}


def test_missing_secret_skips_donki_only():
    http = ScriptedHttp(responses())

    def boom():
        raise RuntimeError("AccessDenied secret-value-should-not-leak")

    deps = build(http, Satellites([]), secret=boom)
    # secret_reader is the callable itself.
    deps.secret_reader = boom
    summary = run(deps)

    by_source = {item["source"]: item for item in summary["results"]}
    assert by_source["donki_flr"]["error"] == "nasa_secret_unreadable"
    assert by_source["noaa_kp"]["status"] == "ok"
    assert not any("DONKI" in url for url in http.urls)
    blob = json.dumps(summary)
    assert "secret-value-should-not-leak" not in blob


def test_no_satellites_skips_celestrak_without_calling_it():
    http = ScriptedHttp(responses())
    summary = run(build(http, Satellites([])))

    assert all("celestrak.org" not in url for url in http.urls)
    celestrak = next(item for item in summary["results"] if item["source"] == "celestrak_tle")
    assert celestrak["status"] == "skipped"


def test_failed_dynamodb_write_does_not_advance_the_cache():
    raw = MemoryRaw()

    class Boom(MemoryTable):
        def put_all(self, items):
            raise StoreError("dynamodb_down test-nasa-key")

    summary = run(
        build(
            ScriptedHttp(responses()),
            Satellites([]),
            raw=raw,
            space_weather=Boom(),
        )
    )

    assert raw.archive
    assert raw.cache == {}
    kp = next(item for item in summary["results"] if item["source"] == "noaa_kp")
    assert kp["status"] == "outage"
    assert "test-nasa-key" not in kp["error"]


def test_one_tle_outage_keeps_the_other_satellite():
    def tle_for(url, conditional):
        del conditional
        if "CATNR=25544" in url:
            return http_ok(TLE_BODY)
        raise HttpFailed("status_404")

    http = ScriptedHttp(responses(**{"celestrak.org": tle_for}))
    tle = MemoryTable()
    summary = run(
        build(
            http,
            Satellites(
                [
                    {"satelliteId": "iss", "noradId": "25544"},
                    {"satelliteId": "missing", "noradId": "99999"},
                ]
            ),
            tle=tle,
        )
    )

    celestrak = next(item for item in summary["results"] if item["source"] == "celestrak_tle")
    assert celestrak["status"] == "partial"
    assert [item["satelliteId"] for item in tle.items] == ["iss"]
    assert summary["ok"] is False
