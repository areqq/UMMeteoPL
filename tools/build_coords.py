#!/usr/bin/env python3
"""Rebuild coords.tsv: meteo.pl location id -> WGS84 latitude, longitude.

The new meteo.pl API (meteogram.py) takes a point, not the location id the old
site used, so every catalogue entry (woj/*) needs coordinates. They come from
the official register of geographical names, PRNG (GUGiK WFS, EPSG:2180): the
locality with the same name whose commune id starts with the county TERYT code
of the entry (teryt.tsv). Towns win over villages, villages over hamlets.

    python3 tools/build_coords.py [--cache DIR]   (from the plugin directory, needs network)
"""
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
storage = __import__(os.path.basename(ROOT) + ".storage", fromlist=["x"])

WFS = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRNG/WFS/GeographicalNames"
LAYER = "ms:M1_UrzedoweNazwyMiejscowosci"
NS = {"ms": "http://mapserver.gis.umn.edu/mapserver", "gml": "http://www.opengis.net/gml/3.2",
      "wfs": "http://www.opengis.net/wfs/2.0"}
BATCH = 40
LIKE_BATCH = 12      # PropertyIsLike filters are longer; the server limits the URL
RANK = {"miasto": 0, "wieś": 1, "osada": 2, "kolonia": 3, "osiedle": 3, "przysiółek": 4,
        "część miasta": 5, "część wsi": 6}
# catalogue names that are commune names, not locality names (-> the commune seat), typos
# and renamed towns (catalogue name -> PRNG name or wildcard pattern)
ALIASES = {
    "Igołomia-Wawrzeńczyce": "Wawrzeńczyce", "Jerzmanowice-Przeginia": "Jerzmanowice",
    "Kocmyrzów-Luborzyca": "Luborzyca", "Bystra-Sidzina": "Bystra", "Radziechowy-Wieprz": "Wieprz",
    "Sitkówka-Nowiny": "Nowiny", "Słupia Konecka": "Słupia", "Stary Dzikowiec": "Dzikowiec",
    "Skarżysko-Kościelne": "Skarżysko Kościelne", "Świeradów Zdrój": "Świeradów-Zdrój",
    "Kozłow": "Kozłów", "Stargard Szczeciński": "Stargard", "Lubicz": "Lubicz Dolny",
    "Szelków": "Stary Szelków",
}
# ids resolved by hand: id -> (lat, lon)
EXTRA = {}


def puwg1992_to_wgs84(northing, easting):
    """EPSG:2180 (Transverse Mercator on GRS80, lon0 19E, k0 0.9993) -> (lat, lon) degrees."""
    a, f = 6378137.0, 1 / 298.257222101
    k0, lon0, fe, fn = 0.9993, math.radians(19.0), 500000.0, -5300000.0
    e2 = f * (2 - f)
    n = f / (2 - f)
    # meridian arc -> footpoint latitude (Krüger series)
    A = a / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    xi = (northing - fn) / (k0 * A)
    eta = (easting - fe) / (k0 * A)
    beta = (n / 2 - 2 * n ** 2 / 3 + 37 * n ** 3 / 96,
            n ** 2 / 48 + n ** 3 / 15,
            17 * n ** 3 / 480)
    xi_p, eta_p = xi, eta
    for j, b in enumerate(beta, 1):
        xi_p -= b * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        eta_p -= b * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
    chi = math.asin(math.sin(xi_p) / math.cosh(eta_p))
    delta = (2 * n - 2 * n ** 2 / 3 - 2 * n ** 3,
             7 * n ** 2 / 3 - 8 * n ** 3 / 5,
             56 * n ** 3 / 15)
    lat = chi
    for j, d in enumerate(delta, 1):
        lat += d * math.sin(2 * j * chi)
    lon = lon0 + math.atan2(math.sinh(eta_p), math.cos(xi_p))
    return math.degrees(lat), math.degrees(lon)


def wfs_get(names, cache_dir, batch_no, like=False):
    tag = "like" if like else "batch"
    path = os.path.join(cache_dir, f"{tag}{batch_no:03d}.xml") if cache_dir else None
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    if like:
        ors = "".join('<PropertyIsLike wildCard="*" singleChar="." escapeChar="!">'
                      f"<PropertyName>NAZWAGLOWNA</PropertyName><Literal>{n}*</Literal></PropertyIsLike>" for n in names)
    else:
        ors = "".join(f"<PropertyIsEqualTo><PropertyName>NAZWAGLOWNA</PropertyName><Literal>{n}</Literal>"
                      "</PropertyIsEqualTo>" for n in names)
    query = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": LAYER,
             "COUNT": 5000, "FILTER": f"<Filter><Or>{ors}</Or></Filter>"}
    with urlopen(WFS + "?" + urlencode(query), timeout=300) as r:
        raw = r.read()
    if path:
        with open(path, "wb") as f:
            f.write(raw)
    return raw


def parse(raw):
    """-> [(name, county4, kind, commune, lat, lon)]"""
    root = ET.fromstring(raw)
    if root.get("numberReturned") == "5000" or 'next="' in raw[:3000].decode("utf-8", "replace"):
        sys.exit("WFS page overflow - lower BATCH")
    out = []
    for m in root.iterfind("wfs:member/ms:M1_UrzedoweNazwyMiejscowosci", NS):
        pos = m.find("ms:msGeometry/gml:Point/gml:pos", NS).text.split()
        lat, lon = puwg1992_to_wgs84(float(pos[0]), float(pos[1]))
        out.append((m.findtext("ms:NAZWAGLOWNA", "", NS), m.findtext("ms:IDENTYFIKATORGMINY", "", NS)[:4],
                    m.findtext("ms:RODZAJOBIEKTU", "", NS), m.findtext("ms:GMINA", "", NS), lat, lon))
    return out


def main():
    cache_dir = None
    if "--cache" in sys.argv:
        cache_dir = sys.argv[sys.argv.index("--cache") + 1]
        os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(ROOT, "teryt.tsv"), encoding="utf-8") as f:
        counties = dict(line.split() for line in f if line[0].isdigit())
    entries = [(loc, label) for label, woj in storage.VOIVODESHIPS for loc in storage.towns(woj)]
    town = lambda loc: loc.name.split(",")[0].strip()
    names = sorted({ALIASES.get(town(loc), town(loc)) for loc, _ in entries})
    found = {}
    for i in range(0, len(names), BATCH):
        batch = names[i:i + BATCH]
        for name, county, kind, commune, lat, lon in parse(wfs_get(batch, cache_dir, i // BATCH)):
            # the commune seat usually sits in the commune of the same name: it wins over a
            # namesake village elsewhere in the county
            found.setdefault((name, county), []).append((RANK.get(kind, 9), 0 if commune.startswith(name) else 1, kind, lat, lon))
        print(f"{i + len(batch)}/{len(names)} names", file=sys.stderr)

    table, missing, ambiguous, fallback = dict(EXTRA), [], [], []
    for loc, label in entries:
        if loc.id in table:
            continue
        key = (ALIASES.get(town(loc), town(loc)), counties.get(loc.id, "?"))
        hits = sorted(found.get(key, []))
        if not hits:
            missing.append((loc, label, key))
            continue
        if len(hits) > 1 and hits[0][:2] == hits[1][:2]:
            ambiguous.append(f"{loc.id}\t{loc.name}\t{label}\t" + "; ".join(f"{h[2]} {h[3]:.4f},{h[4]:.4f}" for h in hits))
        table[loc.id] = (hits[0][3], hits[0][4])

    # second pass for the rest: the catalogue entry is the rural commune around a city with
    # county rights ("Legnica, pow.legnicki") - the city of that name in the voivodeship; or
    # the locality is named differently ("Godziszów Pierwszy", "Rutki-Kossaki") - same
    # county, catalogue name plus a word
    like = {}
    names = sorted({key[0] for _loc, _label, key in missing})
    for i in range(0, len(names), LIKE_BATCH):
        for name, county, kind, commune, lat, lon in parse(wfs_get(names[i:i + LIKE_BATCH], cache_dir, i // LIKE_BATCH, like=True)):
            like.setdefault(county, []).append((RANK.get(kind, 9), 0 if commune.startswith(name) else 1, len(name), name, kind, lat, lon))
    still = []
    for loc, label, (name, county) in missing:
        hits = sorted(h for c, hs in like.items() if c[:2] == county[:2] for h in hs if h[3] == name and h[4] == "miasto")
        if not hits:
            hits = sorted(h for h in like.get(county, []) if h[3].startswith(name) and h[3][len(name):len(name) + 1] in " -")
        if not hits:
            still.append(f"{loc.id}\t{loc.name}\t{label}\t{county}")
            continue
        fallback.append(f"{loc.id}\t{loc.name}\t{label}\t-> {hits[0][3]} ({hits[0][4]}) {hits[0][5]:.4f},{hits[0][6]:.4f}")
        table[loc.id] = (hits[0][5], hits[0][6])
    missing = still
    if ambiguous:
        print("AMBIGUOUS (first taken):\n" + "\n".join(ambiguous), file=sys.stderr)
    if fallback:
        print("RESOLVED BY FALLBACK:\n" + "\n".join(fallback), file=sys.stderr)
    if missing:
        sys.exit("no coordinates for:\n" + "\n".join(missing))
    with open(os.path.join(ROOT, "zig", "src", "coords.tsv"), "w", encoding="utf-8") as f:
        f.write("# meteo.pl id -> latitude, longitude (PRNG, GUGiK); generated by tools/build_coords.py\n")
        f.writelines(f"{i}\t{table[i][0]:.4f}\t{table[i][1]:.4f}\n" for i in sorted(table, key=int))
    print(f"{len(table)} locations", file=sys.stderr)


if __name__ == "__main__":
    main()
