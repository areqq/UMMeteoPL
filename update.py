# -*- coding: utf-8 -*-
"""Background self-update from the publishing server (scripts/publish.sh).

Started at GUI start (plugin.py, WHERE_SESSIONSTART): the first check comes
FIRST_CHECK seconds later, then every INTERVAL. When the first line of
<BASE_URL>/version differs from the version on disk, the console one-liner
runs in the background with its output in /dev/null; the new version works
after the next GUI restart.
"""
import base64
import os
import re
import subprocess
import urllib.request

from .version import VERSION

_KEY = b"UMMeteoPL"
# the server address, XOR-ed with _KEY and base64-encoded so it is not in plain text in git;
# install.sh carries the same string (tests pin both)
BASE_URL_ENC = "PTk5FQdfQH82NC4jAFoKATViJSFiMDkoCiQpOh0B"


def unscramble(enc):
    raw = base64.b64decode(enc)
    return bytes(c ^ _KEY[i % len(_KEY)] for i, c in enumerate(raw)).decode()


BASE_URL = unscramble(BASE_URL_ENC)
COMMAND = f"wget -qO- {BASE_URL}/install.sh | sh"
PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
FIRST_CHECK = 120
INTERVAL = 8 * 3600
TIMEOUT = 10
INSTALL_TIMEOUT = 300

_call = None    # pending reactor.callLater


class UpdateError(Exception):
    pass


def http_get(url, limit=4096):
    req = urllib.request.Request(url, headers={"User-Agent": f"UMMeteoPL/{VERSION} (enigma2 plugin)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read(limit)


def parse_version(raw):
    """Version from the first line of the server's version file."""
    version = raw.decode("utf-8", "replace").split("\n")[0].strip()
    if not version or len(version) > 40 or any(c.isspace() or c in "<>" for c in version):
        raise UpdateError(f"nieprawidłowy plik wersji: {version[:60]!r}")
    return version


def installed_version(plugin_dir=None):
    """Version on disk - after an update it is newer than the running VERSION."""
    try:
        with open(os.path.join(plugin_dir or PLUGIN_DIR, "version.py"), encoding="utf-8") as f:
            m = re.search(r'^VERSION = "(.*)"', f.read(), re.M)
        return m.group(1) if m else VERSION
    except OSError:
        return VERSION


def check(get=http_get, run=subprocess.run):
    """Worker thread: run COMMAND when the server has another version. Returns it, or None."""
    remote = parse_version(get(BASE_URL + "/version"))
    local = installed_version()
    if remote == local:
        return None
    env = dict(os.environ, UMMETEO_DEST=PLUGIN_DIR)
    result = run(COMMAND, shell=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 timeout=INSTALL_TIMEOUT)
    if result.returncode != 0:
        raise UpdateError(f"install.sh: kod {result.returncode}")
    return remote


def start():
    """Schedule the background checks."""
    global _call
    from twisted.internet import reactor
    from twisted.internet.threads import deferToThread

    def tick():
        global _call
        _call = reactor.callLater(INTERVAL, tick)
        deferToThread(check).addErrback(lambda f: None)   # silent: no entries in the enigma log

    if _call is None or not _call.active():
        _call = reactor.callLater(FIRST_CHECK, tick)
