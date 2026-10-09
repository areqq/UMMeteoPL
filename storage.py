# -*- coding: utf-8 -*-
"""Favourite locations and the town catalogue (woj/*). No enigma2 imports."""
import os
import unicodedata

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
WOJ_DIR = os.path.join(PLUGIN_DIR, "woj")
LEGACY_CONFIG_FILE = os.path.join(PLUGIN_DIR, "meteo.ini")

# (label, file name in woj/)
VOIVODESHIPS = (
    ("dolnośląskie", "dolnoslaskie"),
    ("kujawsko-pomorskie", "kujawsko-pomorskie"),
    ("lubelskie", "lubelskie"),
    ("lubuskie", "lubuskie"),
    ("łódzkie", "lodzkie"),
    ("małopolskie", "malopolskie"),
    ("mazowieckie", "mazowieckie"),
    ("opolskie", "opolskie"),
    ("podkarpackie", "podkarpackie"),
    ("podlaskie", "podlaskie"),
    ("pomorskie", "pomorskie"),
    ("śląskie", "slaskie"),
    ("świętokrzyskie", "swietokrzyskie"),
    ("warmińsko-mazurskie", "warminsko-mazurskie"),
    ("wielkopolskie", "wielkopolskie"),
    ("zachodniopomorskie", "zachodniopomorskie"),
)


class Location:
    """One meteo.pl grid point: numeric id plus a human readable name."""
    __slots__ = ("id", "name")

    def __init__(self, id, name):
        self.id = id
        self.name = name

    @classmethod
    def parse(cls, line):
        """'2119 Dobre, pow.radziejowski' -> Location; None for junk lines."""
        parts = line.strip().split(None, 1)
        if not parts or not parts[0].isdigit():
            return None
        return cls(parts[0], parts[1] if len(parts) > 1 else parts[0])

    def __str__(self):
        return f"{self.id} {self.name}"

    def __eq__(self, other):
        return isinstance(other, Location) and self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f"Location({self.id!r}, {self.name!r})"


def _read_locations(path):
    with open(path, encoding="utf-8") as f:
        return [loc for loc in map(Location.parse, f) if loc]


def dump_favourites(locations):
    """Favourites as one config value: '2119 Dobre, pow.radziejowski|462 Kraków'."""
    return "|".join(str(loc) for loc in locations)


def parse_favourites(value):
    return [loc for loc in map(Location.parse, value.split("|")) if loc]


def read_legacy(path=None):
    """Favourites from meteo.ini of versions up to 20.01.05, or None."""
    try:
        path = path or LEGACY_CONFIG_FILE
        return _read_locations(path)
    except (OSError, UnicodeDecodeError):
        return None


def towns(woj_file, woj_dir=WOJ_DIR):
    return _read_locations(os.path.join(woj_dir, woj_file))


def fold(text):
    """Case and diacritics insensitive form: 'Łódź' -> 'lodz'."""
    text = text.lower().replace("ł", "l")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def search_towns(query, woj_dir=WOJ_DIR, limit=200):
    """Towns from every voivodeship whose name (without the county) contains the query.

    Names starting with the query come first."""
    q = fold(query.strip())
    if not q:
        return []
    starts, contains = [], []
    for label, woj_file in VOIVODESHIPS:
        for loc in towns(woj_file, woj_dir):
            town = fold(loc.name.split(",")[0])
            if town.startswith(q):
                starts.append((loc, label))
            elif q in town:
                contains.append((loc, label))
    key = lambda item: fold(item[0].name)
    return (sorted(starts, key=key) + sorted(contains, key=key))[:limit]
