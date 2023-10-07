#!/usr/bin/python -u
# -*- coding: UTF-8 -*-

from Tools.Directories import resolveFilename, SCOPE_PLUGINS
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Components.Label import Label
from Components.ActionMap import ActionMap
from Screens.ChoiceBox import ChoiceBox
from skin import parseColor
# from enigma import eWidget, eLabel, RT_VALIGN_TOP, RT_VALIGN_CENTER, RT_VALIGN_BOTTOM

PluginLocation = "Extensions/UMMeteoPL"
PluginPath = resolveFilename(SCOPE_PLUGINS, PluginLocation)
meteo_ini = PluginPath + '/meteo.ini'

class Configure(Screen):
	from enigma import getDesktop
	screenWidth = getDesktop(0).size().width()
	s=""
	if screenWidth and screenWidth == 1920:
		# FHD skin
		for i in range(10):
			s+= '<widget name="p%i" position="90, %i" size="1260,51" font="Regular;30" valign="center"/>\n' % (i, 135 + (51*i)) 
		skin = """
		<screen name="Configure" position="240,150" size="1440,780" title="Konfiguracja UM Meteo.pl" flags="wfNoBorder">
		<eLabel text="Lista ulubionych miejscowości do sprawdzania prognozy pogody." position="15,7" size="1410,38"  font="Regular;33" halign="center"/>
		<eLabel text="Nawigacja: strzałki Góra/Dół/Prawo/Lewo     OK - edycja pozycji" position="15,45" size="1410,38"  font="Regular;33" halign="center"/>
		<eLabel text="Strona domowa: http://e2.areq.eu.org/ummeteo/" position="10,83" size="1410,38"  font="Regular;33" halign="center"/>
		%s
		<widget name="pages" position="90,645" size="1260,51" font="Regular;20" halign="right" valign="center"/>
		<eLabel text="Usuń" position="0,724" size="270,56" zPosition="2" font="Regular;33" halign="center" backgroundColor="red" valign="center"/>
		<eLabel text="Dodaj stronę" position="270,724" size="270,56" zPosition="2" font="Regular;33" halign="center" backgroundColor="blue" valign="center"/>
		<eLabel text="EXIT/BACK - wyjście bez zapisu" position="540,724" size="630,56" zPosition="2" font="Regular;33" halign="center" valign="center"/>
		<eLabel text="Zapisz i wyjdź" position="1170,724" size="270,56" zPosition="2" font="Regular;33" halign="center" backgroundColor="green" valign="center"/>
		</screen>"""  % s
	else:
		# HD skin
		for i in range(10):
			s+= '<widget name="p%i" position="60, %i" size="840,34" font="Regular;20" valign="center"/>\n' % (i, 90 + (34*i)) 
		skin = """
		<screen name="Configure" position="160,100" size="960,520" title="Konfiguracja UM Meteo.pl" flags="wfNoBorder">
		<eLabel text="Lista ulubionych miejscowości do sprawdzania prognozy pogody." position="10,5" size="940,25"  font="Regular;22" halign="center"/>
		<eLabel text="Nawigacja: strzałki Góra/Dół/Prawo/Lewo     OK - edycja pozycji" position="10,30" size="940,25"  font="Regular;22" halign="center"/>
		<eLabel text="Strona domowa: http://e2.areq.eu.org/ummeteo/" position="10,55" size="940,25"  font="Regular;22" halign="center"/>
		%s
		<widget name="pages" position="60,430" size="840,34" font="Regular;20" halign="right" valign="center"/>
		<eLabel text="Usuń" position="0,485" size="180,35" zPosition="2" font="Regular;22" halign="center" backgroundColor="red" valign="center"/>
		<eLabel text="Dodaj stronę" position="180,485" size="180,35" zPosition="2" font="Regular;22" halign="center" backgroundColor="blue" valign="center"/>
		<eLabel text="EXIT/BACK - wyjście bez zapisu" position="360,485" size="420,35" zPosition="2" font="Regular;22" halign="center" valign="center"/>
		<eLabel text="Zapisz i wyjdź" position="780,485" size="180,35" zPosition="2" font="Regular;22" halign="center" backgroundColor="green" valign="center"/>
		</screen>"""  % s

	def __init__(self, session, args = None):
		self.session = session
		self.miejsca = []
		self.page = 0
		i = 0
		try:
			for l in open(meteo_ini):
				if len(l) > 4:
					self.miejsca.append(l.rstrip('\n'))
					i+=1
		except:
			pass
		self.num_pages = max(1, 1 + ((len(self.miejsca)-1) // 10))
		for k in range(i,self.num_pages*10):
			self.miejsca.append('')
		self.active = 0
		Screen.__init__(self, session)
		for i in range(10):
			self["p%i" % i] = Label('<brak>')
		self["pages"] = Label('<brak>')
		
		self["myActionMap"] =  ActionMap(["MeteoActions"],
		{
		"cancel": self.close, 
		"up": self.up,
		"down" : self.down,
		"left": self.left,
		"right" : self.right,
		"red" : self.red,
		"green" : self.green,
		"blue" : self.addpage,
		"ok" : self.edit
		 }, -1)

		self.onLayoutFinish.append(self.layoutFinished)

	def layoutFinished(self):
		self.print_miejsca()

	def red(self):
		self.miejsca[self.active] = ''
		self.print_miejsca()

	def green(self):
		with open(meteo_ini, 'w') as f:
			for l in self.miejsca:
				if l:
					f.write(l+"\n")
		self.close()

	def up(self):
		self.kursor(-1)

	def down(self):
		self.kursor(1)

	def left(self):
		self.kursor(-10)

	def right(self):
		self.kursor(10)

	def addpage(self):
		self.num_pages += 1
		for k in range((self.num_pages-1)*10,self.num_pages*10):
			self.miejsca.append('')
		self.active = (self.num_pages-1)*10
		self.print_miejsca()

	def kursor(self, kierunek):
		self.active += kierunek
		if self.active < 0:
			if abs(kierunek) == 1:
				self.active = (self.num_pages*10)-1
			else:
				self.active = 0
		if self.active > (self.num_pages*10)-1:
			if abs(kierunek) == 1:
				self.active = 0
			else:
				self.active = (self.num_pages*10)-1
		self.print_miejsca()

	def print_miejsca(self):
		self.page = self.active // 10
		for i in range(10):
			if self.miejsca[i+10*self.page]:
				s = '  %s' % self.miejsca[i+10*self.page]
			else:
				s = '  <niezdefiniowane>'
			if i+10*self.page == self.active:
				self["p%i" %i].instance.setBackgroundColor(parseColor("#0016426e"))
			else:
				self["p%i" %i].instance.clearBackgroundColor()
			# self["p%i" %i].instance.setVAlign(eLabel.alignCenter)
			self["p%i" %i].setText("")
			self["p%i" %i].setText(s)
		p = 'strona %i/%i' % (self.page+1, self.num_pages)
		self["pages"].setText(p)

	def edit(self):	
		askList = [
		['dolnośląskie','dolnoslaskie'],
		['kujawsko-pomorskie','kujawsko-pomorskie'],
		['lubelskie','lubelskie'],
		['lubuskie','lubuskie'],
		['łódzkie','lodzkie'],
		['małopolskie','malopolskie'],
		['mazowieckie','mazowieckie'],
		['opolskie','opolskie'],
		['podkarpackie','podkarpackie'],
		['podlaskie','podlaskie'],
		['pomorskie','pomorskie'],
		['śląskie','slaskie'],
		['świętokrzyskie','swietokrzyskie'],
		['warmińsko-mazurskie','warminsko-mazurskie'],
		['wielkopolskie','wielkopolskie'],
		['zachodniopomorskie','zachodniopomorskie']]

		dei = self.session.openWithCallback(self.wojCB, ChoiceBox, title="Strona domowa: http://e2.areq.eu.org/", list=askList)
		dei.setTitle(_("Wybierz województwo"))

	def wojCB(self, answer):
		answer = answer and answer[1]
		if answer:
			askList = []
			for l in open('%s/woj/%s' % (PluginPath,answer)):
				askList.append([l, l])
			dei = self.session.openWithCallback(self.miejsceCB, ChoiceBox, title="Wybierz miejscowość", list=askList)
			dei.setTitle("Województwo %s" % answer)

	def miejsceCB(self, answer):
		answer = answer and answer[1]
		if answer:
			id = answer.split()[0]
			print("[UMMeteo] - wybrano:", id)
			self.miejsca[self.active] = answer.rstrip('\n')
			self.print_miejsca()
