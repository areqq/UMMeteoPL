#!/usr/bin/python -u
# -*- coding: UTF-8 -*-

from Screens.Screen import Screen
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.ActionMap import ActionMap
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from twisted.web.client import getPage, downloadPage
import os,re

version = '16.01.25'

meteo_ini = '/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL/meteo.ini'

class Meteo(Screen):
    skin="""
        <screen name="UMMeteo" position="center,15" size="920,700" flags="wfNoBorder" backgroundColor="#00FFFFFF" >
            <widget name="info" position="0,0" size="920,20" font="Regular;20"/>
            <widget name="myPic" position="280,20" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL/meteogram.png" size="640,660" zPosition="1" alphatest="on" />
            <ePixmap position="0,50" size="280,660" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL/left.png" transparent="1" alphatest="on" />
            <eLabel text="Menu" position="0,660" size="200,30" zPosition="2" font="Regular;22" halign="center"/>
            <eLabel text="Ulubione" position="200,660" size="200,30" zPosition="2" font="Regular;22" halign="center" backgroundColor="green" />
            <eLabel name="info2" text="www.meteo.pl %s by areq 2016  " position="400,660" size="520,30" zPosition="2" font="Regular;22" halign="right" />
        </screen>""" % version

    def __init__(self, session):
        Screen.__init__(self, session)
        self.load_ini()
        self["info"] = Label('Ładuje...')
        self["myPic"] = Pixmap()
        try:
            os.unlink('/tmp/meteo.png')
        except:
            pass
        self["myActionMap"] = ActionMap(["MeteoActions"],
        {
            "ok": self.cancel,
            "cancel": self.cancel,
            "menu": self.menu,
            "green": self.next,
        }, -1)
        
        getPage('http://e2.areq.eu.org/ummeteo/version').addCallback(self.updateCB).addErrback(self.errorUpdate)

    def load_ini(self):
        self.miejsca = []
        self.active = 0
        try:
            for l in open(meteo_ini):
                if len(l) > 4:
                    self.miejsca.append( l.split()[0])
        except:
            pass
        if len(self.miejsca) < 1:
            self.miejsca = [2119]
        self.start_meteo(self.miejsca[0])

    def next(self):
        self.active += 1
        if self.active >= len(self.miejsca):
            self.active = 0
        self.start_meteo(self.miejsca[self.active])

    def updateCB(self, html):
        try:
            v = html.split('\n')[0]
            if v > version:
                self.session.openWithCallback(self.upgradeCB, MessageBox, "Dostępna jest nowa wersja pluginu UM Meteo\n %s \n Instalować ?" % v, MessageBox.TYPE_YESNO)
        except:
            pass

    def errorUpdate(self, html):
        print "\n[UM Meteto] upgrade problem:", html

    def upgradeCB(self, result = None):
        print "\n[UM Meteto] upgrade:", result
        if result:
            print "\n[UM Meteto] upgrade yes\n"
            downloadPage('http://e2.areq.eu.org/ummeteo/update.py','/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL/update.py').addCallback(self.goupCB).addErrback(self.errorUpdate)
        else:
            print "\n[UM Meteto] upgrade cancel\n"

    def goupCB(self, html):
        print "\n[UM Meteto] upgrade.py done:", html
        try:
            import update
            reload(update)
            self.session.open(update.DoUpdate) 
        except:
            print "\n[UM Meteto] upgrade.py - exception"
            import traceback
            traceback.print_exc() 

    def start_meteo(self, id ):
        print "UMMeteo: miasto:", id
        url = "http://www.meteo.pl/um/php/meteorogram_id_um.php?ntype=0u&id=%s" % id
        getPage(url).addCallback(self.infoCB).addErrback(self.error)

    def error(self, error = None):
        if error is not None:
            self["info"].setText(str(error.getErrorMessage())) 
    
    def infoCB(self, html):
        upng = "http://www.meteo.pl/um/metco/mgram_pict.php?ntype=0u&ffdate=%s&row=%s&col=%s&lang=pl"
        #var fcstdate = "2013080306";var ntype ="0u";var lang ="pl";var id="2119";var act_x = 208;var act_y = 393;
        r = r'.*fcstdate = "(201\d{7})";.*var id="(\d+)";var act_x = (\d+);var act_y = (\d+);.*div id=.model_napis[^\n]+\n[^\n]+\n(.*)\<\/font...div.*'
        m = re.search(r, html, re.M|re.DOTALL)
        if m:
            d, id, x, y, o = m.groups()
            url = upng % (d,y,x)
            o = "%i/%i  #%s Start prognozy %s-%s-%s %s:00     %s" % (self.active + 1, len(self.miejsca), id, d[0:4], d[4:6], d[6:8], d[8:10], o.replace('&nbsp;',' ')) 
            o = o.decode('iso-8859-2').encode("utf-8")
            print "Meteo url png:", url
            downloadPage(url,'/tmp/meteo.png').addCallback(self.pngCB).addErrback(self.error)
        else:
            o ='Problem z pobraniem informacji o meteogramie ;-('
        self["info"].setText(o)

    def pngCB(self, raw):
        self["myPic"].instance.setPixmapFromFile("/tmp/meteo.png") 

    def cancel(self):
        print "[UMMeteo] - cancel\n"
        self.close(None)
    
    def menu(self):
        try:
            import configure
            reload(configure)
            self.session.openWithCallback(self.poConfigureCB, configure.Configure)
        except:
            import traceback
            traceback.print_exc() 

    def poConfigureCB(self):
        self.load_ini()
