# -*- coding: utf-8 -*-
"""Draw the meteogram (the 'retro' layout of old.meteo.pl) from a Forecast.

Everything is laid out in design pixels for a 1280x720 skin (WIDTH x HEIGHT) and
scaled by `scale` when drawn, so FullHD and 4K get crisp charts. No enigma2 imports."""
import calendar
import math
import time

from . import render
from .meteogram import RAIN, SLEET, SNOW

WIDTH, HEIGHT = 1060, 660
PLOT_X0, PLOT_X1 = 300, 1000          # the time axis
LEGEND_X = 8
TOP = 48                               # first panel
# (key, height in design px); gaps of GAP between panels
PANELS = (("temp", 112), ("precip", 90), ("pressure", 68), ("wind", 72), ("winddir", 18),
          ("cloudbase", 84), ("clouds", 90))
GAP = 6

WHITE, BLACK = (255, 255, 255), (0, 0, 0)
GREY_TEXT, GRID, NIGHT, FRAME = (80, 80, 80), (200, 200, 200), (228, 228, 228), (60, 60, 60)
RED, RED_LIGHT, DARK_RED = (220, 30, 30), (250, 190, 190), (150, 20, 20)
BLUE, BLUE_LIGHT, BLUE_DOT = (40, 90, 230), (190, 210, 250), (60, 60, 200)
GREEN, GREEN_LIGHT = (30, 150, 40), (150, 220, 150)
SNOW_C, SNOW_LIGHT = (50, 100, 240), (170, 190, 250)
SLEET_C, SLEET_LIGHT = (70, 160, 190), (170, 215, 230)
YELLOW, ORANGE = (255, 220, 60), (240, 140, 20)
WIND_C, GUST_C = (40, 100, 200), (220, 40, 40)
PROB_C, HUM_C = (120, 120, 120), (220, 40, 40)
CLOUD_SHADES = ((216, 216, 216), (168, 168, 168), (112, 112, 112), (56, 56, 56))   # high .. very low
BASE_SHADES = ((255, 255, 255), (200, 200, 200), (144, 144, 144), (80, 80, 80), (0, 0, 0))
FOG_C, VIS_C, TOP_C = (240, 150, 30), (240, 130, 20), (220, 40, 40)

DAYS = ("pon", "wt", "śr", "czw", "pt", "sob", "nie")


# --- time helpers ------------------------------------------------------------------
def _last_sunday(year, month):
    last = calendar.monthrange(year, month)[1]
    return last - (calendar.weekday(year, month, last) + 1) % 7


def local_offset(t):
    """Seconds to add to UTC for Polish time (CET/CEST, EU rule) at unix time t."""
    year = time.gmtime(t).tm_year
    start = calendar.timegm((year, 3, _last_sunday(year, 3), 1, 0, 0))
    end = calendar.timegm((year, 10, _last_sunday(year, 10), 1, 0, 0))
    return 7200 if start <= t < end else 3600


def local(t):
    return time.gmtime(t + local_offset(t))


def sun_times(lat, lon, day):
    """(sunrise, sunset) unix times for the UTC day containing `day`, or None (polar)."""
    jd = day / 86400.0 + 2440587.5
    n = round(jd - 2451545.0 + 0.0008)
    j_star = n - lon / 360.0
    m = math.radians((357.5291 + 0.98560028 * j_star) % 360)
    c = 1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    lam = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360)
    transit = 2451545.0 + j_star + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * lam)
    decl = math.asin(math.sin(lam) * math.sin(math.radians(23.44)))
    phi = math.radians(lat)
    cos_w = (math.sin(math.radians(-0.83)) - math.sin(phi) * math.sin(decl)) / (math.cos(phi) * math.cos(decl))
    if not -1 <= cos_w <= 1:
        return None
    w = math.degrees(math.acos(cos_w)) / 360.0
    to_unix = lambda j: (j - 2440587.5) * 86400.0
    return to_unix(transit - w), to_unix(transit + w)


def dms(value, pos, neg):
    hemi = pos if value >= 0 else neg
    value = abs(value)
    d = int(value)
    m = int((value - d) * 60)
    s = int(round(((value - d) * 60 - m) * 60))
    return f"{d}°{m:02d}'{s:02d}\"{hemi}"


# --- axis helpers ------------------------------------------------------------------
def nice_range(values, step, pad=1.0, minimum_span=None):
    vals = [v for v in values if v is not None]
    if not vals:
        return 0.0, step * 2
    lo = math.floor((min(vals) - pad) / step) * step
    hi = math.ceil((max(vals) + pad) / step) * step
    if minimum_span and hi - lo < minimum_span:
        extra = minimum_span - (hi - lo)
        lo -= math.floor(extra / 2 / step) * step
        hi = lo + math.ceil(minimum_span / step) * step
    return lo, hi


def frange(lo, hi, step):
    n = int(round((hi - lo) / step))
    return [lo + i * step for i in range(n + 1)]


def fmt(v):
    return f"{v:g}" if abs(v - round(v)) > 1e-9 else f"{int(round(v))}"


class Piecewise:
    """Monotonic axis through breakpoints spaced evenly (cloud base, visibility)."""

    def __init__(self, points, y0, y1):
        self.points, self.y0, self.y1 = points, y0, y1

    def __call__(self, v):
        p = self.points
        v = min(max(v, p[0]), p[-1])
        for i in range(len(p) - 1):
            if v <= p[i + 1]:
                frac = (i + (v - p[i]) / (p[i + 1] - p[i])) / (len(p) - 1)
                return self.y1 - frac * (self.y1 - self.y0)
        return self.y0


class Chart:
    def __init__(self, forecast, scale=1.0):
        self.f = forecast
        self.scale = scale
        self.canvas = render.Canvas(self.p(WIDTH), self.p(HEIGHT))
        self.small = render.font(round(9 * scale))
        self.normal = render.font(round(11 * scale))
        self.big = render.font(round(13 * scale))
        self.thin = max(1, int(round(scale)))
        self.thick = max(2, int(round(2 * scale)))
        times = forecast.times()
        self.t0 = times[0] - forecast.interval     # the run hour: left edge
        self.t1 = times[-1]
        self.xs = [self.xpos(t) for t in times]
        self.hour_w = self.xs[1] - self.xs[0]

    # --- geometry -------------------------------------------------------------------
    def p(self, v):
        return int(round(v * self.scale))

    def xpos(self, t):
        x0, x1 = self.p(PLOT_X0), self.p(PLOT_X1)
        return x0 + (t - self.t0) / float(self.t1 - self.t0) * (x1 - x0)

    def linear(self, lo, hi, y0, y1):
        """Value -> pixel y for a panel spanning y0 (top) .. y1 (bottom)."""
        span = float(hi - lo) or 1.0
        return lambda v: y1 - (v - lo) / span * (y1 - y0)

    # --- the whole picture ----------------------------------------------------------
    def draw(self):
        y = self.p(TOP)
        rects = {}
        for key, height in PANELS:
            rects[key] = (y, y + self.p(height))
            y += self.p(height + GAP)
        self.bottom = rects["clouds"][1]
        self.header()
        for key, (y0, y1) in rects.items():
            self.background(y0, y1, key != "winddir")
        self.time_axes()
        self.temperature(*rects["temp"])
        self.precipitation(*rects["precip"])
        self.pressure(*rects["pressure"])
        self.wind(*rects["wind"])
        self.wind_direction(*rects["winddir"])
        self.cloud_base(*rects["cloudbase"])
        self.clouds(*rects["clouds"])
        self.footer()
        return self.canvas

    def png(self):
        return self.draw().png()

    # --- common parts ---------------------------------------------------------------
    def background(self, y0, y1, nights=True):
        c = self.canvas
        x0, x1 = self.p(PLOT_X0), self.p(PLOT_X1)
        if nights:
            for sunset, sunrise in self.nights():
                c.fill(int(self.xpos(max(sunset, self.t0))), y0, int(round(self.xpos(min(sunrise, self.t1)))), y1, NIGHT)
        for t, _loc, midnight in self.marks():
            x = int(round(self.xpos(t)))
            if midnight:
                c.vline(x, y0, y1, FRAME, self.thin)
            else:
                c.dotted_vline(x, y0, y1, GRID, self.thin, 2 * self.thin)
        c.vline(x0, y0, y1, FRAME, self.thin)
        c.vline(x1 - self.thin, y0, y1, FRAME, self.thin)
        c.hline(x0, x1, y0, FRAME, self.thin)
        c.hline(x0, x1, y1 - self.thin, FRAME, self.thin)

    def nights(self):
        out = []
        day = (self.t0 // 86400) * 86400 - 86400
        while day < self.t1 + 86400:
            sun = sun_times(self.f.lat, self.f.lon, day + 43200)
            nxt = sun_times(self.f.lat, self.f.lon, day + 86400 + 43200)
            if sun and nxt:
                out.append((sun[1], nxt[0]))
            day += 86400
        return [(a, b) for a, b in out if b > self.t0 and a < self.t1]

    def marks(self):
        """[(unix time, local struct_time, is_midnight)] every 6 hours of local time."""
        out = []
        t = self.t0 - self.t0 % 3600
        while t <= self.t1:
            loc = local(t)
            if loc.tm_hour % 6 == 0 and t >= self.t0:
                out.append((t, loc, loc.tm_hour == 0))
            t += 3600
        return out

    def header(self):
        c, f = self.canvas, self.f
        y_info = self.p(13)
        sun = sun_times(f.lat, f.lon, f.start)
        if sun:
            rise, sset = local(sun[0]), local(sun[1])
            zone = "CEST" if local_offset(f.start) == 7200 else "CET"
            c.text(self.p(PLOT_X0), y_info, f"wschód słońca {rise.tm_hour:02d}:{rise.tm_min:02d}   "
                   f"zachód {sset.tm_hour:02d}:{sset.tm_min:02d} {zone}", self.normal, BLUE)
        c.text((self.p(PLOT_X0) + self.p(PLOT_X1)) // 2, y_info, f"{dms(f.lat, 'N', 'S')}  {dms(f.lon, 'E', 'W')}",
               self.normal, BLUE, align="center")
        if f.row is not None and f.col is not None:
            c.text(self.p(PLOT_X1), y_info, f"siatka UM: wiersz {f.row}, kolumna {f.col}", self.normal, GREY_TEXT, align="right")
        c.text(self.p(LEGEND_X), y_info, "UM 4 km, 60 h", self.big, BLACK)
        c.text(self.p(LEGEND_X), self.p(28), f"start {f.run}", self.normal, GREY_TEXT)
        c.text(self.p(LEGEND_X), self.p(41), "szare pasma: noc", self.small, GREY_TEXT)

    def time_axes(self):
        c = self.canvas
        y_days, y_local = self.p(28), self.p(40)
        y_utc, y_days2 = self.bottom + self.p(12), self.bottom + self.p(24)
        zone = "CEST" if local_offset(self.f.start) == 7200 else "CET"
        c.text(self.p(PLOT_X0) - self.p(4), y_local, zone, self.small, BLACK, align="right")
        c.text(self.p(PLOT_X1) + self.p(4), y_local, zone, self.small, BLACK)
        c.text(self.p(PLOT_X0) - self.p(4), y_utc, "UTC", self.small, BLACK, align="right")
        c.text(self.p(PLOT_X1) + self.p(4), y_utc, "UTC", self.small, BLACK)
        for t, loc, midnight in self.marks():
            x = self.xpos(t)
            c.text(x, y_local, f"{loc.tm_hour:02d}", self.small, BLACK, align="center")
            c.text(x, y_utc, f"{time.gmtime(t).tm_hour:02d}", self.small, BLACK, align="center")
        # day names centred on each local day inside the range
        day_start = self.t0 - (self.t0 + local_offset(self.t0)) % 86400
        while day_start < self.t1:
            day_end = day_start + 86400
            a, b = max(day_start, self.t0), min(day_end, self.t1)
            if b - a >= 4 * 3600:
                loc = local(day_start + 43200)
                label = f"{DAYS[loc.tm_wday]}, {loc.tm_mday:02d}.{loc.tm_mon:02d}"
                xm = (self.xpos(a) + self.xpos(b)) / 2
                c.text(xm, y_days, label, self.normal, BLACK, align="center")
                c.text(xm, y_days2, label, self.normal, BLACK, align="center")
            day_start = day_end

    def footer(self):
        c = self.canvas
        y = self.p(HEIGHT) - self.p(5)
        c.text(self.p(PLOT_X0), y, "dane: meteo.pl (ICM, Uniwersytet Warszawski), model UM", self.small, GREY_TEXT)
        c.text(self.p(PLOT_X1), y, "wykres: UM Meteo.pl dla enigmy2", self.small, GREY_TEXT, align="right")

    def axis_left(self, y_of, ticks, grid=True, colour=BLACK):
        c, x0, x1 = self.canvas, self.p(PLOT_X0), self.p(PLOT_X1)
        for v in ticks:
            y = int(round(y_of(v)))
            c.hline(x0 - self.p(3), x0, y, FRAME, self.thin)
            c.text(x0 - self.p(6), y, fmt(v), self.small, colour, align="right", valign="middle")
            if grid and v != ticks[0]:
                c.dotted_hline(x0, x1, y, GRID, self.thin, 2 * self.thin)

    def axis_right(self, y_of, ticks, labels=None, colour=BLACK, unit=None, y0=None):
        c, x1 = self.canvas, self.p(PLOT_X1)
        for i, v in enumerate(ticks):
            y = int(round(y_of(v)))
            c.hline(x1, x1 + self.p(3), y, FRAME, self.thin)
            c.text(x1 + self.p(6), y, labels[i] if labels else fmt(v), self.small, colour, valign="middle")
        if unit:
            c.text(x1 - self.p(5), y0 + self.p(9), unit, self.small, colour, align="right", valign="middle")

    def legend(self, y, items, title=None):
        """Legend column rows: [(marker, colour, text)], marker in line/dash/dots/bar/dot/tri/none."""
        c = self.canvas
        x, line_h = self.p(LEGEND_X), self.p(12)
        if title:
            c.text(x, y + self.p(11), title, self.big, BLACK)
            y += self.p(15)
        for marker, colour, text in items:
            ym = y + self.p(6)
            mx0, mx1 = x, x + self.p(22)
            if marker == "line":
                c.hline(mx0, mx1, ym, colour, self.thick)
            elif marker == "thin":
                c.hline(mx0, mx1, ym, colour, self.thin)
            elif marker == "dash":
                c.line(mx0, ym, mx1, ym, colour, self.thin, dash=(3 * self.thin, 2 * self.thin))
            elif marker == "dots":
                for dx in range(0, mx1 - mx0 + 1, self.p(6)):
                    c.disc(mx0 + dx, ym, self.thin, colour)
            elif marker == "bar":
                c.fill(mx0, ym - self.p(5), mx1, ym + self.p(5), colour)
            elif marker == "dot":
                c.disc((mx0 + mx1) // 2, ym, max(2, self.p(2.5)), colour, outline=GREY_TEXT if colour == WHITE else None)
            elif marker == "tri":
                m = (mx0 + mx1) // 2
                c.polygon([(m - self.p(5), ym + self.p(4)), (m + self.p(5), ym + self.p(4)), (m, ym - self.p(4))], colour)
            elif marker == "whisker":
                m = (mx0 + mx1) // 2
                c.vline(m, ym - self.p(5), ym + self.p(5), colour, self.thin)
                c.hline(m - self.p(2), m + self.p(2), ym - self.p(5), colour, self.thin)
                c.hline(m - self.p(2), m + self.p(2), ym + self.p(5), colour, self.thin)
            c.text(x + self.p(28), ym, text, self.normal, BLACK, valign="middle")
            y += line_h
        return y

    def series(self, name):
        return self.f[name]

    def bars(self, values, y_of, y_base, colour, cap=None, columns=None):
        """One bar per hour, from y_base up to the value; cap -> overflow marker."""
        c = self.canvas
        w = max(1, int(self.hour_w) - self.thin)
        for i, v in enumerate(values):
            if v is None or v <= 0 or (columns and not columns[i]):
                continue
            x1 = int(round(self.xs[i]))
            x0 = x1 - w
            top = int(round(y_of(min(v, cap) if cap else v)))
            c.fill(x0, top, x1, y_base, colour)
            if cap and v > cap:
                m = (x0 + x1) // 2
                c.polygon([(x0, top + self.p(5)), (x1, top + self.p(5)), (m, top - self.p(1))], RED)

    # --- panels -----------------------------------------------------------------------
    def temperature(self, y0, y1):
        c, f = self.canvas, self.f
        names = ("airtmp_point", "airtmp_min", "airtmp_max", "grdtmp_min", "grdtmp_max", "dwptmp_point",
                 "wchill_point", "wchill_min", "wchill_max")
        allv = [v for n in names for v in f[n] if v is not None]
        lo, hi = nice_range(allv, 5, pad=1.0, minimum_span=15)
        step = 5 if hi - lo <= 35 else 10
        y_of = self.linear(lo, hi, y0 + self.p(4), y1 - self.p(4))
        ys = lambda name: [None if v is None else y_of(v) for v in f[name]]
        self.axis_left(y_of, frange(lo, hi, step))
        self.axis_right(y_of, frange(lo, hi, step))
        if lo < 0 < hi:
            c.hline(self.p(PLOT_X0), self.p(PLOT_X1), int(round(y_of(0))), FRAME, self.thin)
        # ground temperature min..max whiskers
        for i, (a, b) in enumerate(zip(f["grdtmp_min"], f["grdtmp_max"])):
            if a is not None and b is not None:
                x = int(round(self.xs[i]))
                c.vline(x, int(round(y_of(b))), int(round(y_of(a))), DARK_RED, self.thin)
        self.band(ys("wchill_min"), ys("wchill_max"), BLUE_LIGHT)
        self.band(ys("airtmp_min"), ys("airtmp_max"), RED_LIGHT)
        c.polyline(self.xs, ys("wchill_point"), BLUE, self.thick)
        c.polyline(self.xs, ys("airtmp_point"), RED, self.thick)
        for x, y in zip(self.xs, ys("dwptmp_point")):
            if y is not None:
                c.disc(x, y, self.thin, BLUE_DOT)
        self.legend(y0, [("line", RED, "temperatura (pasmo: min–max)"), ("line", BLUE, "odczuwalna (min–max)"),
                         ("dots", BLUE_DOT, "punkt rosy"), ("whisker", DARK_RED, "temp. gruntu min–max")],
                    "Temperatura [°C]")

    def band(self, ys_low, ys_high, colour):
        xs, lo, hi = [], [], []
        for x, a, b in zip(self.xs, ys_low, ys_high):
            if a is not None and b is not None:
                xs.append(x)
                lo.append(a)
                hi.append(b)
            elif len(xs) > 1:
                self.canvas.band(xs, lo, hi, colour)
                xs, lo, hi = [], [], []
        if len(xs) > 1:
            self.canvas.band(xs, lo, hi, colour)

    def precipitation(self, y0, y1):
        c, f = self.canvas, self.f
        strip = self.p(10)                       # storm markers at the top
        top, bottom = y0 + strip, y1 - self.thin
        peak = max([v for v in f["pcpttl_max"] + f["pcpttl_aver"] if v is not None] or [0])
        cap = next((v for v in (1, 2, 5, 10, 20) if v >= peak), 20)
        y_of = self.linear(0, cap, top, bottom)
        self.axis_left(y_of, frange(0, cap, {1: 0.25, 2: 0.5, 5: 1, 10: 2, 20: 5}[cap]))
        y_pct = self.linear(0, 100, top, bottom)
        self.axis_right(y_pct, [0, 25, 50, 75, 100], colour=HUM_C, unit="%", y0=y0 + strip)
        kinds = [int(round(t)) if t is not None else 0 for t in f["pcpttl_type_max"]]
        for kind, light, dark in ((RAIN, GREEN_LIGHT, GREEN), (SNOW, SNOW_LIGHT, SNOW_C), (SLEET, SLEET_LIGHT, SLEET_C)):
            cols = [k == kind for k in kinds]
            self.bars(f["pcpttl_max"], y_of, bottom, light, cap, cols)
            self.bars(f["pcpttl_aver"], y_of, bottom, dark, cap, cols)
        # whatever has an amount but no type: treat as rain
        untyped = [(k == 0 and a is not None and a > 0) for k, a in zip(kinds, f["pcpttl_aver"])]
        self.bars(f["pcpttl_max"], y_of, bottom, GREEN_LIGHT, cap, untyped)
        self.bars(f["pcpttl_aver"], y_of, bottom, GREEN, cap, untyped)
        for i, (storm, flash) in enumerate(zip(f["storm_max"], f["flash_max"])):
            x = int(round(self.xs[i] - self.hour_w / 2))
            if storm and storm > 0:
                c.polygon([(x - self.p(4), y0 + strip - self.p(2)), (x + self.p(4), y0 + strip - self.p(2)), (x, y0 + self.p(2))], YELLOW)
            if flash and flash > 0:
                c.polygon([(x - self.p(2), y0 + strip - self.p(3)), (x + self.p(2), y0 + strip - self.p(3)), (x, y0 + self.p(4))], RED)
        c.polyline(self.xs, [None if v is None else y_pct(v) for v in f["pcpttlprob_point"]], PROB_C, self.thin, dash=(3 * self.thin, 3 * self.thin))
        c.polyline(self.xs, [None if v is None else y_pct(v) for v in f["realhum_aver"]], HUM_C, self.thick)
        self.legend(y0, [("bar", GREEN, "deszcz (ciemniej: średni, jaśniej: max)"), ("bar", SNOW_C, "śnieg"),
                         ("bar", SLEET_C, "deszcz ze śniegiem"), ("tri", YELLOW, "burza   (czerwony: wyładowania)"),
                         ("line", HUM_C, "wilgotność względna [%]"), ("dash", PROB_C, "prawdopodobieństwo opadu [%]")],
                    "Opad [mm/h]")

    def pressure(self, y0, y1):
        c, f = self.canvas, self.f
        hpa = [None if v is None else v / 100.0 for v in f["slpres_point"]]
        lo, hi = nice_range(hpa, 5, pad=1.0, minimum_span=10)
        step = 5 if hi - lo <= 30 else 10
        y_of = self.linear(lo, hi, y0 + self.p(4), y1 - self.thin)
        ticks = frange(lo, hi, step)
        self.axis_left(y_of, ticks)
        self.axis_right(y_of, ticks, [f"{v * 0.750062:.0f}" for v in ticks], unit="mmHg", y0=y0)
        ys = [None if v is None else y_of(v) for v in hpa]
        xs, seg = [], []
        for x, y in zip(self.xs, ys):
            if y is not None:
                xs.append(x)
                seg.append(y)
        if len(xs) > 1:
            c.area(xs, seg, y1 - self.thin, YELLOW)
        c.polyline(self.xs, ys, BLACK, self.thick)
        self.legend(y0, [("line", BLACK, "zredukowane do poziomu morza"), ("none", BLACK, "prawa oś: mmHg")],
                    "Ciśnienie [hPa]")

    def wind(self, y0, y1):
        c, f = self.canvas, self.f
        speeds = [v for v in f["wind10_sd_true_prev_point"] + f["wind_gust_max"] if v is not None]
        hi = max(10, int(math.ceil(max(speeds or [0]) / 5.0)) * 5)
        step = 5 if hi <= 25 else 10
        y_of = self.linear(0, hi, y0 + self.p(4), y1 - self.thin)
        ticks = frange(0, hi, step)
        self.axis_left(y_of, ticks)
        self.axis_right(y_of, ticks, [f"{v * 3.6:.0f}" for v in ticks], unit="km/h", y0=y0)
        ys = [None if v is None else y_of(v) for v in f["wind10_sd_true_prev_point"]]
        xs, seg = [], []
        for x, y in zip(self.xs, ys):
            if y is not None:
                xs.append(x)
                seg.append(y)
        if len(xs) > 1:
            c.area(xs, seg, y1 - self.thin, WIND_C)
        c.polyline(self.xs, [None if v is None else y_of(v) for v in f["wind_gust_max"]], GUST_C, self.thin,
                   dash=(4 * self.thin, 3 * self.thin))
        self.legend(y0, [("bar", WIND_C, "prędkość średnia"), ("dash", GUST_C, "maksymalne porywy"),
                         ("none", BLACK, "prawa oś: km/h")], "Wiatr na 10 m [m/s]")

    def wind_direction(self, y0, y1):
        c, f = self.canvas, self.f
        ym = (y0 + y1) // 2
        length = (y1 - y0) * 0.42
        for i, d in enumerate(f["wind10_dr_deg_true_prev_point"]):
            if d is None or i % 2:
                continue
            a = math.radians(d + 180)              # the arrow points where the wind blows to
            dx, dy = math.sin(a) * length, -math.cos(a) * length
            x = self.xs[i] - self.hour_w / 2
            x0, y0a, x1, y1a = x - dx, ym - dy, x + dx, ym + dy
            c.line(x0, y0a, x1, y1a, WIND_C, self.thin)
            for side in (2.6, -2.6):
                hx = x1 - math.sin(a + side) * length * 0.6
                hy = y1a + math.cos(a + side) * length * 0.6
                c.line(x1, y1a, hx, hy, WIND_C, self.thin)
        c.text(self.p(PLOT_X1) + self.p(6), ym, "N u góry", self.small, BLACK, valign="middle")
        c.text(self.p(LEGEND_X), ym, "Kierunek wiatru (strzałka: dokąd wieje, N u góry)", self.normal, BLACK, valign="middle")

    def cloud_base(self, y0, y1):
        c, f = self.canvas, self.f
        top, bottom = y0 + self.p(4), y1 - self.thin
        y_km = Piecewise((0, 0.5, 1, 2, 5, 7, 15), top, bottom)
        self.axis_left(y_km, (0, 0.5, 1, 2, 5, 7, 15))
        y_vis = Piecewise((0, 1, 5, 10, 20, 50), top, bottom)
        self.axis_right(y_vis, (0.2, 1, 5, 10, 20, 50), ["0.2", "1", "5", "10", "20", "50"], colour=VIS_C,
                        unit="widzialność km", y0=y0)
        c.polyline(self.xs, [None if v is None else y_vis(v / 1000.0) for v in f["visibl_min"]], VIS_C, self.thick)
        r = max(2, self.p(2.5))
        for name, shade in zip(("cldbse01", "cldbse25", "cldbse45", "cldbse65", "cldbse79"), BASE_SHADES):
            for x, v in zip(self.xs, f[name]):
                if v is not None and v >= 0:
                    c.disc(x, y_km(v), r, shade, outline=GREY_TEXT if shade == WHITE else None)
        for x, v in zip(self.xs, f["cldtop"]):
            if v is not None and v > 0:
                c.disc(x, y_km(v), r, TOP_C)
        self.legend(y0, [("dot", TOP_C, "wierzchołek chmur"),
                         ("dot", BASE_SHADES[4], "podstawa chmur, pokrycie > 7.9 okt."),
                         ("dot", BASE_SHADES[2], "> 4.5 okt.   (biały: > 0.1, jasny: > 2.5)"),
                         ("dot", BASE_SHADES[3], "> 6.5 okt."),
                         ("line", VIS_C, "widzialność [km], prawa oś")], "Podstawa chmur [km]")

    def clouds(self, y0, y1):
        c, f = self.canvas, self.f
        top, bottom = y0 + self.p(4), y1 - self.thin
        y_of = self.linear(0, 1, top, bottom)
        self.axis_left(lambda v: y_of(v / 8.0), [0, 2, 4, 6, 8])
        self.axis_right(y_of, [0, 0.25, 0.5, 0.75, 1.0], unit="frakcja", y0=y0)
        for name, shade in zip(("cldhigh_aver", "cldmed_aver", "cldlow_aver", "cldvlow_aver"), CLOUD_SHADES):
            xs, seg = [], []
            for x, v in zip(self.xs, f[name]):
                if v is not None:
                    xs.append(x)
                    seg.append(y_of(min(max(v, 0.0), 1.0)))
            if len(xs) > 1:
                c.area(xs, seg, bottom, shade)
        self.bars(f["fog_max"], y_of, bottom, FOG_C, cap=1.0)
        c.polyline(self.xs, [None if v is None else y_of(min(max(v, 0.0), 1.0)) for v in f["cldtot_aver"]], BLACK, self.thin,
                   dash=(2 * self.thin, 2 * self.thin))
        self.legend(y0, [("bar", CLOUD_SHADES[0], "wysokie"), ("bar", CLOUD_SHADES[1], "średnie"),
                         ("bar", CLOUD_SHADES[2], "niskie"), ("bar", CLOUD_SHADES[3], "bardzo niskie"),
                         ("bar", FOG_C, "mgła (frakcja)"), ("dash", BLACK, "zachmurzenie całkowite")],
                    "Zachmurzenie [okt.]")


def placeholder(title, subtitle, scale=1.5, colour=BLUE):
    """Empty panel frames with a message: loading.png / error.png (tools/build_placeholders.py)."""
    p = lambda v: int(round(v * scale))
    c = render.Canvas(p(WIDTH), p(HEIGHT))
    y = p(TOP)
    for _key, height in PANELS:
        c.fill(p(PLOT_X0), y, p(PLOT_X1), y + p(height), (246, 246, 246))
        for x in range(p(PLOT_X0), p(PLOT_X1), p(58)):
            c.vline(x, y, y + p(height), (232, 232, 232), max(1, p(1)))
        y += p(height + GAP)
    c.text(p(WIDTH) // 2, p(HEIGHT) // 2 - p(14), title, render.font(round(13 * scale * 2)), colour, align="center", valign="middle")
    c.text(p(WIDTH) // 2, p(HEIGHT) // 2 + p(22), subtitle, render.font(round(13 * scale)), GREY_TEXT, align="center", valign="middle")
    return c.png()


def render_png(forecast, scale=1.0):
    """Forecast -> (PNG bytes, (width, height))."""
    chart = Chart(forecast, scale)
    png = chart.png()
    return png, (chart.canvas.width, chart.canvas.height)
