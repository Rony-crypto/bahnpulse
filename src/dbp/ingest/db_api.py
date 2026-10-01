"""Minimal client for the DB API Marketplace (Timetables + StaDa).

Credentials come from .env (DB_CLIENT_ID, DB_API_KEY). If you get HTTP 401/403, check that your
application is subscribed to the API in the Marketplace and compare the header names with the
API's documentation page.
"""

from __future__ import annotations

import logging
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from dbp.config import env

log = logging.getLogger(__name__)

API_ROOT = "https://apis.deutschebahn.com/db-api-marketplace/apis"
TIMETABLES = f"{API_ROOT}/timetables/v1"
STADA = f"{API_ROOT}/station-data/v2"

# Free Timetables plan: 60 calls/min. We stay far below with a small pause between calls.
MIN_SECONDS_BETWEEN_CALLS = 1.1


class RateLimited(Exception):
    """Raised on HTTP 429 so tenacity retries with backoff."""


_last_call = 0.0


def _headers(accept: str) -> dict[str, str]:
    return {
        "DB-Client-Id": env("DB_CLIENT_ID"),
        "DB-Api-Key": env("DB_API_KEY"),
        "Accept": accept,
    }


@retry(
    retry=retry_if_exception_type((RateLimited, requests.ConnectionError, requests.Timeout)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=2, max=60),
    reraise=True,
)
def get(url: str, accept: str = "application/json") -> requests.Response:
    global _last_call
    wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    r = requests.get(url, headers=_headers(accept), timeout=30)
    if r.status_code == 429:
        log.warning("rate limited, backing off")
        raise RateLimited(url)
    r.raise_for_status()
    return r


def stada_stations(searchstring: str) -> dict:
    """StaDa station search, e.g. 'Hamburg Hbf' or 'Hamburg*'."""
    return get(f"{STADA}/stations?searchstring={requests.utils.quote(searchstring)}").json()


def timetables_station(pattern: str) -> str:
    """Timetables station lookup by name pattern; returns XML with eva numbers."""
    return get(
        f"{TIMETABLES}/station/{requests.utils.quote(pattern)}", accept="application/xml"
    ).text
