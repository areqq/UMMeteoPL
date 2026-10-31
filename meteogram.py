# -*- coding: utf-8 -*-
"""meteo.pl UM forecast for a point from the meteogram API of app.meteo.pl.

The old site (old.meteo.pl, ready-made meteogram pictures per location id) was
shut down in October 2026. The new application fetches the numbers for a point
and draws the chart itself; so does this plugin (chart.py). Location ids of the
catalogue (woj/*) are mapped to coordinates by coords.tsv. No enigma2 imports."""
import json
import os
import time
from urllib.request import Request, urlopen

API = "https://devmgramapi.meteo.pl/meteorograms"
MODEL = "um4_60"            # UM 4 km, 60 hourly steps (um4_120 and gfs exist too)
USER_AGENT = "UMMeteoPL (enigma2 plugin)"
TIMEOUT = 15
COORDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coords.tsv")
MISSING = -1e6              # the API marks 'no value' with a huge negative number

# series names used by chart.py; every one is in each response (checked 2026-10-31)
SERIES = (
    "airtmp_point", "airtmp_min", "airtmp_max", "grdtmp_min", "grdtmp_max", "dwptmp_point",
    "wchill_point", "wchill_min", "wchill_max",
    "pcpttl_aver", "pcpttl_max", "pcpttl_type_max", "pcpttlprob_point", "storm_max", "flash_max",
    "realhum_aver", "slpres_point",
    "wind10_sd_true_prev_point", "wind_gust_max", "wind10_dr_deg_true_prev_point",
    "cldbse01", "cldbse25", "cldbse45", "cldbse65", "cldbse79", "cldtop", "visibl_min",
    "cldvlow_aver", "cldlow_aver", "cldmed_aver", "cldhigh_aver", "cldtot_aver", "fog_max",
)
# pcpttl_type_max codes (app.meteo.pl: none, rain, snow, sleet)
RAIN, SNOW, SLEET = 1, 2, 3


class ParseError(Exception):
    pass


class Forecast:
    __slots__ = ("run_time", "start", "interval", "lat", "lon", "row", "col", "series")

    def __init__(self, run_time, start, interval, lat, lon, row, col, series):
        self.run_time = run_time      # model run, unix time (UTC)
        self.start = start            # first hourly value, unix time
        self.interval = interval      # seconds between values (3600)
        self.lat, self.lon = lat, lon
        self.row, self.col = row, col # UM grid cell
        self.series = series          # name -> [float or None] * steps

    @property
    def steps(self):
        return len(self.series["airtmp_point"])

    @property
    def run(self):
        """'31.10.2026 06 UTC' - the status line of the meteogram screen."""
        return time.strftime("%d.%m.%Y %H UTC", time.gmtime(self.run_time))

    def times(self):
        return [self.start + i * self.interval for i in range(self.steps)]

    def __getitem__(self, name):
        return self.series[name]


def load_coords(path=COORDS_FILE):
    """coords.tsv -> {location id: (lat, lon)}"""
    table = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) == 3 and parts[0].isdigit():
                table[parts[0]] = (float(parts[1]), float(parts[2]))
    return table


def http_get(url, timeout=TIMEOUT):
    """Blocking GET -> bytes. Run it off the reactor thread."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def http_post(url, body, timeout=TIMEOUT):
    """Blocking POST of a JSON document (bytes) -> bytes."""
    req = Request(url, data=body, headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_available(raw, model=MODEL):
    """/meteorograms/available -> model runs (unix time), newest first."""
    try:
        runs = json.loads(raw.decode("utf-8"))[model]
        return sorted((int(r) for r in runs), reverse=True)
    except (ValueError, KeyError, TypeError) as e:
        raise ParseError(f"meteo.pl: nieznana lista prognoz ({e})") from None


def _clean(values, steps):
    out = [None if v is None or v < MISSING else float(v) for v in values]
    return out[:steps] if len(out) >= steps else out + [None] * (steps - len(out))


def parse_forecast(raw, run_time, lat, lon):
    """POST /meteorograms/<model> response -> Forecast. Raises ParseError."""
    try:
        data = json.loads(raw.decode("utf-8"))["data"]
        ref = data["airtmp_point"]
        start, interval, steps = int(ref["first_timestamp"]), int(ref["interval"]), len(ref["data"])
        if steps < 2 or interval <= 0:
            raise ValueError("pusta prognoza")
        series = {}
        for name in SERIES:
            item = data.get(name)
            series[name] = _clean(item["data"], steps) if item else [None] * steps
        point = ref.get("point") or {}
        return Forecast(run_time, start, interval, lat, lon, point.get("row"), point.get("col"), series)
    except (ValueError, KeyError, TypeError) as e:
        raise ParseError(f"meteo.pl: nieznana odpowiedź ({e})") from None


def request_body(lat, lon, run_time):
    return json.dumps({"point": {"lat": f"{lat:.4f}", "lon": f"{lon:.4f}"}, "date": run_time}).encode()


def fetch(location_id, get=http_get, post=http_post, coords=None):
    """Blocking: the newest UM forecast for a catalogue location -> Forecast."""
    coords = coords or load_coords()
    if location_id not in coords:
        raise ParseError("Brak współrzędnych tej lokalizacji")
    lat, lon = coords[location_id]
    runs = parse_available(get(f"{API}/available"))
    if not runs:
        raise ParseError("meteo.pl nie ma żadnej prognozy")
    # the newest run can still be incomplete on the server: fall back to the one before
    for n, run_time in enumerate(runs[:2]):
        try:
            return parse_forecast(post(f"{API}/{MODEL}", request_body(lat, lon, run_time)), run_time, lat, lon)
        except (OSError, ParseError):
            if n == len(runs[:2]) - 1:
                raise

