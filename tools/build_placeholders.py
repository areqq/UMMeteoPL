#!/usr/bin/env python3
"""Rebuild loading.png and error.png (chart.placeholder, FullHD scale).

    python3 tools/build_placeholders.py   (from the plugin directory)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
chart = __import__(os.path.basename(ROOT) + ".chart", fromlist=["x"])

for name, title, subtitle, colour in (("loading.png", "Pobieram prognozę...", "meteo.pl, model UM", chart.BLUE),
                                      ("error.png", "Nie udało się pobrać prognozy", "CZERWONY - spróbuj ponownie", chart.RED)):
    with open(os.path.join(ROOT, name), "wb") as f:
        f.write(chart.placeholder(title, subtitle, colour=colour))
    print(name)
