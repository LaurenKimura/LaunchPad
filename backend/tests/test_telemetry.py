"""CSV and JSON parsing. Errors carry a code and not the file text."""

from datetime import datetime, timezone

import pytest

from telemetry import TelemetryError, parse_telemetry, parse_timestamp


def test_iso_offsets_become_utc():
    stamp = parse_timestamp("2026-03-01T00:00:00-05:00")
    assert stamp == datetime(2026, 3, 1, 5, 0, tzinfo=timezone.utc)


def test_naive_timestamp_is_utc():
    stamp = parse_timestamp("2026-03-01 00:00:10")
    assert stamp == datetime(2026, 3, 1, 0, 0, 10, tzinfo=timezone.utc)


def test_epoch_milliseconds():
    expected = datetime(2026, 3, 1, tzinfo=timezone.utc)
    stamp = parse_timestamp(int(expected.timestamp() * 1000))
    assert stamp == expected


def test_csv_requires_a_timestamp_column():
    with pytest.raises(TelemetryError) as raised:
        parse_telemetry(b"voltage\n1\n", "telemetry.csv", max_rows=10)
    assert raised.value.code == "invalid_format"
    assert "voltage" not in str(raised.value)


def test_bad_timestamp_does_not_echo_the_cell():
    body = b"timestamp\nnot-a-time\n"
    with pytest.raises(TelemetryError) as raised:
        parse_telemetry(body, "telemetry.csv", max_rows=10)
    assert raised.value.code == "invalid_timestamp"
    assert "not-a-time" not in str(raised.value)


def test_json_samples_list_and_bare_strings():
    body = b'{"records":["2026-03-01T00:00:00Z","2026-03-01T00:00:10Z"]}'
    stamps = parse_telemetry(body, "telemetry.json", max_rows=10)
    assert len(stamps) == 2
    assert stamps[0].tzinfo == timezone.utc


def test_too_many_rows():
    body = b"timestamp\n2026-03-01T00:00:00Z\n2026-03-01T00:00:10Z\n"
    with pytest.raises(TelemetryError) as raised:
        parse_telemetry(body, "telemetry.csv", max_rows=1)
    assert raised.value.code == "too_many_rows"


def test_empty_file():
    with pytest.raises(TelemetryError) as raised:
        parse_telemetry(b"", "telemetry.csv", max_rows=10)
    assert raised.value.code == "empty"
