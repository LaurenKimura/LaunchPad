"""Upstream URLs. The NASA key is added only for DONKI, and only as a query parameter."""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlencode

DONKI_BASE = "https://api.nasa.gov/DONKI"
DONKI_KINDS = ("SEP", "FLR", "CME", "GST")
NOAA_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
NOAA_PROTON_URL = "https://services.swpc.noaa.gov/json/goes/primary/integral-protons-1-day.json"
CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"


def donki_url(kind: str, *, api_key: str, today: date, lookback_days: int) -> str:
    # DONKI rejects windows longer than about 30 days. Clamp so a bad env
    # value cannot turn the hourly job into a failing request.
    days = min(max(lookback_days, 1), 30)
    end = today
    start = end - timedelta(days=days)
    query = urlencode(
        {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "api_key": api_key,
        }
    )
    return f"{DONKI_BASE}/{kind.upper()}?{query}"


def celestrak_tle_url(norad_id: str) -> str:
    # FORMAT=TLE is the three-line set: name, line 1, line 2.
    query = urlencode({"CATNR": norad_id, "FORMAT": "TLE"})
    return f"{CELESTRAK_GP_URL}?{query}"
