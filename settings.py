# -*- coding: utf-8 -*-
"""Plugin settings in enigma2's config tree (/etc/enigma2/settings)."""
import os

from Components.config import ConfigSelection, ConfigSubsection, ConfigText, ConfigYesNo, config, configfile

from . import storage

config.plugins.UMMeteoPL = ConfigSubsection()
cfg = config.plugins.UMMeteoPL
cfg.favourites = ConfigText(default="", fixed_size=False)
cfg.start = ConfigSelection(default="first", choices=[("first", "pierwszą z listy"), ("last", "ostatnio oglądaną")])
cfg.last = ConfigText(default="", fixed_size=False)
cfg.cache = ConfigSelection(default="30", choices=[("10", "10 minut"), ("30", "30 minut"), ("60", "1 godzinę")])
cfg.autoupdate = ConfigYesNo(default=True)


def favourites():
    return storage.parse_favourites(cfg.favourites.value)


def save_favourites(locations):
    cfg.favourites.value = storage.dump_favourites(locations)
    cfg.favourites.save()
    configfile.save()


def remember_last(location_id):
    if cfg.start.value == "last" and cfg.last.value != location_id:
        cfg.last.value = location_id
        cfg.last.save()
        configfile.save()


def migrate():
    """Move meteo.ini of versions up to 20.01.05 into the config tree, once."""
    legacy = storage.read_legacy()
    if legacy is None:
        return
    if not cfg.favourites.value and legacy:
        save_favourites(legacy)
    try:
        os.rename(storage.LEGACY_CONFIG_FILE, storage.LEGACY_CONFIG_FILE + ".migrated")
    except OSError as e:
        print(f"[UMMeteo] cannot rename {storage.LEGACY_CONFIG_FILE}: {e}")


migrate()
