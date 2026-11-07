"""Normalized items from mocked upstream payloads."""

from decimal import Decimal

import pytest

from normalize import UnexpectedPayload, normalize_donki, normalize_kp, normalize_protons, normalize_tle, tle_epoch_iso


FETCHED = "2026-11-07T12:00:00Z"
RAW = "raw/test/2026-11-07/2026-11-07T12:00:00Z.json"


def test_kp_object_rows_are_utc_samples():
    items = normalize_kp(
        [
            {"time_tag": "2026-10-31T00:00:00", "Kp": Decimal("3.00"), "a_running": Decimal("15"), "station_count": Decimal("8")},
            {"time_tag": "2026-10-31T03:00:00", "Kp": Decimal("6.00"), "a_running": Decimal("80"), "station_count": Decimal("8")},
        ],
        raw_s3_key=RAW,
        fetched_at=FETCHED,
    )

    assert [item["observedAt"] for item in items] == [
        "2026-10-31T00:00:00Z",
        "2026-10-31T03:00:00Z",
    ]
    assert items[1]["dataset"] == "noaa_kp"
    assert items[1]["kp"] == Decimal("6.00")
    assert items[1]["source"] == "noaa_swpc"


def test_legacy_kp_rows_skip_the_header():
    items = normalize_kp(
        [
            ["time_tag", "Kp", "a_running", "station_count"],
            ["2026-10-31 00:00:00.000", "3.33", "18", "8"],
        ],
        raw_s3_key=RAW,
        fetched_at=FETCHED,
    )

    assert len(items) == 1
    assert items[0]["observedAt"] == "2026-10-31T00:00:00Z"
    assert items[0]["kp"] == Decimal("3.33")


def test_proton_channels_are_independent_datasets_and_duplicate_keys_collapse():
    items = normalize_protons(
        [
            {"time_tag": "2026-11-06T20:20:00Z", "satellite": 18, "flux": Decimal("0.31"), "energy": ">=10 MeV"},
            {"time_tag": "2026-11-06T20:20:00Z", "satellite": 19, "flux": Decimal("0.50"), "energy": ">=10 MeV"},
            {"time_tag": "2026-11-06T20:20:00Z", "satellite": 18, "flux": Decimal("0.24"), "energy": ">=100 MeV"},
            {"time_tag": "2026-11-06T20:25:00Z", "satellite": 18, "flux": Decimal("1.5"), "energy": ">=7 MeV"},
        ],
        raw_s3_key=RAW,
        fetched_at=FETCHED,
    )
    by_key = {(item["dataset"], item["observedAt"]): item for item in items}

    assert by_key[("noaa_proton_10mev", "2026-11-06T20:20:00Z")]["flux"] == Decimal("0.50")
    assert by_key[("noaa_proton_100mev", "2026-11-06T20:20:00Z")]["flux"] == Decimal("0.24")
    assert by_key[("noaa_proton_7_mev", "2026-11-06T20:25:00Z")]["energy"] == ">=7 MeV"
    assert len(items) == 3


def test_donki_events_keep_separate_scores_of_likelihood_rows():
    # Two flares that start at the same second must both survive.
    items = normalize_donki(
        "FLR",
        [
            {
                "flrID": "2024-05-08T01:23:00-FLR-001",
                "beginTime": "2024-05-08T01:23Z",
                "peakTime": "2024-05-08T01:30Z",
                "endTime": "2024-05-08T01:40Z",
                "classType": "M1.2",
                "sourceLocation": "N12W34",
                "activeRegionNum": 3664,
                "instruments": [{"displayName": "GOES"}],
            },
            {
                "flrID": "2024-05-08T01:23:00-FLR-002",
                "beginTime": "2024-05-08T01:23:00Z",
                "classType": "C4.0",
            },
        ],
        raw_s3_key=RAW,
        fetched_at=FETCHED,
    )

    assert len(items) == 2
    assert items[0]["dataset"] == "donki_flr"
    assert items[0]["observedAt"].startswith("2024-05-08T01:23:00Z#")
    assert items[0]["observedAt"] != items[1]["observedAt"]
    assert items[0]["classType"] == "M1.2"
    assert items[0]["instruments"] == "GOES"
    assert "score" not in items[0]


def test_donki_cme_uses_the_most_accurate_speed_and_gst_uses_max_kp():
    cme = normalize_donki(
        "CME",
        [
            {
                "activityID": "2024-05-08T12:00:00-CME-001",
                "startTime": "2024-05-08T12:00:00Z",
                "cmeAnalyses": [
                    {"speed": Decimal("400"), "isMostAccurate": False},
                    {"speed": Decimal("850"), "isMostAccurate": True},
                ],
            }
        ],
        raw_s3_key=RAW,
        fetched_at=FETCHED,
    )
    gst = normalize_donki(
        "GST",
        [
            {
                "gstID": "2024-05-11T01:00:00-GST-001",
                "startTime": "2024-05-11T01:00:00Z",
                "allKpIndex": [
                    {"kpIndex": Decimal("5")},
                    {"kpIndex": Decimal("8")},
                ],
            }
        ],
        raw_s3_key=RAW,
        fetched_at=FETCHED,
    )
    sep = normalize_donki(
        "SEP",
        [{"sepID": "2024-05-08T12:00:00-SEP-001", "eventTime": "2024-05-08T12:00:00Z"}],
        raw_s3_key=RAW,
        fetched_at=FETCHED,
    )

    assert cme[0]["speedKmPerSec"] == Decimal("850")
    assert cme[0]["dataset"] == "donki_cme"
    assert gst[0]["maxKp"] == Decimal("8")
    assert gst[0]["dataset"] == "donki_gst"
    assert sep[0]["dataset"] == "donki_sep"


def test_donki_error_object_is_rejected():
    with pytest.raises(UnexpectedPayload):
        normalize_donki("FLR", {"message": "Internal server error"}, raw_s3_key=RAW, fetched_at=FETCHED)


def test_tle_epoch_and_lines():
    # Columns 19-20 are the year (24) and columns 21-32 are day 279.5.
    line1 = "1 25544U 98067A   24279.50000000  .00016717  00000-0  10270-3 0  9993"
    line2 = "2 25544  51.6400 123.4567 0006789  12.3456 347.6543 15.50000000123456"
    assert len(line1) >= 69 and len(line2) >= 69
    assert tle_epoch_iso(line1) == "2024-10-05T12:00:00Z"

    body = f"ISS (ZARYA)\n{line1}\n{line2}\n".encode()
    items = normalize_tle("iss", body, raw_s3_key="raw/celestrak/25544/x.tle", fetched_at=FETCHED)

    assert items == [
        {
            "satelliteId": "iss",
            "epoch": "2024-10-05T12:00:00Z",
            "noradId": "25544",
            "objectName": "ISS (ZARYA)",
            "line1": line1,
            "line2": line2,
            "source": "celestrak",
            "rawS3Key": "raw/celestrak/25544/x.tle",
            "fetchedAt": FETCHED,
        }
    ]


def test_tle_without_an_element_pair_is_rejected():
    with pytest.raises(UnexpectedPayload):
        normalize_tle("iss", b"No GP data found", raw_s3_key="raw/x", fetched_at=FETCHED)
