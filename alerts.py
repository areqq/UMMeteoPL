# -*- coding: utf-8 -*-
"""IMGW-PIB meteorological warnings from the public API. No enigma2 imports.

The API lists the counties a warning applies to as 4-digit TERYT codes;
teryt.tsv maps meteo.pl location ids to those codes."""
import json
import os
from datetime import datetime

from . import meteogram

URL = "https://danepubliczne.imgw.pl/api/data/warningsmeteo"
NO_WARNINGS = "Brak ostrzeżeń meteorologicznych"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"     # Polish local time, as on meteo.imgw.pl
TERYT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "teryt.tsv")


class Alert:
    __slots__ = ("event", "level", "probability", "valid_from", "valid_to", "text", "office", "counties")

    def __init__(self, raw):
        self.event = raw["nazwa_zdarzenia"].strip()
        self.level = int(raw["stopien"])
        self.probability = raw.get("prawdopodobienstwo") or ""
        self.valid_from = datetime.strptime(raw["obowiazuje_od"], TIME_FORMAT)
        self.valid_to = datetime.strptime(raw["obowiazuje_do"], TIME_FORMAT)
        self.text = (raw.get("tresc") or "").strip()
        self.office = (raw.get("biuro") or "").strip()
        self.counties = frozenset(raw["teryt"])

    def period(self, now):
        if self.valid_from > now:
            return f"od {when(self.valid_from, now)} do {when(self.valid_to, now)}"
        return f"do {when(self.valid_to, now)}"

    def details(self, now):
        lines = [f"{self.event} - ostrzeżenie {self.level}. stopnia", self.period(now).capitalize()]
        if self.probability:
            lines.append(f"Prawdopodobieństwo: {self.probability}%")
        if self.text:
            lines += ["", self.text]
        if self.office:
            lines += ["", self.office]
        return "\n".join(lines)


def when(moment, now):
    return moment.strftime("%H:%M" if moment.date() == now.date() else "%d.%m %H:%M")


def parse(raw):
    """API response (bytes) -> [Alert]. Raises meteogram.ParseError."""
    try:
        data = json.loads(raw.decode("utf-8"))
        if data == {"message": NO_WARNINGS}:
            return []
        if not isinstance(data, list):
            raise ValueError(f"unexpected response {data!r:.200}")
        return [Alert(item) for item in data]
    except (ValueError, KeyError, TypeError) as e:
        raise meteogram.ParseError(f"Nieczytelne ostrzeżenia IMGW: {e}")


def for_county(warnings, county, now):
    """Warnings for one county that have not expired, most severe first."""
    found = [w for w in warnings if county in w.counties and w.valid_to > now]
    return sorted(found, key=lambda w: (-w.level, w.valid_from))


def summary(found, now):
    """One short footer line, e.g. '1. st. Silny wiatr do 15:00 (+1)'."""
    if not found:
        return ""
    top = found[0]
    if top.valid_from > now:
        period = f"od {when(top.valid_from, now)}"
    else:
        period = f"do {when(top.valid_to, now)}"
    more = f" (+{len(found) - 1})" if len(found) > 1 else ""
    return f"{top.level}. st. {top.event} {period}{more}"


def load_counties(path=TERYT_FILE):
    counties = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#"):
                    location_id, _, code = line.strip().partition("\t")
                    if code:
                        counties[location_id] = code
    except OSError as e:
        print(f"[UMMeteo] cannot read {path}: {e}")
    return counties


def fetch(get=meteogram.http_get):
    """Blocking: all current warnings."""
    return parse(get(URL))
