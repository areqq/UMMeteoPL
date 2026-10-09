# -*- coding: utf-8 -*-
import os
import time
from datetime import datetime
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError

from enigma import BT_HALIGN_CENTER, BT_VALIGN_BOTTOM, ePicLoad, gRGB, getDesktop
from twisted.internet.threads import deferToThread

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Screens.ChoiceBox import ChoiceBox
from Screens.Screen import Screen
from Screens.TextBox import TextBox

from . import alerts, meteogram, settings, storage

VERSION = "26.10.09"
TMP_DIR = "/tmp/ummeteo"
ALERTS_TTL = 10 * 60
# IMGW warning levels: yellow, orange, red (background, text)
ALERT_COLOURS = {1: (0xf2c200, 0x202020), 2: (0xff8c00, 0x202020), 3: (0xd02020, 0xffffff)}

SCALE = getDesktop(0).size().height() / 720.0


def s(value):
    """Skin coordinate designed for 1280x720 -> current resolution."""
    return int(round(value * SCALE))


def keys_bar(y, width, items, bg):
    """Footer with coloured key markers: [(colour, text, width), ...]."""
    out = [f'<eLabel position="0,{s(y)}" size="{s(width)},{s(30)}" backgroundColor="{bg}" />']
    x = 10
    for colour, text, w in items:
        out.append(f'<eLabel position="{s(x)},{s(y + 8)}" size="{s(14)},{s(14)}" backgroundColor="{colour}" zPosition="1" />')
        out.append(f'<eLabel text="{text}" position="{s(x + 20)},{s(y)}" size="{s(w - 24)},{s(30)}" font="Regular;{s(17)}" '
                   f'valign="center" foregroundColor="#00202020" backgroundColor="{bg}" zPosition="1" />')
        x += w
    return "\n".join(out)


RED, GREEN, YELLOW, BLUE = "#00e04040", "#0030b030", "#00e0c020", "#003070e0"


def build_skin():
    legend = "leftfhd.png" if SCALE >= 1.5 else "left.png"
    header, chart_w, chart_h, legend_w = 26, meteogram.CHART_WIDTH, meteogram.CHART_HEIGHT, 280
    width, footer_y = legend_w + chart_w, header + chart_h
    return f"""
    <screen name="UMMeteoPL" position="center,center" size="{s(width)},{s(footer_y + 30)}" flags="wfNoBorder" backgroundColor="#00ffffff" title="UM Meteo.pl">
        <widget name="title" position="{s(10)},0" size="{s(500)},{s(header)}" font="Regular;{s(20)}" valign="center" foregroundColor="#00202020" backgroundColor="#00ffffff" />
        <widget name="status" position="{s(510)},0" size="{s(width - 520)},{s(header)}" font="Regular;{s(16)}" halign="right" valign="center" foregroundColor="#00505050" backgroundColor="#00ffffff" />
        <ePixmap position="0,{s(header)}" size="{s(legend_w)},{s(chart_h)}" pixmap="{storage.PLUGIN_DIR}/{legend}" scale="1" />
        <widget name="chart" position="{s(legend_w)},{s(header)}" size="{s(chart_w)},{s(chart_h)}" zPosition="1" />
        {keys_bar(footer_y, width, [(RED, "Odśwież", 110), (GREEN, "Następna", 115), (YELLOW, "Pomoc", 100), (BLUE, "Ustawienia", 125)], "#00ececec")}
        <widget name="hints" position="{s(460)},{s(footer_y)}" size="{s(width - 470)},{s(30)}" font="Regular;{s(16)}" halign="right" valign="center" foregroundColor="#00606060" backgroundColor="#00ececec" zPosition="1" />
        <widget name="alert" position="{s(460)},{s(footer_y + 2)}" size="{s(width - 462)},{s(26)}" font="Regular;{s(15)}" halign="center" valign="center" noWrap="1" foregroundColor="#00202020" backgroundColor="#00f2c200" zPosition="2" />
    </screen>"""


def describe_error(failure):
    err = failure.value
    if isinstance(err, meteogram.ParseError):
        return str(err)
    if isinstance(err, HTTPError):
        return f"meteo.pl odpowiada błędem {err.code}"
    if isinstance(err, (URLError, SocketTimeout, ConnectionError)):
        return "Brak połączenia z meteo.pl"
    print("[UMMeteo] fetch failed:", failure.getTraceback())
    return f"Błąd: {err}"


class Meteo(Screen):
    def __init__(self, session):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self.setTitle("UM Meteo.pl")
        self["title"] = Label("")
        self["status"] = Label("")
        self["chart"] = Pixmap()
        self["hints"] = Label("OK lista   < > zmiana   1-9 skok")
        self["alert"] = Label("")
        self["actions"] = ActionMap(["MeteoActions"], {
            "ok": self.choose,
            "list": self.choose,
            "cancel": self.close,
            "left": self.prev,
            "right": self.next,
            "green": self.next,
            "red": self.refresh,
            "yellow": self.help,
            "info": self.info,
            "blue": self.configure,
            "menu": self.configure,
            "start": lambda: self.show_location(0),
            **{str(n): (lambda n=n: self.show_location(n - 1)) for n in range(1, 10)},
        }, -1)

        self.favourites = []
        self.index = 0
        self.seq = 0            # newer request invalidates older callbacks
        self.cache = {}         # id -> (time, Forecast, png path, (w, h))
        self.alerts = None      # IMGW warnings, None = not known
        self.alerts_time = 0
        self.counties = alerts.load_counties()
        self.closed = False
        self.decoding = False
        self.queued = None
        self.picload = ePicLoad()
        self.picload.PictureData.get().append(self.decoded)
        os.makedirs(TMP_DIR, exist_ok=True)

        self.onLayoutFinish.append(self.first_load)
        self.onClose.append(self.cleanup)

    # --- lifecycle ---------------------------------------------------------
    def first_load(self):
        self["alert"].hide()
        self.reload(first_run=True)

    def cleanup(self):
        self.closed = True
        if self.favourites:
            settings.remember_last(self.favourites[self.index].id)
        try:
            self.picload.PictureData.get().remove(self.decoded)
        except ValueError:
            pass
        for _t, _f, path, _size in self.cache.values():
            try:
                os.unlink(path)
            except OSError:
                pass

    def reload(self, first_run=False):
        self.favourites = settings.favourites()
        if self.favourites:
            if first_run and settings.cfg.start.value == "last":
                ids = [loc.id for loc in self.favourites]
                self.index = ids.index(settings.cfg.last.value) if settings.cfg.last.value in ids else 0
            self.show_location(min(self.index, len(self.favourites) - 1))
            return
        self.seq += 1
        self["title"].setText("Brak ulubionych miejscowości")
        self.set_status("MENU lub NIEBIESKI - dodaj miejscowość")
        self.show_picture(storage.PLUGIN_DIR + "/loading.png")
        if first_run:
            self.edit_favourites()

    # --- navigation --------------------------------------------------------
    def show_location(self, index, force=False):
        if not 0 <= index < len(self.favourites):
            return
        self.index = index
        loc = self.favourites[index]
        self.seq += 1
        seq = self.seq
        self["title"].setText(loc.name)
        self.update_alert()
        self.load_alerts(force)

        cached = self.cache.get(loc.id)
        if cached and not force and time.time() - cached[0] < int(settings.cfg.cache.value) * 60:
            self.ready(seq, loc.id, cached)
            return
        self.set_status(f"{self.position()}   Ładuję...")
        self.show_picture(storage.PLUGIN_DIR + "/loading.png")
        d = deferToThread(self.download, loc.id)
        d.addCallbacks(lambda result: self.ready(seq, loc.id, result), lambda failure: self.failed(seq, failure))

    def next(self):
        if self.favourites:
            self.show_location((self.index + 1) % len(self.favourites))

    def prev(self):
        if self.favourites:
            self.show_location((self.index - 1) % len(self.favourites))

    def refresh(self):
        self.show_location(self.index, force=True)

    def position(self):
        return f"{self.index + 1}/{len(self.favourites)}"

    # --- worker thread -----------------------------------------------------
    @staticmethod
    def download(location_id):
        forecast, png, size = meteogram.fetch(location_id)
        path = f"{TMP_DIR}/{location_id}.png"
        with open(path, "wb") as f:
            f.write(png)
        return time.time(), forecast, path, size

    # --- reactor thread ----------------------------------------------------
    def ready(self, seq, loc_id, result):
        if self.closed:
            return
        self.cache[loc_id] = result
        if seq != self.seq:
            return
        _t, forecast, path, size = result
        self.set_status(f"{self.position()}   prognoza z {forecast.run}")
        self.show_picture(path, size)

    def failed(self, seq, failure):
        if self.closed or seq != self.seq:
            return
        self.set_status(f"{self.position()}   {describe_error(failure)}", error=True)
        self.show_picture(storage.PLUGIN_DIR + "/error.png")

    # --- IMGW warnings -----------------------------------------------------
    def load_alerts(self, force=False):
        if self.alerts_time and not force and time.time() - self.alerts_time < ALERTS_TTL:
            return
        self.alerts_time = time.time()
        d = deferToThread(alerts.fetch)
        d.addCallbacks(self.alerts_loaded, self.alerts_failed)

    def alerts_loaded(self, result):
        if not self.closed:
            self.alerts = result
            self.update_alert()

    def alerts_failed(self, failure):
        print("[UMMeteo] IMGW warnings:", failure.getErrorMessage())
        self.alerts_time = 0    # try again on the next location change

    def current_alerts(self):
        if not self.alerts or not self.favourites:
            return []
        county = self.counties.get(self.favourites[self.index].id)
        return alerts.for_county(self.alerts, county, datetime.now()) if county else []

    def update_alert(self):
        found = self.current_alerts()
        if not found:
            self["alert"].hide()
            self["hints"].show()
            return
        bg, fg = ALERT_COLOURS.get(found[0].level, ALERT_COLOURS[3])
        self["alert"].setText(f"{alerts.summary(found, datetime.now())}  [INFO]")
        if self["alert"].instance:
            self["alert"].instance.setBackgroundColor(gRGB(bg))
            self["alert"].instance.setForegroundColor(gRGB(fg))
        self["hints"].hide()
        self["alert"].show()

    def info(self):
        found = self.current_alerts()
        if not found:
            return self.help()
        now = datetime.now()
        text = "\n\n----------\n\n".join(a.details(now) for a in found)
        self.session.open(TextBox, text + "\n\nŹródło: IMGW-PIB, danepubliczne.imgw.pl",
                          f"Ostrzeżenia IMGW - {self.favourites[self.index].name}")

    def set_status(self, text, error=False):
        self["status"].setText(text)
        if self["status"].instance:
            self["status"].instance.setForegroundColor(gRGB(0xc00000 if error else 0x505050))

    # --- picture -----------------------------------------------------------
    def show_picture(self, path, size=None):
        """Decode in the background, scaled to the chart width.

        Anything taller than the chart (the banner above it) is cut off by
        bottom alignment."""
        if self.decoding:
            self.queued = (path, size)
            return
        widget = self["chart"].instance
        w, h = widget.size().width(), widget.size().height()
        if size:
            h = int(round(size[1] * w / float(size[0])))
        self.decoding = True
        self.picload.setPara((w, h, 0, 0, False, 1, "#00ffffff"))
        if self.picload.startDecode(path):
            self.decoding = False

    def decoded(self, picinfo=None):
        self.decoding = False
        if self.closed:
            return
        if self.queued:
            path, size = self.queued
            self.queued = None
            self.show_picture(path, size)
            return
        ptr = self.picload.getData()
        if ptr is not None:
            widget = self["chart"].instance
            set_flags = getattr(widget, "setPixmapScale", None) or getattr(widget, "setPixmapScaleFlags", None)
            if set_flags:
                set_flags(BT_HALIGN_CENTER | BT_VALIGN_BOTTOM)
            widget.setPixmap(ptr)

    # --- dialogs -----------------------------------------------------------
    def choose(self):
        if not self.favourites:
            return self.edit_favourites()
        choices = [(loc.name, n) for n, loc in enumerate(self.favourites)]
        self.session.openWithCallback(self.chosen, ChoiceBox, title="Wybierz miejscowość",
                                      list=choices, selection=self.index, windowTitle="Ulubione")

    def chosen(self, answer):
        if answer is not None:
            self.show_location(answer[1])

    def configure(self):
        from .setup import Setup
        self.session.openWithCallback(self.configured, Setup)

    def edit_favourites(self):
        from .configure import Configure
        self.session.openWithCallback(self.configured, Configure)

    def configured(self, changed=False):
        if changed:
            self.reload()

    def help(self):
        try:
            with open(storage.PLUGIN_DIR + "/opis.txt", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = "Brak opisu."
        self.session.open(TextBox, text, f"UM Meteo.pl {VERSION} - pomoc")
