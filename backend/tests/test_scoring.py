"""Independent cause scores. Weights are read from scoring_weights.json."""

import inspect
from datetime import datetime, timedelta, timezone

from scoring import (
    GapFacts,
    OrbitSummary,
    interval_from_record,
    load_weights,
    overlap_fraction,
    score_eclipse,
    score_geomagnetic,
    score_radiation,
    score_software,
    score_window,
)
from scoring import FluxSample, IntervalEvent

UTC = timezone.utc


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, 1, hour, minute, tzinfo=UTC)


def gap(hour: int, minutes: int = 10, anomaly_id: str = "gap-0001") -> GapFacts:
    start = at(hour)
    return GapFacts(anomaly_id, start, start + timedelta(minutes=minutes), minutes * 60)


def sep_covering(weights: dict) -> IntervalEvent:
    event = interval_from_record(
        {
            "dataset": "donki_sep",
            "eventId": "2026-SEP-1",
            "eventTime": "2026-03-01T00:00:00Z",
            "observedAt": "2026-03-01T00:00:00Z#2026-SEP-1",
        },
        weights["association_hours"],
    )
    assert event is not None
    return event


def test_gap_fully_overlapping_a_sep_scores_high_on_radiation_only():
    weights = load_weights()
    window = gap(1)
    event = sep_covering(weights)

    assert overlap_fraction(window, event) == 1
    scores = {
        score.cause_id: score
        for score in score_window(window, [event], [], [], OrbitSummary(available=False), [], weights)
    }

    assert scores["radiation"].score == weights["radiation"]["sep_full_overlap"]
    assert scores["radiation"].score >= 80
    assert "2026-SEP-1" in scores["radiation"].evidence[0]
    assert "entire gap" in scores["radiation"].evidence[0]
    assert scores["eclipse_power"].score == 0
    assert scores["geomagnetic"].score == 0
    assert scores["software_system"].score == 0
    # A high radiation score is not pulled down so the four causes sum to 100.
    assert sum(score.score for score in scores.values()) == scores["radiation"].score


def test_sep_weight_in_the_config_sets_the_score():
    weights = load_weights()
    weights["radiation"]["sep_full_overlap"] = 50
    window = gap(1)
    score = score_radiation(window, [sep_covering(weights)], [], OrbitSummary(available=False), weights)
    assert score.score == 50


def test_full_eclipse_can_score_100_while_radiation_stays_at_the_sep_weight():
    weights = load_weights()
    window = gap(1)
    orbit = OrbitSummary(available=True, ok_count=12, saa_count=0, eclipse_count=12)
    eclipse = score_eclipse(window, orbit, weights)
    radiation = score_radiation(window, [sep_covering(weights)], [], orbit, weights)
    assert eclipse.score == 100
    assert radiation.score == weights["radiation"]["sep_full_overlap"]
    assert eclipse.score + radiation.score > 100


def test_saa_time_adds_radiation_points_and_the_total_clamps_at_100():
    weights = load_weights()
    window = gap(1)
    orbit = OrbitSummary(available=True, ok_count=4, saa_count=4, eclipse_count=0)
    score = score_radiation(window, [sep_covering(weights)], [], orbit, weights)
    assert score.score == 100
    assert any("South Atlantic Anomaly" in line for line in score.evidence)


def test_kp_and_a_storm_score_geomagnetic_without_using_the_sep():
    weights = load_weights()
    window = gap(1)
    storm = IntervalEvent("gst", at(0), at(6), "2026-GST-1")
    score = score_geomagnetic(window, [storm], [FluxSample(at(0), 9)], weights)
    assert score.score == 100
    quiet = score_geomagnetic(window, [], [], weights)
    assert quiet.score == 0


def test_repeating_gap_lengths_score_software_and_ignore_space_weather():
    assert "events" not in inspect.signature(score_software).parameters
    weights = load_weights()
    current = GapFacts("gap-0002", at(3), at(3) + timedelta(minutes=1), 60)
    others = [
        GapFacts("gap-0001", at(1), at(1) + timedelta(minutes=1), 60),
        GapFacts("gap-0003", at(5), at(5) + timedelta(minutes=1), 60),
    ]
    score = score_software(current, others, weights)
    assert score.score == 100
    assert any("2 other gaps" in line for line in score.evidence)
    assert any("every 120 minutes" in line for line in score.evidence)

    alone = score_software(current, [], weights)
    assert alone.score == 0
