#!/usr/bin/python -u
# -*- coding: UTF-8 -*-

from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Components.Label import Label
from Components.ActionMap import ActionMap
from Screens.ChoiceBox import ChoiceBox

meteo_ini = '/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL/meteo.ini'

class Configure(Screen):
	s = ''
	for i in xrange(9):
		s+= '<widget name="p%i" position="10, %i" size="900,40" font="Regular;20"/>\n' % (i, 90 +(42 *i)) 
	skin = """
	<screen name="Configure" position="160,100" size="960,520" title="Konfiguracja UM Meteo.pl" flags="wfNoBorder">
	<eLabel text="Możesz skonfigurować 9 ulubionych miejscowości do sprawdzania prognozy." position="10,5" size="900,25"  font="Regular;22" halign="center"/>
	<eLabel text="Nawigacja: Strzałki Góra/Dół     OK - edycja pozycji" position="10,30" size="900,25"  font="Regular;22" halign="center"/>
	<eLabel text="Strona domowa: http://e2.areq.eu.org/" position="10,55" size="900,25"  font="Regular;22" halign="center"/>
	%s
	<eLabel text="Usuń" position="0,485" size="200,40" zPosition="2" font="Regular;22" halign="center" backgroundColor="red" valign="center"/>
	<eLabel text="EXIT/BACK - wyjście bez zapisu" position="300,485" size="360,40" zPosition="2" font="Regular;22" halign="center" valign="center"/>
	<eLabel text="Zapisz i wyjdź" position="760,485" size="200,40" zPosition="2" font="Regular;22" halign="center" backgroundColor="green" valign="center"/>

	</screen>"""  % s

	def __init__(self, session, args = None):
		self.session = session
		self.miejsca = ['', '', '', '', '', '', '', '', '']
		i = 0
		try:
			for l in open(meteo_ini):
				if len(l) > 4:
					self.miejsca[i] = l
					i+=1
		except:
				pass
		self.active = 0
		Screen.__init__(self, session)
		for i in xrange(9):
			self["p%i" % i] = Label('<brak>')
		
		self["myActionMap"] =  ActionMap(["MeteoActions"],
		{
		"cancel": self.close, 
		"up": self.up,
		"down" : self.down,
		"red" : self.red,
		"green" : self.green,
		"ok" : self.edit
		 }, -1)
		 
		self.print_miejsca()

	def red(self):
		self.miejsca[self.active] = ''
		self.print_miejsca()

	def green(self):
		with open(meteo_ini, 'w') as f:
			for l in self.miejsca:
				if l:
					f.write(l)
		self.close()

	def up(self):
		self.kursor(-1)

	def down(self):
		self.kursor(1)

	def kursor(self, kierunek):
		self.active += kierunek
		if self.active < 0:
			self.active = 8
		if self.active > 8:
			self.active = 0
		self.print_miejsca()

	def print_miejsca(self):
		for i in xrange(9):
			if self.miejsca[i]:
				s = ' %s' % self.miejsca[i]
			else:
				s = ' <niezdefiniowane>'
			if i == self.active:
				s = '*' +s
			else:
				s = ' ' +s
			self["p%i" %i].setText(s)

	def edit(self):	
		askList = [
		['dolnośląskie','dolnoslaskie'],
		['kujawsko-pomorskie','kujawsko-pomorskie'],
		['lubelskie','lubelskie'],
		['lubuskie','lubuskie'],
		['łódzkie''lodzkie'],
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
			for l in open('/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL/woj/%s' % answer):
				askList.append([l, l])
			dei = self.session.openWithCallback(self.miejsceCB, ChoiceBox, title="Wybierz miejscowość", list=askList)
			dei.setTitle("Województwo %s" % answer)

	def miejsceCB(self, answer):
		answer = answer and answer[1]
		if answer:
			id = answer.split()[0]
			print "UMMeteo wybrano", id
			self.miejsca[self.active] = answer
			self.print_miejsca()
