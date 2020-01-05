#!/usr/bin/python -u
# -*- coding: UTF-8 -*-

from Tools.Directories import resolveFilename, fileExists, SCOPE_PLUGINS
from Screens.Screen import Screen
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.ActionMap import ActionMap
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.TextBox import TextBox
from twisted.web.client import getPage, downloadPage
from Components.Console import Console
import os,re

version = '20.01.05'

PluginLocation = "Extensions/UMMeteoPL"
PluginPath = resolveFilename(SCOPE_PLUGINS, PluginLocation)
meteo_ini = PluginPath + '/meteo.ini'

class Meteo(Screen):
    from enigma import getDesktop
    screenWidth = getDesktop(0).size().width()
    if screenWidth and screenWidth == 1920:
        # FHD skin
        skin="""
        <screen name="UMMeteo" position="center,5" size="1365,1066" flags="wfNoBorder" backgroundColor="#00FFFFFF" >
            <widget name="info" position="0,0" size="1620,31" font="Regular;27" halign="center"/>
            <ePixmap position="0,31" size="420,990" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL/leftfhd.png" transparent="1" alphatest="on" scale="1"/>
            <widget name="myPic" position="420,31" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL/meteogramfhd.png" size="945,990" zPosition="1" alphatest="on" scale="1"/>
            <eLabel text="Menu" position="0,1021" size="240,45" zPosition="2" font="Regular;33" halign="center" backgroundColor="blue" valign="center"/>
            <eLabel text="Ulubione" position="240,1021" size="240,45" zPosition="2" font="Regular;33" halign="center" backgroundColor="green" valign="center"/>
            <eLabel text="Info" position="480,1021" size="240,45" zPosition="2" font="Regular;33" halign="center" backgroundColor="yellow" valign="center"/>
            <eLabel name="about" text="www.meteo.pl %s by areq 2019" position="720,1021" size="640,45" zPosition="2" font="Regular;33" halign="right" valign="center"/>
            <eLabel name="pad" text=" " position="1360,1021" size="5,45" zPosition="2" font="Regular;33" halign="center" valign="center"/>
        </screen>""" % version
    else:
        # HD skin
        skin="""
        <screen name="UMMeteo" position="center,5" size="910,710" flags="wfNoBorder" backgroundColor="#00FFFFFF" >
            <widget name="info" position="0,0" size="910,20" font="Regular;18" halign="center"/>
            <ePixmap position="0,20" size="280,660" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL/left.png" transparent="1" alphatest="on"/>
            <widget name="myPic" position="280,20" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL/meteogram.png" size="630,660" zPosition="1" alphatest="on" scale="1"/>
            <eLabel text="Menu" position="0,680" size="160,30" zPosition="2" font="Regular;22" halign="center" backgroundColor="blue" valign="center"/>
            <eLabel text="Ulubione" position="160,680" size="160,30" zPosition="2" font="Regular;22" halign="center" backgroundColor="green" valign="center"/>
            <eLabel text="Info" position="320,680" size="160,30" zPosition="2" font="Regular;22" halign="center" backgroundColor="yellow" valign="center"/>
            <eLabel name="about" text="www.meteo.pl %s by areq 2019" position="480,680" size="426,30" zPosition="2" font="Regular;22" halign="right" valign="center"/>
            <eLabel name="pad" text=" " position="906,680" size="4,30" zPosition="2" font="Regular;22" halign="center" valign="center"/>
        </screen>""" % version

    def __init__(self, session):
        Screen.__init__(self, session)
        self["info"] = Label('Ładuję...')
        self["myPic"] = Pixmap()
        try:
            os.unlink('/tmp/meteo.png')
        except:
            pass
        try:
            os.unlink('/tmp/meteofhd.png')
        except:
            pass
        self["myActionMap"] = ActionMap(["MeteoActions"],
        {
            "ok": self.cancel,
            "cancel": self.cancel,
            "menu": self.menu,
            "blue": self.menu,
            "green": self.next,
            "left": self.prev,
            "right": self.next,
            "start": self.start,
            "info": self.ShowOpis,
            "yellow": self.ShowOpis,
            "list": self.choose,
        }, -1)

        getPage('http://e2.areq.eu.org/ummeteo/version').addCallback(self.updateCB).addErrback(self.errorUpdate)

        self.onLayoutFinish.append(self.layoutFinished)

    def layoutFinished(self):
        from enigma import getDesktop
        screenWidth = getDesktop(0).size().width()
        if screenWidth and screenWidth == 1920:
            self.fhdskin = True
        else:
            self.fhdskin = False
        self.load_ini()

    def load_ini(self):
        self.miejscaFull = []
        self.miejsca = []
        self.active = 0
        try:
            for l in open(meteo_ini):
                if len(l) > 4:
                    self.miejscaFull.append(l.rstrip('\n'))
                    self.miejsca.append(l.split()[0])
        except:
            pass
        if len(self.miejsca) < 1:
            self.miejscaFull = ["2119 Dobre, pow.radziejowski"]
            self.miejsca = [2119]
        self.start_meteo(self.miejsca[0])

    def prev(self):
        self.active -= 1
        if self.active < 0:
            self.active = len(self.miejsca)-1
        #if self.fhdskin:
        #    self["myPic"].instance.setPixmapFromFile(PluginPath + "/meteogramfhd.png")
        #else:
        #    self["myPic"].instance.setPixmapFromFile(PluginPath + "/meteogram.png")
        self.start_meteo(self.miejsca[self.active])

    def next(self):
        self.active += 1
        if self.active >= len(self.miejsca):
            self.active = 0
        #if self.fhdskin:
        #    self["myPic"].instance.setPixmapFromFile(PluginPath + "/meteogramfhd.png")
        #else:
        #    self["myPic"].instance.setPixmapFromFile(PluginPath + "/meteogram.png")
        self.start_meteo(self.miejsca[self.active])

    def start(self):
        self.active = 0
        #if self.fhdskin:
        #    self["myPic"].instance.setPixmapFromFile(PluginPath + "/meteogramfhd.png")
        #else:
        #    self["myPic"].instance.setPixmapFromFile(PluginPath + "/meteogram.png")
        self.start_meteo(self.miejsca[self.active])

    def updateCB(self, html):
        try:
            v = html.split('\n')[0]
            if v > version:
                self.session.openWithCallback(self.upgradeCB, MessageBox, "Dostępna jest nowa wersja pluginu UM Meteo\n %s \n Instalować ?" % v, MessageBox.TYPE_YESNO)
        except:
            pass

    def errorUpdate(self, html):
        print "[UMMeteo] - upgrade problem:", html

    def upgradeCB(self, result = None):
        print "[UMMeteo] - upgrade:", result
        if result:
            print "\n[UMMeteo] - upgrade yes\n"
            downloadPage('http://e2.areq.eu.org/ummeteo/update.py',PluginPath + '/update.py').addCallback(self.goupCB).addErrback(self.errorUpdate)
        else:
            print "[UMMeteo] upgrade cancel\n"

    def goupCB(self, html):
        print "[UMMeteo] - upgrade.py done:", html
        try:
            import update
            reload(update)
            self.session.open(update.DoUpdate) 
        except:
            print "[UMMeteo] - upgrade.py - exception"
            import traceback
            traceback.print_exc() 

    def start_meteo(self, id ):
        print "[UMMeteo] - miasto:", id
        if self.fhdskin:
            self["myPic"].instance.setPixmapFromFile(PluginPath + "/meteogramfhd.png")
        else:
            self["myPic"].instance.setPixmapFromFile(PluginPath + "/meteogram.png")
        self["info"].setText("Ładuję")
        url = "http://www.meteo.pl/um/php/meteorogram_id_um.php?ntype=0u&id=%s" % id
        getPage(url).addCallback(self.infoCB).addErrback(self.error)

    def error(self, error = None):
        if error is not None:
            self["info"].setText(str(error.getErrorMessage())) 

    def infoCB(self, html):
        upng = "http://www.meteo.pl/um/metco/mgram_pict.php?ntype=0u&ffdate=%s&row=%s&col=%s&lang=pl"
        #var fcstdate = "2013080306";var ntype ="0u";var lang ="pl";var id="2119";var act_x = 208;var act_y = 393;
        r = r'.*fcstdate = "(202\d{7})";.*var id="(\d+)";var act_x = (\d+);var act_y = (\d+);.*div id=.model_napis[^\n]+\n[^\n]+\n(.*)\<\/font...div.*'
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
        if self.fhdskin:
            if fileExists("/usr/bin/convert"):
                # make convert - high quality scale
                # v1: no spinner
                convertcmd = "convert /tmp/meteo.png -filter quadratic -resize 945x990\\! -quality 11 /tmp/meteofhd.png"
                # convertcmd = "convert /tmp/meteo.png -filter quadratic -resize 945x990\\! /tmp/meteofhd.bmp"
                Console().ePopen(convertcmd,self.getConvertFinished)
                # v2: spinner...
                #os.system("convert /tmp/meteo.png -filter quadratic -resize 945x990\\! -quality 11 /tmp/meteofhd.png")
                #self["myPic"].instance.setPixmapFromFile("/tmp/meteofhd.png")
            else:
                # load downloaded file - low quality scale
                self["myPic"].instance.setPixmapFromFile("/tmp/meteo.png")
        else:
            self["myPic"].instance.setPixmapFromFile("/tmp/meteo.png")


    def getConvertFinished(self, result, retval, extra_args):
        self["myPic"].instance.setPixmapFromFile("/tmp/meteofhd.png")
        # self["myPic"].instance.setPixmapFromFile("/tmp/meteofhd.bmp")

    def cancel(self):
        # print "[UMMeteo] - cancel\n"
        self.close(None)

    def menu(self):
        try:
            import configure
            reload(configure)
            self.session.openWithCallback(self.poConfigureCB, configure.Configure)
            self.load_ini()
        except:
            import traceback
            traceback.print_exc() 

    def poConfigureCB(self):
        self.load_ini()

    def ShowOpis(self):
        opisFile = PluginPath + '/opis.txt'
        if os.path.isfile(opisFile):
            f = open(opisFile, 'r')
            opisText = f.read()
            f.close()
            Message = opisText
        else:
            Message = '\nBrak informacji'
        self.session.open(TextBox, Message, "UMMeteoPL - informacje")

    def choose(self):
        askList = []
        i = 0
        for l in self.miejscaFull:
            askList.append([l, i])
            i += 1
        dei = self.session.openWithCallback(self.favCB, ChoiceBox, title="Wybierz lokalizację", list=askList)
        dei.setTitle("Lista ulubionych")

    def favCB(self, answer):
        answer = answer and answer[1]
        if answer:
            self.active = answer
            if self.fhdskin:
                self["myPic"].instance.setPixmapFromFile(PluginPath + "/meteogramfhd.png")
            else:
                self["myPic"].instance.setPixmapFromFile(PluginPath + "/meteogram.png")
            self.start_meteo(self.miejsca[self.active])
