# -*- coding: utf-8 -*-
"""Host-side tests: python3 -m unittest discover -s tests -t ."""
import os
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


class ParseTest(unittest.TestCase):
    def test_page(self):
        f = meteogram.parse_page((FIX / "meteorogram_2119.html").read_bytes())
        self.assertEqual((f.date, f.row, f.col), ("2026100912", "393", "208"))
        self.assertEqual(f.place, "Dobre, pow.radziejowski, woj.kujawsko-pomorskie")
        self.assertEqual(f.run, "09.10.2026 12 UTC")
        self.assertIn("fdate=2026100912&row=393&col=208", f.picture_url)

    def test_invalid_id(self):
        with self.assertRaises(meteogram.ParseError):
            meteogram.parse_page((FIX / "meteorogram_invalid_id.html").read_bytes())

    def test_png_size(self):
        self.assertEqual(meteogram.png_size((FIX / "mgram_head.png").read_bytes()), (630, 780))
        with self.assertRaises(meteogram.ParseError):
            meteogram.png_size(b"<html>error</html>" * 3)

    def test_fetch_with_fake_transport(self):
        page = (FIX / "meteorogram_2119.html").read_bytes()
        png = (FIX / "mgram_head.png").read_bytes()
        urls = []
        get = lambda url: urls.append(url) or (page if "meteorogram_id" in url else png)
        forecast, raw, size = meteogram.fetch("2119", get)
        self.assertEqual(size, (630, 780))
        self.assertTrue(urls[0].endswith("id=2119"))


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
        for height in (720, 1080, 2160):
            stub_enigma(height)
            Meteo = __import__(f"{PKG}.Meteo", fromlist=["x"])
            __import__(f"{PKG}.setup", fromlist=["x"])
            configure = __import__(f"{PKG}.configure", fromlist=["x"])
            w, h = self.check(Meteo.build_skin())
            self.assertLessEqual(h, height)
            self.check(configure.build_skin())
            self.assertIn("leftfhd.png" if height >= 1080 else "left.png", Meteo.build_skin())


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
    def setUp(self):
        update.installed = update.failed = ""

    def test_version_file(self):
        sha = "ab" * 32
        self.assertEqual(update.parse_version(f"26.10.10\ninstall.sh {sha}\n".encode()), ("26.10.10", sha))
        for bad in (b"", b"<html>404</html>\n", b"26.10.10\n", b"26.10.10\ninstall.sh xyz\n"):
            with self.assertRaises(update.UpdateError):
                update.parse_version(bad)

    def test_only_a_different_version_is_offered(self):
        line = f"\ninstall.sh {'0' * 64}\n"
        self.assertIsNone(update.available(lambda url: (update.VERSION + line).encode()))
        self.assertEqual(update.available(lambda url: ("99.1.1" + line).encode())[0], "99.1.1")
        update.failed = "99.1.1"
        self.assertIsNone(update.available(lambda url: ("99.1.1" + line).encode()))

    def test_wrong_install_sh_checksum_is_refused(self):
        with self.assertRaises(update.UpdateError):
            update.install("99.1.1", "0" * 64, get=lambda url: b"rm -rf /\n", run=None)
        self.assertEqual(update.failed, "99.1.1")

    def test_install_sh_replaces_the_plugin_from_the_server(self):
        import hashlib
        import io
        import tarfile
        with tempfile.TemporaryDirectory() as d:
            server, dest = os.path.join(d, "server"), os.path.join(d, "Extensions", "UMMeteoPL")
            os.makedirs(server)
            os.makedirs(dest)
            Path(dest, "stale.py").write_text("old")
            Path(dest, "meteo.ini").write_text("462 Kraków\n")
            with tarfile.open(os.path.join(server, "UMMeteoPL.tar.gz"), "w:gz") as tar:
                for name, body in (("plugin.py", b""), ("Meteo.py", b""), ("version.py", b'VERSION = "99.1.1"\n')):
                    info = tarfile.TarInfo(f"UMMeteoPL/{name}")
                    info.size = len(body)
                    tar.addfile(info, io.BytesIO(body))
            digest = hashlib.sha256(Path(server, "UMMeteoPL.tar.gz").read_bytes()).hexdigest()
            Path(server, "UMMeteoPL.tar.gz.sha256").write_text(f"{digest}  UMMeteoPL.tar.gz\n")
            script = (ROOT / "install.sh").read_bytes()
            old = update.BASE_URL, update.PLUGIN_DIR
            update.BASE_URL, update.PLUGIN_DIR = "file://" + server, dest
            try:
                update.install("99.1.1", hashlib.sha256(script).hexdigest(), get=lambda url: script)
            finally:
                update.BASE_URL, update.PLUGIN_DIR = old
            self.assertEqual(update.installed, "99.1.1")
            self.assertEqual(sorted(os.listdir(dest)), ["Meteo.py", "meteo.ini", "plugin.py", "version.py"])

            Path(server, "UMMeteoPL.tar.gz.sha256").write_text("0" * 64 + "  UMMeteoPL.tar.gz\n")
            update.BASE_URL, update.PLUGIN_DIR = "file://" + server, dest
            try:
                with self.assertRaisesRegex(update.UpdateError, "suma kontrolna archiwum"):
                    update.install("99.1.2", hashlib.sha256(script).hexdigest(), get=lambda url: script)
            finally:
                update.BASE_URL, update.PLUGIN_DIR = old


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


class KeymapTest(unittest.TestCase):
    def test_actions_are_mapped(self):
        mapped = {k.get("mapto") for k in ET.parse(ROOT / "keymap.xml").iter("key")}
        self.assertTrue({"ok", "cancel", "red", "green", "yellow", "blue", "menu", "info", "list",
                         "start", "left", "right", "up", "down"} | {str(n) for n in range(1, 10)} <= mapped)


if __name__ == "__main__":
    unittest.main()
