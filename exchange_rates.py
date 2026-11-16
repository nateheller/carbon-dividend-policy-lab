"""Bank of Canada daily averages, in CAD per unit of foreign currency."""

import json
import math
from datetime import date
from threading import Lock
from time import monotonic
from urllib.request import urlopen

CURRENCIES = ("USD", "EUR", "GBP")
VALET_URL = (
    "https://www.bankofcanada.ca/valet/observations/FXUSDCAD,FXEURCAD,FXGBPCAD/json?recent=1"
)
# Published at https://www.bankofcanada.ca/rates/exchange/daily-exchange-rates/
BUNDLED_RATES = {"date": "2026-11-13", "cadPerUnit": {"USD": 1.4257, "EUR": 1.5734, "GBP": 1.8848}}

_lock = Lock()
_next_fetch = 0
_rates = BUNDLED_RATES
_refreshed = False


def parse_rates(payload):
    row = payload["observations"][-1]
    day = date.fromisoformat(row["d"]).isoformat()
    rates = {code: float(row[f"FX{code}CAD"]["v"]) for code in CURRENCIES}
    if any(not math.isfinite(value) or value <= 0 for value in rates.values()):
        raise ValueError("Invalid exchange rate")
    return {"date": day, "cadPerUnit": rates}


def latest_rates():
    """Reuse a complete dated snapshot if the Bank is unreachable."""
    global _next_fetch, _rates, _refreshed
    with _lock:
        if monotonic() >= _next_fetch:
            _refreshed = False
            try:
                with urlopen(VALET_URL, timeout=3) as response:
                    candidate = parse_rates(json.load(response))
                if candidate["date"] >= _rates["date"]:
                    _rates = candidate
                    _refreshed = True
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                pass
            _next_fetch = monotonic() + (3600 if _refreshed else 300)
        return {"rates": _rates, "refreshed": _refreshed}
