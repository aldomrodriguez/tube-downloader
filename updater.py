"""Auto-update against GitHub Releases.

Flow: ask the GitHub API for the latest release, compare its tag with
APP_VERSION, download the .exe asset to a temp file, verify it, and hand off to
a tiny batch script that waits for this process to exit, swaps the file and
relaunches. A running .exe can't overwrite itself on Windows, hence the script.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = "aldomrodriguez/tube-downloader"
ASSET_NAME = "TubeDownloader.exe"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = "TubeDownloader-updater"


def parse_version(text):
    """'v1.2.3' -> (1, 2, 3). Non-numeric parts are ignored."""
    return tuple(int(n) for n in re.findall(r"\d+", text or ""))


def can_self_update():
    # Only the packaged .exe can replace itself; running app.py from source can't.
    return getattr(sys, "frozen", False)


def check_latest(current_version, timeout=8):
    """Return update info if GitHub has a newer release, else None.

    Never raises: no internet, rate limits or a missing release just mean
    "no update" — the app must keep working offline.
    """
    try:
        req = urllib.request.Request(API_URL, headers={
            "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except Exception:
        return None

    if data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name", "")
    if parse_version(tag) <= parse_version(current_version):
        return None

    asset = next((a for a in data.get("assets", []) if a.get("name") == ASSET_NAME), None)
    if not asset:
        return None

    digest = asset.get("digest") or ""
    return {
        "version": tag.lstrip("vV"),
        "notes": (data.get("body") or "").strip(),
        "url": asset["browser_download_url"],
        "size": asset.get("size") or 0,
        "sha256": digest[7:].lower() if digest.startswith("sha256:") else None,
    }


def download(info, on_progress=None, should_cancel=None):
    """Download the new .exe to a temp file and verify it. Returns its path."""
    fd, tmp = tempfile.mkstemp(prefix="TubeDownloader-", suffix=".exe")
    os.close(fd)
    sha = hashlib.sha256()
    done = 0
    try:
        req = urllib.request.Request(info["url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            total = info["size"] or int(r.headers.get("Content-Length") or 0)
            while True:
                if should_cancel and should_cancel():
                    raise InterruptedError("cancelado")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if on_progress and total:
                    on_progress(done, total)

        if info["size"] and done != info["size"]:
            raise IOError("La descarga quedó incompleta.")
        if info["sha256"] and sha.hexdigest() != info["sha256"]:
            raise IOError("El archivo descargado no coincide con el publicado.")
        with open(tmp, "rb") as f:
            if f.read(2) != b"MZ":
                raise IOError("El archivo descargado no es un ejecutable válido.")
        return tmp
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def install_and_restart(new_exe):
    """Spawn the swap script. The caller must exit right after this returns."""
    current = Path(sys.executable).resolve()
    backup = current.with_suffix(".old")
    script = Path(tempfile.gettempdir()) / "TubeDownloader-update.cmd"

    # A one-file PyInstaller exe stays locked until both the bootloader and this
    # Python process exit, so retry the move instead of waiting on one PID.
    # `ping` is the delay because `timeout` refuses to run without a console.
    script.write_text(
        "@echo off\r\n"
        "set /a n=0\r\n"
        ":retry\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        f'move /Y "{current}" "{backup}" >nul 2>&1 && goto swap\r\n'
        "set /a n+=1\r\n"
        "if %n% lss 30 goto retry\r\n"
        "goto launch\r\n"
        ":swap\r\n"
        f'move /Y "{new_exe}" "{current}" >nul 2>&1 || move /Y "{backup}" "{current}" >nul\r\n'
        f'del /F /Q "{backup}" >nul 2>&1\r\n'
        ":launch\r\n"
        f'start "" "{current}"\r\n'
        f'del /F /Q "{new_exe}" >nul 2>&1\r\n'
        'del "%~f0"\r\n',
        encoding="mbcs",
    )

    # Without this the relaunched exe would inherit our PyInstaller environment
    # and try to reuse the temp folder that is being deleted as we exit.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("_MEI", "_PYI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"

    subprocess.Popen(
        ["cmd.exe", "/c", str(script)],
        env=env,
        cwd=str(current.parent),
        # A hidden console (not DETACHED_PROCESS): otherwise every `ping`
        # in the loop would pop up its own console window.
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
