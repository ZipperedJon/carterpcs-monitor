"""CarterPCs Monitor - web UI and API."""
import logging
import os
import uuid

from flask import Flask, jsonify, request, send_from_directory

from monitor import notify
from monitor.core import PLATFORMS, Monitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__, static_folder="static")
monitor = Monitor()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/state")
def state():
    return jsonify(monitor.public_state())


@app.get("/api/settings")
def get_settings():
    return jsonify({"settings": monitor.get_settings(), "platforms": PLATFORMS})


@app.post("/api/settings")
def save_settings():
    data = request.get_json(force=True)
    for d in data.get("destinations", []):
        d.setdefault("id", uuid.uuid4().hex[:8])
    monitor.save_settings(data)
    return jsonify({"ok": True})


@app.post("/api/check")
def check_now():
    monitor.wake.set()
    return jsonify({"ok": True})


@app.post("/api/test-destination")
def test_destination():
    dest = request.get_json(force=True)
    sample = {"id": "test", "url": "https://www.youtube.com/@actuallycarterpcs",
              "title": "Test notification from CarterPCs Monitor - it works! 🎉",
              "thumbnail": "", "published": None, "kind": "post"}
    platform = (dest.get("platforms") or ["youtube"])[0]
    try:
        notify.send(dest, platform, sample)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.post("/api/update")
def update_now():
    return jsonify(monitor.run_update())


if __name__ == "__main__":
    monitor.start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), threaded=True)
