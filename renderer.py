# -*- coding: utf-8 -*-
"""The meteogram comes from `ummeteo`, a static binary written in Zig (zig/): it fetches
the UM forecast for the location from the API of app.meteo.pl and draws the chart to a
PNG. One binary per architecture lives in bin/ (built by scripts/publish.sh, not in
git; install.sh keeps only the one for the box). No enigma2 imports."""
import os
import platform
import subprocess
import sys
import time

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
WIDTH, HEIGHT = 1280, 720       # design pixels of the chart (zig/src/chart.zig): the whole 720p screen
TIMEOUT = 40                    # seconds for the whole fetch + draw


class RenderError(Exception):
    pass


def arch(machine=None, byteorder=None):
    """Suffix of bin/ummeteo-<arch> for this box, None when there is no build for it."""
    machine = machine or platform.machine()
    byteorder = byteorder or sys.byteorder
    if machine.startswith("mips"):
        return "mipsel" if byteorder == "little" else None
    if machine.startswith("arm"):
        return "arm"
    if machine in ("aarch64", "x86_64"):
        return machine
    return None


def binary():
    suffix = arch()
    if suffix is None:
        raise RenderError(f"Brak programu ummeteo dla procesora {platform.machine()}")
    path = os.path.join(PLUGIN_DIR, "bin", f"ummeteo-{suffix}")
    if not os.access(path, os.X_OK):
        raise RenderError(f"Brak pliku bin/ummeteo-{suffix} we wtyczce")
    return path


def parse_result(stdout):
    """'ok 1590x990 run=1793448000 start=1793451600 steps=60 out=...' -> (run text, (w, h))"""
    fields = stdout.strip().split("\n")[-1].split()
    try:
        if fields[0] != "ok":
            raise ValueError(fields[0])
        w, h = (int(v) for v in fields[1].split("x"))
        values = dict(f.split("=", 1) for f in fields[2:] if "=" in f)
        run = time.strftime("%d.%m.%Y %H UTC", time.gmtime(int(values["run"])))
    except (IndexError, KeyError, ValueError):
        raise RenderError(f"ummeteo: nieznana odpowiedź {stdout.strip()[:80]!r}") from None
    return run, (w, h)


def render(location_id, scale, out_path, title="", note="", run=subprocess.run):
    """Blocking: fetch the newest forecast and draw it to out_path -> (run text, (w, h)).
    `title` (the location name) and `note` ("1/5") go into the chart's header."""
    cmd = [binary(), "--id", str(location_id), "--scale", f"{scale:g}", "--out", out_path, "--timeout", str(TIMEOUT),
           "--title", title, "--note", note]
    try:
        result = run(cmd, capture_output=True, text=True, timeout=TIMEOUT + 10)
    except subprocess.TimeoutExpired:
        raise RenderError("meteo.pl nie odpowiada") from None
    if result.returncode != 0:
        lines = [line.strip() for line in result.stderr.split("\n") if line.strip()]
        message = lines[-1] if lines else f"ummeteo: kod {result.returncode}"
        raise RenderError(message.replace("ummeteo: ", "", 1))
    return parse_result(result.stdout)
