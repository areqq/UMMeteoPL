# -*- coding: utf-8 -*-
from Plugins.Plugin import PluginDescriptor

from . import settings  # noqa: F401 - defines config.plugins.UMMeteoPL at boot


def main(session, **kwargs):
    from .Meteo import Meteo
    session.open(Meteo)


def Plugins(**kwargs):
    return [PluginDescriptor(name="UM Meteo.pl", description="Meteogram modelu UM z meteo.pl (ICM UW)",
                             where=[PluginDescriptor.WHERE_PLUGINMENU, PluginDescriptor.WHERE_EXTENSIONSMENU],
                             icon="meteo.png", fnc=main)]
