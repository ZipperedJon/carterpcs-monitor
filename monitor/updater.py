"""Self-update from GitHub: git pull, reinstall requirements, restart."""
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("carterpcs")
ROOT = Path(__file__).resolve().parent.parent


def _git(*args):
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r.stdout.strip()


def version():
    try:
        return _git("rev-parse", "--short", "HEAD")
    except Exception:
        return "dev"


def check_and_update(apply=True):
    if not (ROOT / ".git").exists():
        return {"ok": False, "message": "Not installed from git, auto-update unavailable"}
    try:
        _git("fetch", "--quiet", "origin")
        local, remote = _git("rev-parse", "HEAD"), _git("rev-parse", "@{u}")
        if local == remote or _git("merge-base", "HEAD", "@{u}") == remote:
            return {"ok": True, "message": "Up to date", "updated": False}
        if not apply:
            return {"ok": True, "message": "Update available", "updated": False}
        _git("pull", "--ff-only", "--quiet")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")],
                       timeout=600, check=False)
        log.info("Updated %s -> %s, restarting", local[:7], remote[:7])
        threading.Timer(2, restart).start()  # give the web request time to respond
        return {"ok": True, "message": f"Updated to {remote[:7]}, restarting…", "updated": True}
    except Exception as e:
        return {"ok": False, "message": f"Update failed: {e}"}


def restart():
    os.execv(sys.executable, [sys.executable, *sys.argv])
