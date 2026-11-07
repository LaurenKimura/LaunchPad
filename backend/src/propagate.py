"""SGP4 position, South Atlantic Anomaly, and Earth shadow for one gap.

sgp4 returns TEME coordinates in kilometres. Latitude and longitude use a
spherical Earth and Greenwich mean sidereal time, which is enough to test
the configured SAA box. Eclipse uses a cylindrical Earth shadow in that
same frame. The cylinder is a little larger than the true umbra.

These helpers do not read files or talk to AWS. A bad TLE becomes a short
error code. The element lines are not included in that code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class PropagationSettings:
    sample_seconds: int
    max_samples: int
    saa_lat_min: float
    saa_lat_max: float
    saa_lon_min: float
    saa_lon_max: float
    earth_radius_km: float


@dataclass(frozen=True)
class OrbitFix:
    at: datetime
    latitude_deg: float | None
    longitude_deg: float | None
    altitude_km: float | None
    in_saa: bool
    in_eclipse: bool
    ok: bool


@dataclass(frozen=True)
class Propagation:
    samples: list[OrbitFix]
    failure: str | None = None


def settings_from_weights(weights: dict[str, Any]) -> PropagationSettings:
    block = weights["propagation"]
    return PropagationSettings(
        sample_seconds=int(block["sample_seconds"]),
        max_samples=int(block["max_samples"]),
        saa_lat_min=float(block["saa_lat_min"]),
        saa_lat_max=float(block["saa_lat_max"]),
        saa_lon_min=float(block["saa_lon_min"]),
        saa_lon_max=float(block["saa_lon_max"]),
        earth_radius_km=float(block["earth_radius_km"]),
    )


def propagate_window(
    line1: str,
    line2: str,
    start: datetime,
    end: datetime,
    settings: PropagationSettings,
) -> Propagation:
    try:
        from sgp4.api import Satrec, jday
    except ImportError:
        return Propagation(samples=[], failure="sgp4_unavailable")
    try:
        satellite = Satrec.twoline2rv(line1.strip(), line2.strip())
    except (ValueError, AttributeError):
        return Propagation(samples=[], failure="tle_unreadable")

    samples: list[OrbitFix] = []
    any_ok = False
    for moment in sample_times(start, end, settings.sample_seconds, settings.max_samples):
        jd, fraction = jday(
            moment.year,
            moment.month,
            moment.day,
            moment.hour,
            moment.minute,
            moment.second + moment.microsecond / 1_000_000,
        )
        error, position, _velocity = satellite.sgp4(jd, fraction)
        if error != 0:
            samples.append(_failed(moment))
            continue
        any_ok = True
        latitude, longitude, altitude = teme_to_geodetic(position, jd + fraction, settings.earth_radius_km)
        sun = sun_unit(moment)
        samples.append(
            OrbitFix(
                at=moment,
                latitude_deg=latitude,
                longitude_deg=longitude,
                altitude_km=altitude,
                in_saa=in_saa(latitude, longitude, settings),
                in_eclipse=in_earth_shadow(position, sun, settings.earth_radius_km),
                ok=True,
            )
        )
    if not any_ok:
        return Propagation(samples=samples, failure="propagation_failed")
    return Propagation(samples=samples)


def sample_times(start: datetime, end: datetime, step_seconds: int, max_samples: int) -> list[datetime]:
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if end < start:
        return []
    duration = (end - start).total_seconds()
    step = float(step_seconds if step_seconds > 0 else 60)
    count = int(duration // step) + 1
    if max_samples > 1 and count > max_samples:
        step = duration / (max_samples - 1)
    times: list[datetime] = []
    index = 0
    while len(times) < max_samples:
        moment = start + timedelta(seconds=index * step)
        if moment >= end:
            break
        times.append(moment)
        index += 1
    if not times or times[-1] != end:
        if len(times) >= max_samples:
            times[-1] = end
        else:
            times.append(end)
    return times


def teme_to_geodetic(position_km: tuple[float, float, float], julian: float, earth_radius_km: float) -> tuple[float, float, float]:
    """TEME kilometres to geodetic degrees and altitude. GMST rotates about Z."""

    x_teme, y_teme, z_teme = position_km
    theta = gmst_radians(julian)
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    x_ecef = cos_theta * x_teme + sin_theta * y_teme
    y_ecef = -sin_theta * x_teme + cos_theta * y_teme
    horizontal = math.hypot(x_ecef, y_ecef)
    latitude = math.degrees(math.atan2(z_teme, horizontal))
    longitude = _wrap_degrees(math.degrees(math.atan2(y_ecef, x_ecef)))
    radius = math.sqrt(x_teme * x_teme + y_teme * y_teme + z_teme * z_teme)
    return latitude, longitude, radius - earth_radius_km


def in_saa(latitude: float, longitude: float, settings: PropagationSettings) -> bool:
    return (
        settings.saa_lat_min <= latitude <= settings.saa_lat_max
        and settings.saa_lon_min <= longitude <= settings.saa_lon_max
    )


def in_earth_shadow(position_km: tuple[float, float, float], sun: tuple[float, float, float], earth_radius_km: float) -> bool:
    """True when the satellite is behind the Earth in a cylindrical shadow."""

    along = position_km[0] * sun[0] + position_km[1] * sun[1] + position_km[2] * sun[2]
    if along >= 0:
        return False
    radial_x = position_km[0] - along * sun[0]
    radial_y = position_km[1] - along * sun[1]
    radial_z = position_km[2] - along * sun[2]
    radial = math.sqrt(radial_x * radial_x + radial_y * radial_y + radial_z * radial_z)
    return radial < earth_radius_km


def sun_unit(moment: datetime) -> tuple[float, float, float]:
    """Low-precision Sun direction in the same approximate inertial frame as TEME."""

    moment = moment.astimezone(timezone.utc)
    julian = _julian(moment)
    days = julian - 2451545.0
    mean_longitude = math.radians((280.460 + 0.9856474 * days) % 360.0)
    mean_anomaly = math.radians((357.528 + 0.9856003 * days) % 360.0)
    ecliptic = mean_longitude + math.radians(1.915) * math.sin(mean_anomaly) + math.radians(0.020) * math.sin(2 * mean_anomaly)
    obliquity = math.radians(23.439 - 0.0000004 * days)
    x = math.cos(ecliptic)
    y = math.cos(obliquity) * math.sin(ecliptic)
    z = math.sin(obliquity) * math.sin(ecliptic)
    length = math.sqrt(x * x + y * y + z * z)
    return x / length, y / length, z / length


def gmst_radians(julian: float) -> float:
    centuries = (julian - 2451545.0) / 36525.0
    seconds = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * centuries
        + 0.093104 * centuries * centuries
        - 6.2e-6 * centuries * centuries * centuries
    )
    return math.radians((seconds / 240.0) % 360.0)


def _julian(moment: datetime) -> float:
    from sgp4.api import jday

    jd, fraction = jday(
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second + moment.microsecond / 1_000_000,
    )
    return jd + fraction


def _failed(moment: datetime) -> OrbitFix:
    return OrbitFix(moment, None, None, None, False, False, False)


def _wrap_degrees(degrees: float) -> float:
    wrapped = (degrees + 180.0) % 360.0 - 180.0
    if wrapped == -180.0:
        return 180.0
    return wrapped
