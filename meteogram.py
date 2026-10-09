# -*- coding: utf-8 -*-
"""meteo.pl UM meteogram: URLs and page parsing. No enigma2 imports."""
import html
import re
import struct
from urllib.request import Request, urlopen

BASE = "https://www.meteo.pl/um"
PAGE_URL = BASE + "/php/meteorogram_id_um.php?ntype=0u&id={id}"
PICTURE_URL = BASE + "/metco/mgram_pict.php?ntype=0u&fdate={date}&row={row}&col={col}&lang=pl"
PAGE_ENCODING = "iso-8859-2"
USER_AGENT = "UMMeteoPL (enigma2 plugin)"
TIMEOUT = 10

# The chart (and the legend in left.png) is this tall at 1:1. The server currently
# prepends an advertising banner (630x780 picture), so only the bottom part is shown.
CHART_WIDTH = 630
CHART_HEIGHT = 660

_RE_DATE = re.compile(r'fcstdate\s*=\s*"(\d{10})"')
_RE_X = re.compile(r"act_x\s*=\s*(\d+)")
_RE_Y = re.compile(r"act_y\s*=\s*(\d+)")
_RE_NAME = re.compile(r"id='model_napis'.*?<font[^>]*>(.*?)</font>", re.S)


class Forecast:
    __slots__ = ("date", "row", "col", "place")

    def __init__(self, date, row, col, place):
        self.date = date      # model run, YYYYMMDDHH (UTC)
        self.row = row
        self.col = col
        self.place = place    # 'Dobre, pow.radziejowski, woj.kujawsko-pomorskie'

    @property
    def picture_url(self):
        return PICTURE_URL.format(date=self.date, row=self.row, col=self.col)

    @property
    def run(self):
        d = self.date
        return f"{d[6:8]}.{d[4:6]}.{d[0:4]} {d[8:10]} UTC"


class ParseError(Exception):
    pass


def parse_page(raw):
    """Meteogram HTML page (bytes) -> Forecast. Raises ParseError."""
    text = raw.decode(PAGE_ENCODING, "replace")
    date, x, y = _RE_DATE.search(text), _RE_X.search(text), _RE_Y.search(text)
    if not (date and x and y):
        raise ParseError("Brak meteogramu dla tej lokalizacji")
    name = _RE_NAME.search(text)
    place = " ".join(html.unescape(name.group(1)).split()) if name else ""
    return Forecast(date.group(1), y.group(1), x.group(1), place)


def png_size(raw):
    """(width, height) from the PNG IHDR chunk; raises ParseError otherwise."""
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise ParseError("Serwer nie zwrócił obrazka PNG")
    return struct.unpack(">II", raw[16:24])


def http_get(url, timeout=TIMEOUT):
    """Blocking GET -> bytes. Run it off the reactor thread."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch(location_id, get=http_get):
    """Blocking: page + picture -> (Forecast, png bytes, (w, h))."""
    forecast = parse_page(get(PAGE_URL.format(id=location_id)))
    png = get(forecast.picture_url)
    return forecast, png, png_size(png)
