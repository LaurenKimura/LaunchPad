"""Gap windows, including the sample files in /samples."""

from datetime import datetime, timezone
from pathlib import Path

from gaps import find_gaps, iso_utc
from telemetry import parse_telemetry

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "telemetry"
UTC = timezone.utc


def at(hour: int, minute: int, second: int) -> datetime:
    return datetime(2026, 3, 1, hour, minute, second, tzinfo=UTC)


def test_steady_sample_has_no_gap():
    stamps = parse_telemetry((SAMPLES / "steady.csv").read_bytes(), "telemetry.csv", max_rows=100)
    median, windows = find_gaps(stamps, multiplier=2)
    assert median == 10
    assert windows == []


def test_one_gap_sample_flags_the_sixty_second_hole():
    stamps = parse_telemetry((SAMPLES / "one-gap.csv").read_bytes(), "telemetry.csv", max_rows=100)
    _median, windows = find_gaps(stamps, multiplier=2)
    assert len(windows) == 1
    assert iso_utc(windows[0].start) == "2026-03-01T00:00:30Z"
    assert iso_utc(windows[0].end) == "2026-03-01T00:01:30Z"
    assert windows[0].gap_seconds == 60
    assert windows[0].median_seconds == 10
    assert windows[0].threshold_seconds == 20


def test_mixed_zones_are_compared_in_utc():
    stamps = parse_telemetry((SAMPLES / "mixed-zones.json").read_bytes(), "telemetry.json", max_rows=100)
    _median, windows = find_gaps(stamps, multiplier=2)
    assert [iso_utc(stamp) for stamp in sorted(stamps)][:2] == [
        "2026-03-01T05:00:00Z",
        "2026-03-01T05:00:10Z",
    ]
    assert len(windows) == 1
    assert iso_utc(windows[0].start) == "2026-03-01T05:00:30Z"
    assert iso_utc(windows[0].end) == "2026-03-01T05:02:00Z"


def test_exactly_twice_the_median_is_not_a_gap():
    # "More than 2x". An interval of exactly 20 seconds stays inside the rule.
    stamps = [at(0, 0, 0), at(0, 0, 10), at(0, 0, 20), at(0, 0, 40)]
    _median, windows = find_gaps(stamps, multiplier=2)
    assert windows == []


def test_higher_multiplier_can_hide_a_hole():
    stamps = [at(0, 0, 0), at(0, 0, 10), at(0, 0, 20), at(0, 0, 30), at(0, 0, 55)]
    _median, strict = find_gaps(stamps, multiplier=2)
    _median, loose = find_gaps(stamps, multiplier=3)
    assert len(strict) == 1
    assert loose == []


def test_duplicate_timestamps_do_not_collapse_the_median():
    stamps = [at(0, 0, 0), at(0, 0, 0), at(0, 0, 10), at(0, 0, 20), at(0, 1, 20)]
    median, windows = find_gaps(stamps, multiplier=2)
    assert median == 10
    assert len(windows) == 1
    assert windows[0].gap_seconds == 60


def test_unsorted_input_is_ordered_before_the_median():
    stamps = [at(0, 0, 40), at(0, 0, 0), at(0, 0, 20), at(0, 1, 40), at(0, 0, 10), at(0, 0, 30)]
    _median, windows = find_gaps(stamps, multiplier=2)
    assert len(windows) == 1
    assert iso_utc(windows[0].start) == "2026-03-01T00:00:40Z"


def test_single_sample_has_no_interval():
    median, windows = find_gaps([at(0, 0, 0)], multiplier=2)
    assert median is None
    assert windows == []
