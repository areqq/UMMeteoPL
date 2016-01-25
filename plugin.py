from Plugins.Plugin import PluginDescriptor

def main(session, **kwargs):
	try:
		import Meteo 
		reload(Meteo)

		session.open(Meteo.Meteo)
	except:
		import traceback
		traceback.print_exc()

def Plugins(path, **kwargs):
    p = [PluginDescriptor( name=_("UM Meteo.pl"), description="Meteogram z meteo.pl", where = PluginDescriptor.WHERE_PLUGINMENU,icon="meteo.png", fnc = main)]
    return p

