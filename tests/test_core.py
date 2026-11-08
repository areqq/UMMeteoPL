# -*- coding: utf-8 -*-
"""Host-side tests: python3 -m unittest discover -s tests -t ."""
import calendar
import json
import os
import struct
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT.parent))
PKG = ROOT.name

meteogram = __import__(f"{PKG}.meteogram", fromlist=["x"])
storage = __import__(f"{PKG}.storage", fromlist=["x"])
alerts = __import__(f"{PKG}.alerts", fromlist=["x"])
update = __import__(f"{PKG}.update", fromlist=["x"])


chart = __import__(f"{PKG}.chart", fromlist=["x"])
render = __import__(f"{PKG}.render", fromlist=["x"])

RUN = 1793448000        # 31.10.2026 12 UTC, the run of the Warszawa fixture


def forecast():
    raw = (FIX / "um4_60_warszawa_2026-10-31.json").read_bytes()
    return meteogram.parse_forecast(raw, RUN, 52.2298, 21.0117)


class ApiTest(unittest.TestCase):
    """Real responses of devmgramapi.meteo.pl captured 2026-10-31."""

    def test_available_newest_first(self):
        runs = meteogram.parse_available((FIX / "available_2026-10-31.json").read_bytes())
        self.assertEqual(runs[0], RUN)
        self.assertEqual(runs, sorted(runs, reverse=True))
        with self.assertRaises(meteogram.ParseError):
            meteogram.parse_available(b"<html>")

    def test_forecast(self):
        f = forecast()
        self.assertEqual((f.steps, f.interval, f.start), (60, 3600, RUN + 3600))
        self.assertEqual((f.row, f.col), (212, 252))
        self.assertEqual(f.run, "31.10.2026 12 UTC")
        self.assertEqual(set(f.series), set(meteogram.SERIES))
        self.assertAlmostEqual(f["airtmp_point"][0], 9.475)
        # the API marks 'no cloud base' with a huge negative number
        self.assertTrue(all(v is None or v >= 0 for v in f["cldbse79"]))
        self.assertIn(None, f["cldbse79"])

    def test_unknown_shape_is_an_error(self):
        for raw in (b"{}", b'{"data": {}}', b"<html>", b'{"data": {"airtmp_point": {"data": []}}}'):
            with self.assertRaises(meteogram.ParseError):
                meteogram.parse_forecast(raw, RUN, 52.0, 21.0)

    def test_fetch_with_fake_transport(self):
        calls = []

        def get(url):
            calls.append(("GET", url))
            return (FIX / "available_2026-10-31.json").read_bytes()

        def post(url, body):
            calls.append(("POST", url, json.loads(body)))
            return (FIX / "um4_60_warszawa_2026-10-31.json").read_bytes()
        f = meteogram.fetch("2727", get, post)
        self.assertEqual(f.run_time, RUN)
        self.assertEqual(calls[0], ("GET", meteogram.API + "/available"))
        self.assertEqual(calls[1][1], meteogram.API + "/um4_60")
        self.assertEqual(calls[1][2], {"point": {"lat": "52.2298", "lon": "21.0117"}, "date": RUN})
        with self.assertRaisesRegex(meteogram.ParseError, "współrzędnych"):
            meteogram.fetch("999999", get, post)

    def test_fetch_falls_back_to_the_previous_run(self):
        posts = []

        def post(url, body):
            posts.append(json.loads(body)["date"])
            if len(posts) == 1:
                raise meteogram.ParseError("not ready")
            return (FIX / "um4_60_warszawa_2026-10-31.json").read_bytes()
        f = meteogram.fetch("2727", lambda url: (FIX / "available_2026-10-31.json").read_bytes(), post)
        self.assertEqual(posts, [RUN, RUN - 6 * 3600])
        self.assertEqual(f.run_time, RUN - 6 * 3600)

    def test_coords_cover_the_catalogue(self):
        coords = meteogram.load_coords()
        for label, woj in storage.VOIVODESHIPS:
            for loc in storage.towns(woj):
                lat, lon = coords[loc.id]
                self.assertTrue(49.0 <= lat <= 54.9 and 14.1 <= lon <= 24.2, str(loc))


class ChartTest(unittest.TestCase):
    def test_png_at_every_scale(self):
        for scale, size in ((1.0, (1060, 660)), (1.5, (1590, 990)), (2.0, (2120, 1320)), (3.0, (3180, 1980))):
            png, got = chart.render_png(forecast(), scale)
            self.assertEqual(got, size)
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", png[16:24]), size)

    def test_missing_values_do_not_crash(self):
        f = forecast()
        for name in f.series:
            f.series[name] = [None] * f.steps
        chart.render_png(f, 1.0)
        f = forecast()
        f.series["pcpttl_max"] = [50.0] * f.steps     # over the scale
        f.series["storm_max"] = [1.0] * f.steps
        chart.render_png(f, 1.0)

    def test_sun_and_local_time(self):
        rise, sset = chart.sun_times(52.23, 21.01, RUN)
        local_rise, local_set = chart.local(rise), chart.local(sset)
        # Warszawa, 31.10.2026 (CET): sunrise 06:28, sunset 16:10 (timeanddate.com: 6:28 / 16:10)
        self.assertEqual((local_rise.tm_hour, local_rise.tm_min), (6, 28))
        self.assertEqual((local_set.tm_hour, local_set.tm_min), (16, 10))
        self.assertEqual(chart.local_offset(RUN), 3600)
        march = calendar.timegm((2026, 3, 29, 1, 0, 0))      # last Sunday of March 2026
        self.assertEqual((chart.local_offset(march - 1), chart.local_offset(march)), (3600, 7200))
        october = calendar.timegm((2026, 10, 25, 1, 0, 0))
        self.assertEqual((chart.local_offset(october - 1), chart.local_offset(october)), (7200, 3600))

    def test_fonts_and_canvas(self):
        f = render.font(11)
        self.assertEqual(f.size, 11)
        self.assertGreater(f.width("Temperatura"), f.width("Temp"))
        c = render.Canvas(20, 10)
        c.fill(2, 2, 5, 4, (1, 2, 3))
        self.assertEqual(bytes(c.rows[2][6:9]), b"\x01\x02\x03")
        self.assertEqual(bytes(c.rows[4][6:9]), b"\xff\xff\xff")
        c.text(0, 8, "Ab °ą", f, (0, 0, 0))
        self.assertTrue(any(b != 255 for row in c.rows for b in row))
        c.vtext(15, 9, "x", f, (0, 0, 0))
        self.assertEqual(len(c.png()) > 50, True)

    def test_placeholders_are_current(self):
        for name in ("loading.png", "error.png"):
            png = (ROOT / name).read_bytes()
            self.assertEqual(struct.unpack(">II", png[16:24]), (1590, 990), name)


class RenderTest(unittest.TestCase):
    """The row-slice fast paths in render.py must draw what the per-pixel code drew."""

    def test_text_fast_path_equals_blending(self):
        f = render.font(16)
        fast = render.Canvas(120, 30, (200, 220, 240))
        fast.text(3, 20, "Wiatr 12 km/h", f, (10, 20, 30))
        slow = render.Canvas(120, 30, (200, 220, 240))
        x = 3
        for ch in "Wiatr 12 km/h":
            for dx, dy, a in f.pixels(ch):
                slow.blend(x + dx, 20 + dy, (10, 20, 30), a)
            x += f.glyph(ch)[4]
        self.assertEqual(fast.rows, slow.rows)
        self.assertTrue(any(b != 200 for b in fast.rows[15]))
        # a glyph over a non-uniform background still blends pixel by pixel
        fast.fill(0, 0, 120, 30, (255, 255, 255))
        fast.fill(0, 0, 120, 15, (0, 0, 0))
        fast.text(3, 20, "W", f, (255, 0, 0))
        self.assertTrue(any(bytes(fast.rows[y][9:12]) not in (b"\x00\x00\x00", b"\xff\xff\xff") for y in range(30)))

    def test_dotted_and_dashed_lines(self):
        c = render.Canvas(30, 5)
        c.dotted_hline(2, 20, 1, (1, 2, 3), 2, 4)
        xs = [x for x in range(30) if bytes(c.rows[1][x * 3:x * 3 + 3]) == b"\x01\x02\x03"]
        self.assertEqual(xs, [2, 3, 8, 9, 14, 15, 20])
        c.dotted_vline(25, 0, 4, (1, 2, 3), 1, 2)
        self.assertEqual([y for y in range(5) if c.rows[y][75] == 1], [0, 3])
        c = render.Canvas(30, 5)
        c.line(0, 2, 29, 2, (9, 9, 9), 1, dash=(3, 2))
        xs = [x for x in range(30) if c.rows[2][x * 3] == 9]
        self.assertEqual(xs, [x for x in range(30) if x % 5 < 3])
        self.assertEqual(sum(1 for y in (1, 3) for b in c.rows[y] if b == 9), 0)

    def test_lines_cover_bresenham_pixels(self):
        for (x0, y0, x1, y1) in ((1, 1, 25, 9), (25, 9, 1, 1), (2, 20, 6, 1), (0, 0, 20, 0), (5, 0, 5, 20)):
            c = render.Canvas(30, 24)
            c.line(x0, y0, x1, y1, (0, 0, 0))
            lit = {(x, y) for y in range(24) for x in range(30) if c.rows[y][x * 3] == 0}
            steps = max(abs(x1 - x0), abs(y1 - y0))
            self.assertEqual(len(lit), steps + 1, (x0, y0, x1, y1))
            self.assertIn((x0, y0), lit)
            self.assertIn((x1, y1), lit)
            for x, y in lit:                       # 8-connected, one pixel per major-axis step
                self.assertTrue(any((x + dx, y + dy) in lit for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy))
        c = render.Canvas(30, 24)
        c.line(2, 10, 27, 12, (0, 0, 0), 3)
        self.assertEqual(sum(1 for b in c.rows[8] if b == 0) + sum(1 for b in c.rows[14] if b == 0), 0)
        self.assertGreater(sum(1 for b in c.rows[11] if b == 0), 3 * 20)

    def test_area_and_band_fill_columns(self):
        c = render.Canvas(40, 20)
        xs, ys = [5.0, 15.0, 25.0, 35.0], [15.0, 5.0, 10.0, 2.0]
        c.area(xs, ys, 18, (0, 0, 0))
        for x in (6, 10, 15, 20, 30, 34):
            y_curve = ys[(x - 5) // 10] + (ys[(x - 5) // 10 + 1] - ys[(x - 5) // 10]) * ((x - 5) % 10) / 10.0
            col = [c.rows[y][x * 3] for y in range(20)]
            self.assertEqual(col[17], 0, x)                                 # row above the base line
            self.assertEqual(col[18], 255, x)                               # the base line itself is not filled
            self.assertEqual(col[int(y_curve + 2)], 0, x)
            self.assertEqual(col[max(0, int(y_curve - 2))], 255, x)
        self.assertEqual(c.rows[16][2 * 3], 255)                            # nothing left of xs[0]
        c = render.Canvas(40, 20)
        c.band([0.0, 39.0], [5.0, 5.0], [10.0, 10.0], (0, 0, 0))
        self.assertEqual([y for y in range(20) if c.rows[y][60] == 0], [5, 6, 7, 8, 9])

    def test_fonts_parse_lazily(self):
        fonts = render._load_fonts()
        self.assertEqual(len(fonts), 12)
        self.assertEqual(render.font(13).glyph("A")[4], render.font(13).width("A"))
        self.assertGreater(len(render.font(13)._glyphs), 100)


class StorageTest(unittest.TestCase):
    def test_catalogue_is_valid(self):
        for label, woj in storage.VOIVODESHIPS:
            towns = storage.towns(woj)
            self.assertTrue(towns, woj)
            self.assertTrue(all(t.id.isdigit() and t.name for t in towns))

    def test_search_ignores_case_and_diacritics(self):
        names = [loc.name for loc, _ in storage.search_towns("lodz")]
        self.assertTrue(names[0].startswith("Łódź"), names[:3])
        self.assertTrue(storage.search_towns("KRAKÓW"))
        self.assertEqual(storage.search_towns("   "), [])

    def test_config_value_roundtrip(self):
        locs = [storage.Location("2119", "Dobre, pow.radziejowski"), storage.Location("2201", "Łódź")]
        value = storage.dump_favourites(locs)
        self.assertEqual(value, "2119 Dobre, pow.radziejowski|2201 Łódź")
        self.assertEqual([str(l) for l in storage.parse_favourites(value)], [str(l) for l in locs])
        self.assertEqual(storage.parse_favourites(""), [])

    def test_read_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            legacy = os.path.join(d, "meteo.ini")
            self.assertIsNone(storage.read_legacy(legacy))
            Path(legacy).write_text("2119 Dobre, pow.radziejowski\n\nśmieci\n", encoding="utf-8")
            self.assertEqual([str(l) for l in storage.read_legacy(legacy)], ["2119 Dobre, pow.radziejowski"])


class FakeElement:
    def __init__(self, default="", **kw):
        self.value = self.saved = default

    def save(self):
        self.saved = self.value

    def cancel(self):
        self.value = self.saved


class FakeConfigFile:
    saves = 0

    def save(self):
        FakeConfigFile.saves += 1


def stub_enigma(height):
    """Just enough of enigma2 to import the screen modules and build skins."""
    size = types.SimpleNamespace(height=lambda: height, width=lambda: height * 16 // 9)
    mods = {
        "enigma": dict(BT_HALIGN_CENTER=4, BT_VALIGN_BOTTOM=128, ePicLoad=object, gRGB=int,
                       getDesktop=lambda n: types.SimpleNamespace(size=lambda: size)),
        "twisted": {}, "twisted.internet": {}, "twisted.internet.threads": dict(deferToThread=None),
        "Components": {}, "Components.ActionMap": dict(ActionMap=object),
        "Components.config": dict(ConfigSubsection=types.SimpleNamespace, ConfigText=FakeElement,
                                  ConfigSelection=FakeElement, ConfigNothing=FakeElement, ConfigYesNo=FakeElement, getConfigListEntry=tuple,
                                  config=types.SimpleNamespace(plugins=types.SimpleNamespace()),
                                  configfile=FakeConfigFile()),
        "Components.ConfigList": dict(ConfigListScreen=type("ConfigListScreen", (), {})), "Components.Sources": {},
        "Components.Sources.StaticText": dict(StaticText=object), "Components.Label": dict(Label=object),
        "Components.Pixmap": dict(Pixmap=object), "Components.MenuList": dict(MenuList=object),
        "Screens": {}, "Screens.ChoiceBox": dict(ChoiceBox=object), "Screens.Screen": dict(Screen=object),
        "Screens.TextBox": dict(TextBox=object), "Screens.MessageBox": dict(MessageBox=object),
        "Screens.VirtualKeyBoard": dict(VirtualKeyBoard=object),
    }
    for name, attrs in mods.items():
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
    for name in (f"{PKG}.Meteo", f"{PKG}.configure", f"{PKG}.settings", f"{PKG}.setup"):
        sys.modules.pop(name, None)


class SkinTest(unittest.TestCase):
    def check(self, skin):
        root = ET.fromstring(skin)
        sw, sh = map(int, root.get("size").split(","))
        for el in root:
            x, y = map(int, el.get("position").split(","))
            w, h = map(int, el.get("size").split(","))
            self.assertLessEqual(x + w, sw, el.attrib)
            self.assertLessEqual(y + h, sh, el.attrib)
        return sw, sh

    def test_skins_fit_every_resolution(self):
        for height in (720, 1080, 1440, 2160):
            stub_enigma(height)
            Meteo = __import__(f"{PKG}.Meteo", fromlist=["x"])
            __import__(f"{PKG}.setup", fromlist=["x"])
            configure = __import__(f"{PKG}.configure", fromlist=["x"])
            w, h = self.check(Meteo.build_skin())
            self.assertLessEqual(h, height)
            self.check(configure.build_skin())
            self.assertEqual(Meteo.RENDER_SCALE, min(height / 720.0, 2.0))


class AlertsTest(unittest.TestCase):
    """Real public API response captured 2026-10-08 (seven wind warnings)."""
    NOW = alerts.datetime(2026, 10, 9, 8, 0)

    def sample(self):
        return alerts.parse((FIX / "warningsmeteo_2026-10-08.json").read_bytes())

    def test_parse(self):
        found = self.sample()
        self.assertEqual(len(found), 7)
        self.assertEqual({a.event for a in found}, {"Silny wiatr"})
        self.assertEqual(sorted({a.level for a in found}), [1, 2])

    def test_no_warnings(self):
        self.assertEqual(alerts.parse((FIX / "warningsmeteo_none.json").read_bytes()), [])

    def test_unknown_shape_is_an_error(self):
        for raw in (b'{"message": "Limit"}', b"<html>", b"[{}]"):
            with self.assertRaises(alerts.meteogram.ParseError):
                alerts.parse(raw)

    def test_gdansk(self):
        counties = alerts.load_counties()
        found = alerts.for_county(self.sample(), counties["1877"], self.NOW)
        self.assertEqual([(a.level, a.period(self.NOW)) for a in found], [(1, "do 15:00")])
        self.assertEqual(alerts.summary(found, self.NOW), "1. st. Silny wiatr do 15:00")
        self.assertIn("Prawdopodobieństwo: 80%", found[0].details(self.NOW))

    def test_expired_and_upcoming(self):
        counties = alerts.load_counties()
        # Jelenia Góra: 21:00-02:00 warning is over at 08:00
        self.assertEqual(alerts.for_county(self.sample(), counties["981"], self.NOW), [])
        early = alerts.datetime(2026, 10, 8, 20, 0)
        found = alerts.for_county(self.sample(), counties["981"], early)
        self.assertEqual(found[0].period(early), "od 21:00 do 09.10 02:00")
        self.assertEqual(alerts.summary(found, early), "1. st. Silny wiatr od 21:00")

    def test_most_severe_first(self):
        a = self.sample()
        county = "2210"
        self.assertEqual([w.level for w in alerts.for_county(a, county, self.NOW)][0], 2)

    def test_county_table_covers_catalogue(self):
        counties = alerts.load_counties()
        for label, woj in storage.VOIVODESHIPS:
            for loc in storage.towns(woj):
                self.assertRegex(counties.get(loc.id, ""), r"^\d{4}$", str(loc))


class SettingsTest(unittest.TestCase):
    def test_legacy_ini_is_migrated_once(self):
        with tempfile.TemporaryDirectory() as d:
            legacy = os.path.join(d, "meteo.ini")
            Path(legacy).write_text("2119 Dobre, pow.radziejowski\n462 Kraków\n", encoding="utf-8")
            old = storage.LEGACY_CONFIG_FILE
            storage.LEGACY_CONFIG_FILE = legacy
            try:
                stub_enigma(720)
                settings = __import__(f"{PKG}.settings", fromlist=["x"])
            finally:
                storage.LEGACY_CONFIG_FILE = old
            self.assertEqual(settings.cfg.favourites.saved, "2119 Dobre, pow.radziejowski|462 Kraków")
            self.assertEqual([l.id for l in settings.favourites()], ["2119", "462"])
            self.assertFalse(os.path.exists(legacy))
            self.assertTrue(os.path.exists(legacy + ".migrated"))

    def test_remember_last_only_when_enabled(self):
        stub_enigma(720)
        settings = __import__(f"{PKG}.settings", fromlist=["x"])
        settings.remember_last("462")
        self.assertEqual(settings.cfg.last.saved, "")
        settings.cfg.start.value = "last"
        settings.remember_last("462")
        self.assertEqual(settings.cfg.last.saved, "462")


class UpdateTest(unittest.TestCase):
    LINE = f"\ninstall.sh {'0' * 64}\n"

    def test_version_file(self):
        self.assertEqual(update.parse_version(b"26.10.10" + self.LINE.encode()), "26.10.10")
        self.assertEqual(update.parse_version(b"26.10.10\n"), "26.10.10")
        for bad in (b"", b"<html>404</html>\n", b"26.10 .10\n"):
            with self.assertRaises(update.UpdateError):
                update.parse_version(bad)

    def test_version_on_disk_wins_over_the_running_one(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(update.installed_version(d), update.VERSION)
            Path(d, "version.py").write_text('VERSION = "99.1.1"\n')
            self.assertEqual(update.installed_version(d), "99.1.1")

    def test_same_version_runs_nothing(self):
        def run(*a, **k):
            raise AssertionError("install.sh must not run")
        self.assertIsNone(update.check(lambda url: (update.installed_version() + self.LINE).encode(), run))

    def test_other_version_runs_the_one_liner(self):
        import subprocess
        calls = []

        def run(cmd, **kw):
            calls.append((cmd, kw["shell"], kw["env"]["UMMETEO_DEST"]))
            self.assertEqual((kw["stdout"], kw["stderr"]), (subprocess.DEVNULL, subprocess.DEVNULL))
            return types.SimpleNamespace(returncode=0)
        self.assertEqual(update.check(lambda url: b"99.1.1" + self.LINE.encode(), run), "99.1.1")
        self.assertEqual(calls, [(f"wget -qO- {update.BASE_URL}/install.sh | sh", True, update.PLUGIN_DIR)])

        failed = types.SimpleNamespace(returncode=1)
        with self.assertRaisesRegex(update.UpdateError, "kod 1"):
            update.check(lambda url: b"99.1.1\n", lambda cmd, **kw: failed)

    def test_server_address_is_never_in_plain_text(self):
        import re
        import subprocess
        install = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertEqual(re.search(r'^BASE_ENC="(.*)"', install, re.M).group(1), update.BASE_URL_ENC)
        self.assertTrue(update.BASE_URL.startswith("https://"))
        host = update.BASE_URL.split("/")[2]
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        for name in files or [p.name for p in ROOT.iterdir() if p.is_file()]:
            data = (ROOT / name).read_bytes()
            self.assertNotIn(host.encode(), data, name)
            self.assertNotIn(host.split(".")[0].encode(), data.lower(), name)

    def test_install_sh_replaces_the_plugin(self):
        import hashlib
        import io
        import subprocess
        import tarfile
        with tempfile.TemporaryDirectory() as d:
            server, dest = os.path.join(d, "server"), os.path.join(d, "Extensions", "UMMeteoPL")
            os.makedirs(server)
            os.makedirs(dest)
            Path(dest, "stale.py").write_text("old")
            Path(dest, "meteo.ini").write_text("462 Kraków\n")
            tgz = os.path.join(server, "UMMeteoPL.tar.gz")
            with tarfile.open(tgz, "w:gz") as tar:
                for name, body in (("plugin.py", b""), ("Meteo.py", b""), ("version.py", b'VERSION = "99.1.1"\n')):
                    info = tarfile.TarInfo(f"UMMeteoPL/{name}")
                    info.size = len(body)
                    tar.addfile(info, io.BytesIO(body))
            sha = Path(tgz + ".sha256")
            sha.write_text(hashlib.sha256(Path(tgz).read_bytes()).hexdigest() + "  UMMeteoPL.tar.gz\n")
            env = dict(os.environ, UMMETEO_BASE="file://" + server, UMMETEO_DEST=dest)
            run = subprocess.run(["sh", str(ROOT / "install.sh")], env=env, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(sorted(os.listdir(dest)), ["Meteo.py", "meteo.ini", "plugin.py", "version.py"])
            self.assertEqual(update.installed_version(dest), "99.1.1")

            sha.write_text("0" * 64 + "  UMMeteoPL.tar.gz\n")
            run = subprocess.run(["sh", str(ROOT / "install.sh")], env=env, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("suma kontrolna archiwum", run.stderr.decode())


class ScreenApiTest(unittest.TestCase):
    # enigma2 Screen methods; overriding one (e.g. show) breaks session.open()
    RESERVED = {"show", "hide", "close", "execBegin", "execEnd", "doClose", "setTitle", "getTitle",
                "applySkin", "createGUIScreen", "deleteGUIScreen", "getRelatedScreen", "setFocus",
                "setAnimationMode", "callLater", "addSummary", "removeSummary", "getCallback"}

    def test_no_screen_method_is_shadowed(self):
        import ast
        for name in ("Meteo.py", "configure.py", "setup.py"):
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
            for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
                defs = {f.name for f in cls.body if isinstance(f, ast.FunctionDef)}
                self.assertFalse(defs & self.RESERVED, f"{name}:{cls.name}")


class FirstLoadTest(unittest.TestCase):
    def test_nothing_is_opened_during_layout(self):
        # onLayoutFinish runs inside applySkin, before the screen is modal: session.open
        # there kills the GUI ("modal open are allowed only from a screen which is modal!",
        # Uno 4K SE, fresh install with no favourites)
        import ast
        tree = ast.parse((ROOT / "Meteo.py").read_text(encoding="utf-8"))
        meteo = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Meteo")
        funcs = {f.name: f for f in meteo.body if isinstance(f, ast.FunctionDef)}
        openers = {"edit_favourites", "configure", "choose", "help", "info"}
        for name in ("first_load", "reload", "show_location", "show_picture"):
            calls = {c.func.attr for c in ast.walk(funcs[name])
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
            self.assertFalse(calls & (openers | {"open", "openWithCallback"}), name)


class SkinNameTest(unittest.TestCase):
    def test_screens_use_their_own_skin_names(self):
        # BlackHarmony ships <screen name="Meteo"> and <screen name="Configure"> for the old
        # plugin; enigma picks a skin screen by skinName (= class name by default)
        import ast
        import re
        for name, cls in (("Meteo.py", "Meteo"), ("configure.py", "Configure")):
            src = (ROOT / name).read_text(encoding="utf-8")
            embedded = re.search(r'<screen name="([^"]+)"', src).group(1)
            tree = ast.parse(src)
            node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
            assigned = [a.value.value for a in ast.walk(node) if isinstance(a, ast.Assign)
                        and any(isinstance(t, ast.Attribute) and t.attr == "skinName" for t in a.targets)]
            self.assertEqual(assigned, [embedded], name)
            self.assertNotEqual(embedded, cls)


class KeymapTest(unittest.TestCase):
    def test_actions_are_mapped(self):
        mapped = {k.get("mapto") for k in ET.parse(ROOT / "keymap.xml").iter("key")}
        self.assertTrue({"ok", "cancel", "red", "green", "yellow", "blue", "menu", "info", "list",
                         "start", "left", "right", "up", "down"} | {str(n) for n in range(1, 10)} <= mapped)


if __name__ == "__main__":
    unittest.main()
