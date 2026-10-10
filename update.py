# -*- coding: utf-8 -*-
"""Self-update from the publishing server (no enigma imports here).

The server (scripts/publish.sh) holds:
  version              line 1: version, line 2: "install.sh <sha256>"
  install.sh           the same script as the console one-liner
  UMMeteoPL.tar.gz     the plugin, verified by install.sh against .sha256
A version different from the installed one is installed by running the
server's install.sh, which replaces the plugin directory.
"""
import hashlib
import os
import subprocess
import tempfile
import urllib.request

from .version import VERSION

BASE_URL = "https://<serwer wtyczki>"
PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
TIMEOUT = 10
INSTALL_TIMEOUT = 300

installed = ""   # version installed during this session, waiting for a GUI restart
failed = ""      # version whose installation failed during this session


class UpdateError(Exception):
    pass


def http_get(url, limit=65536):
    req = urllib.request.Request(url, headers={"User-Agent": f"UMMeteoPL/{VERSION} (enigma2 plugin)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise UpdateError(f"{url}: odpowiedź większa niż {limit} B")
    return data


def parse_version(raw):
    """(version, install.sh sha256) from the server's version file."""
    lines = raw.decode("utf-8", "replace").split("\n")
    version = lines[0].strip()
    if not version or len(version) > 40 or any(c.isspace() or c in "<>" for c in version):
        raise UpdateError(f"nieprawidłowy plik wersji: {version[:60]!r}")
    sha = ""
    for line in lines[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[0] == "install.sh":
            sha = parts[1].lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise UpdateError("w pliku wersji brak sumy install.sh")
    return version, sha


def available(get=http_get):
    """(version, sha) on the server when it should be installed here, else None."""
    version, sha = parse_version(get(BASE_URL + "/version"))
    if version in (VERSION, installed, failed):
        return None
    return version, sha


def install(version, sha, get=http_get, run=subprocess.run):
    """Run the server's install.sh into PLUGIN_DIR; raises UpdateError on failure."""
    global installed, failed
    try:
        script = get(BASE_URL + "/install.sh")
        if hashlib.sha256(script).hexdigest() != sha:
            raise UpdateError("suma kontrolna install.sh się nie zgadza")
        fd, path = tempfile.mkstemp(prefix="ummeteo-install-", suffix=".sh")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(script)
            env = dict(os.environ, UMMETEO_BASE=BASE_URL, UMMETEO_DEST=PLUGIN_DIR)
            result = run(["/bin/sh", path], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=INSTALL_TIMEOUT)
        finally:
            os.unlink(path)
        output = result.stdout.decode("utf-8", "replace").strip()
        print(f"[UMMeteo] install.sh {version}:\n{output}")
        if result.returncode != 0:
            raise UpdateError(output.splitlines()[-1] if output else f"install.sh: kod {result.returncode}")
    except subprocess.TimeoutExpired:
        failed = version
        raise UpdateError(f"install.sh nie skończył się w {INSTALL_TIMEOUT} s")
    except Exception:
        failed = version
        raise
    installed = version
    return version


def check_and_install(get=http_get, run=subprocess.run):
    """Worker-thread entry: installed version, or None when there is nothing new."""
    found = available(get)
    return install(*found, get=get, run=run) if found else None
