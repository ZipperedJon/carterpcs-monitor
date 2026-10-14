"""Settings, state and the background polling loop."""
import copy
import json
import logging
import os
import threading
import time
from pathlib import Path

from . import notify, sources, updater

log = logging.getLogger("carterpcs")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CARTERPCS_DATA", ROOT / "data"))
SETTINGS_FILE = DATA_DIR / "settings.json"
STATE_FILE = DATA_DIR / "state.json"

PLATFORMS = ["youtube", "tiktok", "instagram", "twitter"]
MAX_POSTS_SHOWN = 30
MAX_SEEN = 500
MAX_HISTORY = 500
MAX_NOTIFY_PER_CHECK = 5  # per platform, so a glitch can't spam a channel

DEFAULT_SETTINGS = {
    "poll_minutes": 10,
    "platforms": {
        "youtube": {"enabled": True, "handle": "actuallycarterpcs", "feed_url": ""},
        "tiktok": {"enabled": True, "handle": "carterpcs", "feed_url": ""},
        "instagram": {"enabled": True, "handle": "carterpcs_", "feed_url": ""},
        "twitter": {"enabled": True, "handle": "carternotpcs", "feed_url": "", "include_reposts": False},
    },
    # Each destination: {id, name, type: discord|telegram, enabled, webhook_url,
    #                    bot_token, chat_id, mention, platforms: [...]}
    "destinations": [],
    "auto_update": True,
    "update_check_minutes": 60,
}


def _merge(defaults, saved):
    out = copy.deepcopy(defaults)
    for k, v in (saved or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class Monitor:
    def __init__(self):
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.settings = _merge(DEFAULT_SETTINGS, _load(SETTINGS_FILE, {}))
        self.state = _load(STATE_FILE, {})
        for p in PLATFORMS:
            self.state.setdefault(p, {"seen": [], "posts": [], "stats": {}, "history": [],
                                      "cache": {}, "error": None, "last_check": None, "seeded": False})
        self.state.setdefault("notify_log", [])
        self.update_status = {"last_check": None, "message": "Not checked yet"}

    # ---------------------------------------------------------- settings --
    def get_settings(self):
        with self.lock:
            return copy.deepcopy(self.settings)

    def save_settings(self, new):
        with self.lock:
            self.settings = _merge(DEFAULT_SETTINGS, new)
            self.settings["poll_minutes"] = max(2, int(self.settings["poll_minutes"]))
            _save(SETTINGS_FILE, self.settings)
        self.wake.set()  # re-check with the new settings straight away

    # ------------------------------------------------------------- state --
    def public_state(self):
        with self.lock:
            out = {}
            for p in PLATFORMS:
                s = self.state[p]
                out[p] = {k: s[k] for k in ("posts", "stats", "history", "error", "last_check")}
                out[p]["handle"] = self.settings["platforms"][p]["handle"]
                out[p]["enabled"] = self.settings["platforms"][p]["enabled"]
            out["notify_log"] = self.state["notify_log"][-30:]
            out["version"] = updater.version()
            out["update"] = self.update_status
            out["poll_minutes"] = self.settings["poll_minutes"]
            return out

    # ------------------------------------------------------------ checks --
    def check_platform(self, p):
        cfg = self.settings["platforms"][p]
        st = self.state[p]
        if cfg["handle"] != st["cache"].get("handle"):
            # Handle changed: forget everything so we don't notify on old posts.
            st.update(seen=[], posts=[], history=[], seeded=False, cache={"handle": cfg["handle"]})

        errors, result = [], {"stats": {}, "posts": []}
        try:
            result = sources.FETCHERS[p](cfg["handle"], st["cache"])
        except Exception as e:
            errors.append(str(e))
        if cfg.get("feed_url"):
            try:
                result["posts"] = sources.fetch_feed(cfg["feed_url"])
            except Exception as e:
                errors.append(f"Custom feed: {e}")

        posts = result["posts"]
        if p == "twitter" and not cfg.get("include_reposts"):
            posts = [x for x in posts if x["kind"] != "repost"]

        new_posts = []
        with self.lock:
            st["error"] = "; ".join(errors) or None
            st["last_check"] = time.time()
            if result["stats"]:
                st["stats"] = {k: v for k, v in result["stats"].items() if v is not None}
                if st["stats"].get("followers"):
                    st["history"].append([int(time.time()), st["stats"]["followers"]])
                    st["history"] = st["history"][-MAX_HISTORY:]
            if posts:
                seen = set(st["seen"])
                new_posts = [x for x in posts if x["id"] not in seen]
                st["seen"] = (st["seen"] + [x["id"] for x in new_posts])[-MAX_SEEN:]
                # Merge with older posts so count-based platforms keep a history.
                by_id = {x["id"]: x for x in st["posts"]}
                for x in posts:
                    old = by_id.get(x["id"])
                    if old and old.get("published"):  # keep first-detected time
                        x = {**x, "published": old["published"]}
                    by_id[x["id"]] = x
                st["posts"] = sorted(by_id.values(), key=lambda x: x.get("published") or 0,
                                     reverse=True)[:MAX_POSTS_SHOWN]
                if not st["seeded"]:
                    st["seeded"] = True  # first run: remember what exists, don't notify
                    new_posts = []
        if new_posts:
            new_posts.sort(key=lambda x: x.get("published") or 0)
            for post in new_posts[-MAX_NOTIFY_PER_CHECK:]:
                self.dispatch(p, post)

    def dispatch(self, platform, post):
        for dest in self.settings["destinations"]:
            if not dest.get("enabled", True) or platform not in dest.get("platforms", []):
                continue
            entry = {"time": time.time(), "platform": platform, "title": post["title"][:120],
                     "destination": dest.get("name") or dest["type"], "ok": True, "error": None}
            try:
                notify.send(dest, platform, post)
            except Exception as e:
                entry.update(ok=False, error=str(e)[:300])
                log.warning("Notify %s failed: %s", entry["destination"], e)
            with self.lock:
                self.state["notify_log"] = (self.state["notify_log"] + [entry])[-100:]

    def check_all(self):
        for p in PLATFORMS:
            if self.settings["platforms"][p]["enabled"]:
                log.info("Checking %s", p)
                self.check_platform(p)
        with self.lock:
            _save(STATE_FILE, self.state)

    # -------------------------------------------------------------- loop --
    def run_forever(self):
        last_update_check = 0
        while True:
            try:
                self.check_all()
            except Exception:
                log.exception("Check failed")
            s = self.settings
            if s["auto_update"] and time.time() - last_update_check > s["update_check_minutes"] * 60:
                last_update_check = time.time()
                self.run_update()
            self.wake.wait(s["poll_minutes"] * 60)
            self.wake.clear()

    def run_update(self):
        self.update_status = updater.check_and_update()
        self.update_status["last_check"] = time.time()
        return self.update_status

    def start(self):
        threading.Thread(target=self.run_forever, daemon=True).start()
