"""SGP4 propagation and the SAA / eclipse checks."""

from datetime import datetime, timedelta, timezone

from propagate import in_earth_shadow, in_saa, propagate_window, settings_from_weights, sun_unit
from scoring import load_weights

UTC = timezone.utc
# Element set used by the fetch tests. Mean motion is about 15.5 rev/day.
LINE1 = "1 25544U 98067A   24279.50000000  .00016717  00000-0  10270-3 0  9993"
LINE2 = "2 25544  51.6400 123.4567 0006789  12.3456 347.6543 15.50000000123456"


def test_sgp4_returns_a_leo_position_inside_the_inclination():
    weights = load_weights()
    settings = settings_from_weights(weights)
    start = datetime(2024, 10, 5, 12, 0, tzinfo=UTC)
    result = propagate_window(LINE1, LINE2, start, start + timedelta(minutes=2), settings)

    assert result.failure is None
    assert result.samples[0].ok
    assert result.samples[-1].at == start + timedelta(minutes=2)
    altitude = result.samples[0].altitude_km
    latitude = result.samples[0].latitude_deg
    longitude = result.samples[0].longitude_deg
    assert altitude is not None and 300 < altitude < 600
    assert latitude is not None and abs(latitude) <= 52
    assert longitude is not None and -180 <= longitude <= 180


def test_saa_box_is_the_configured_rectangle():
    settings = settings_from_weights(load_weights())
    assert in_saa(-30, -40, settings)
    assert not in_saa(40, 10, settings)
    assert not in_saa(-30, 50, settings)


def test_cylindrical_shadow_is_the_night_side_inside_earth_radius():
    sun = (1.0, 0.0, 0.0)
    assert in_earth_shadow((-7000.0, 0.0, 0.0), sun, 6371.0)
    assert not in_earth_shadow((7000.0, 0.0, 0.0), sun, 6371.0)
    assert not in_earth_shadow((-7000.0, 7000.0, 0.0), sun, 6371.0)
    length = sum(component * component for component in sun_unit(datetime(2026, 3, 1, tzinfo=UTC)))
    assert abs(length - 1) < 1e-9
