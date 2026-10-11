# -*- coding: utf-8 -*-
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard

from . import settings, storage
from .Meteo import BLUE, GREEN, RED, YELLOW, s

ADD = "+ Dodaj miejscowość"
SEARCH = object()


def build_skin():
    width, height = 820, 560
    keys = []
    x = 20
    for colour, text in ((RED, "Usuń"), (GREEN, "Zapisz"), (YELLOW, "W górę"), (BLUE, "W dół")):
        keys.append(f'<eLabel position="{s(x)},{s(height - 40)}" size="{s(180)},{s(4)}" backgroundColor="{colour}" />')
        keys.append(f'<eLabel text="{text}" position="{s(x)},{s(height - 34)}" size="{s(180)},{s(30)}" font="Regular;{s(20)}" halign="center" valign="center" transparent="1" />')
        x += 200
    keys = "\n".join(keys)
    return f"""
    <screen name="UMMeteoPLConfigure" position="center,center" size="{s(width)},{s(height)}" title="UM Meteo.pl - ulubione">
        <widget name="hint" position="{s(20)},{s(10)}" size="{s(width - 40)},{s(56)}" font="Regular;{s(18)}" valign="center" />
        <widget name="list" position="{s(20)},{s(76)}" size="{s(width - 40)},{s(height - 130)}" font="Regular;{s(22)}" itemHeight="{s(34)}" scrollbarMode="showOnDemand" />
        {keys}
    </screen>"""


class Configure(Screen):
    def __init__(self, session):
        self.skin = build_skin()
        Screen.__init__(self, session)
        # not the class name: skins (e.g. BlackHarmony) still carry screens of the old plugin
        # named "Meteo" and "Configure", which would replace the embedded skin
        self.skinName = "UMMeteoPLConfigure"
        self.setTitle("UM Meteo.pl - ulubione")
        self.locations = settings.favourites()
        self.dirty = False
        self["hint"] = Label("OK - zmień lub dodaj miejscowość.  Kolejność listy to kolejność "
                             "przełączania na ekranie meteogramu (klawisze 1-9).")
        self["list"] = MenuList([])
        self["actions"] = ActionMap(["MeteoActions"], {
            "ok": self.edit,
            "cancel": self.exit,
            "up": lambda: self["list"].up(),
            "down": lambda: self["list"].down(),
            "left": lambda: self["list"].pageUp(),
            "right": lambda: self["list"].pageDown(),
            "red": self.remove,
            "green": self.save,
            "yellow": lambda: self.move(-1),
            "blue": lambda: self.move(1),
        }, -1)
        self.onLayoutFinish.append(self.refresh)

    def refresh(self, index=None):
        self["list"].setList([f"{n + 1}. {loc.name}" for n, loc in enumerate(self.locations)] + [ADD])
        if index is not None:
            self["list"].moveToIndex(index)

    def current(self):
        """Index of the selected favourite or None on the 'add' row."""
        index = self["list"].getSelectionIndex()
        return index if index < len(self.locations) else None

    # --- editing -----------------------------------------------------------
    def remove(self):
        index = self.current()
        if index is not None:
            del self.locations[index]
            self.dirty = True
            self.refresh(min(index, len(self.locations)))

    def move(self, step):
        index = self.current()
        target = None if index is None else index + step
        if target is None or not 0 <= target < len(self.locations):
            return
        loc = self.locations
        loc[index], loc[target] = loc[target], loc[index]
        self.dirty = True
        self.refresh(target)

    def edit(self):
        choices = [("Szukaj po nazwie...", SEARCH)] + [(f"woj. {label}", woj) for label, woj in storage.VOIVODESHIPS]
        self.session.openWithCallback(self.voivodeship_chosen, ChoiceBox, title="Wybierz województwo lub wyszukaj",
                                      list=choices, windowTitle="Dodaj miejscowość")

    def voivodeship_chosen(self, answer):
        if answer is None:
            return
        if answer[1] is SEARCH:
            self.session.openWithCallback(self.search, VirtualKeyBoard, title="Nazwa miejscowości (bez polskich znaków też zadziała):")
            return
        choices = [(loc.name, loc) for loc in storage.towns(answer[1])]
        self.session.openWithCallback(self.town_chosen, ChoiceBox, title="Wybierz miejscowość",
                                      list=choices, windowTitle=answer[0])

    def search(self, text):
        if not text:
            return
        found = storage.search_towns(text)
        if not found:
            self.session.openWithCallback(lambda *_: self.edit(), MessageBox,
                                          f"Nie znaleziono miejscowości „{text}”.", MessageBox.TYPE_INFO, timeout=5)
            return
        choices = [(f"{loc.name} (woj. {woj})", loc) for loc, woj in found]
        self.session.openWithCallback(self.town_chosen, ChoiceBox, title=f"Wyniki dla „{text}”: {len(found)}",
                                      list=choices, windowTitle="Wybierz miejscowość")

    def town_chosen(self, answer):
        if answer is None:
            return
        loc = answer[1]
        index = self.current()
        if loc in self.locations and self.locations.index(loc) != index:
            self.refresh(self.locations.index(loc))
            self.session.open(MessageBox, f"{loc.name} już jest na liście.", MessageBox.TYPE_INFO, timeout=3)
            return
        if index is None:
            self.locations.append(loc)
            index = len(self.locations) - 1
        else:
            self.locations[index] = loc
        self.dirty = True
        self.refresh(index)

    # --- leaving -----------------------------------------------------------
    def save(self):
        settings.save_favourites(self.locations)
        self.close(True)

    def exit(self):
        if not self.dirty:
            return self.close(False)
        choices = [("Zapisz i wyjdź", "save"), ("Wyjdź bez zapisywania", "discard"), ("Wróć do edycji", None)]
        self.session.openWithCallback(self.exit_chosen, ChoiceBox, title="Lista została zmieniona.",
                                      list=choices, windowTitle="Zapisać zmiany?")

    def exit_chosen(self, answer):
        action = answer and answer[1]
        if action == "save":
            self.save()
        elif action == "discard":
            self.close(False)
