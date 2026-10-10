# -*- coding: utf-8 -*-
from Components.config import ConfigNothing, configfile, getConfigListEntry
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
from Components.Sources.StaticText import StaticText
from Screens.Screen import Screen

from .settings import cfg, favourites


class Setup(ConfigListScreen, Screen):
    """Plugin settings drawn by the skin's own "Setup" screen."""

    def __init__(self, session):
        Screen.__init__(self, session)
        self.skinName = ["UMMeteoPLSetup", "Setup"]
        self.setTitle("UM Meteo.pl - ustawienia")
        if hasattr(self, "setImage"):
            self.setImage("UMMeteoPL", "setup")  # skin's default setup icon; Setup skins expect "Image"
        self["key_red"] = StaticText("Anuluj")
        self["key_green"] = StaticText("Zapisz")
        self["description"] = Label("")
        self["footnote"] = Label("")
        self.favourites_entry = ConfigNothing()
        ConfigListScreen.__init__(self, [], session=session, on_change=self.describe, fullUI=True)
        self.favourites_changed = False
        self.build()
        self["config"].onSelectionChanged.append(self.describe)
        self.onLayoutFinish.append(self.describe)

    def build(self):
        self["config"].list = [
            getConfigListEntry(f"Ulubione miejscowości ({len(favourites())})", self.favourites_entry,
                               "OK - dodawanie, usuwanie i kolejność miejscowości."),
            getConfigListEntry("Po uruchomieniu pokaż miejscowość", cfg.start,
                               "Którą miejscowość z listy ulubionych pokazać po otwarciu wtyczki."),
            getConfigListEntry("Pamiętaj pobrany meteogram przez", cfg.cache,
                               "W tym czasie powrót do miejscowości nie pobiera meteogramu ponownie. "
                               "CZERWONY na ekranie meteogramu zawsze pobiera świeży."),
            getConfigListEntry("Aktualizuj automatycznie", cfg.autoupdate,
                               "Co 8 godzin wtyczka sprawdza w tle na swoim serwerze, czy jest inna wersja, "
                               "i instaluje ją. Nowa wersja działa po restarcie GUI."),
        ]

    def describe(self):
        current = self["config"].getCurrent()
        self["description"].setText(current[2] if current and len(current) > 2 else "")

    def keySelect(self):
        current = self["config"].getCurrent()
        if current and current[1] is self.favourites_entry:
            from .configure import Configure
            self.session.openWithCallback(self.favourites_edited, Configure)
        else:
            ConfigListScreen.keySelect(self)

    def favourites_edited(self, changed=False):
        self.favourites_changed |= bool(changed)
        index = self["config"].getCurrentIndex()
        self.build()
        self["config"].setCurrentIndex(index)

    def keySave(self):
        for entry in self["config"].list:
            entry[1].save()
        configfile.save()
        self.close(True)

    def keyCancel(self):
        for entry in self["config"].list:
            entry[1].cancel()
        self.close(self.favourites_changed)
