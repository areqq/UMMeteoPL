# UMMeteoPL

Wtyczka enigma2 (Python 3) pokazująca meteogram modelu UM z [meteo.pl](https://www.meteo.pl)
(ICM, Uniwersytet Warszawski) dla listy ulubionych miejscowości, z ostrzeżeniami
meteorologicznymi IMGW-PIB dla powiatu. Bez zależności spoza enigmy (bez `requests`, PIL, ImageMagick).

Instalacja: zawartość repozytorium do `/usr/lib/enigma2/python/Plugins/Extensions/UMMeteoPL/`,
restart GUI. Obsługa: [opis.txt](opis.txt) (też pod klawiszem INFO).

| plik | rola |
|---|---|
| `meteogram.py` | adresy meteo.pl, parsowanie strony, pobieranie (bez zależności od enigmy) |
| `storage.py` | katalog `woj/*`, wyszukiwarka, (de)serializacja ulubionych (bez enigmy) |
| `alerts.py` | ostrzeżenia IMGW-PIB (`danepubliczne.imgw.pl`) dla powiatu (bez enigmy) |
| `teryt.tsv` | id miejscowości → kod TERYT powiatu; generuje `tools/build_teryt.py` z PRG (GUGiK) |
| `settings.py` | `config.plugins.UMMeteoPL` w `/etc/enigma2/settings`, migracja `meteo.ini` |
| `Meteo.py` | ekran meteogramu |
| `setup.py` | ustawienia (`ConfigListScreen`, wygląd ze skórki `Setup`) |
| `configure.py` | edytor listy ulubionych |
| `keymap.xml` | kontekst `MeteoActions` |

Testy (na PC, bez enigmy; uruchamiać z katalogu nadrzędnego):

    python3 -m unittest UMMeteoPL.tests.test_core -v
