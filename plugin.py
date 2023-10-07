from Plugins.Plugin import PluginDescriptor

def main(session, **kwargs):
	from Plugins.Extensions.UMMeteoPL.Meteo import Meteo
	session.open(Meteo)

def Plugins(path, **kwargs):
    p = [PluginDescriptor( name=_("UM Meteo.pl"), description="Meteogram z meteo.pl", where = PluginDescriptor.WHERE_PLUGINMENU,icon="meteo.png", fnc = main)]
    return p
