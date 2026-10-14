"""Discord webhook and Telegram bot senders."""
import html
from datetime import datetime, timezone

import requests

PLATFORM_INFO = {
    "youtube": {"name": "YouTube", "color": 0xFF0000, "emoji": "▶️"},
    "tiktok": {"name": "TikTok", "color": 0x25F4EE, "emoji": "🎵"},
    "instagram": {"name": "Instagram", "color": 0xE1306C, "emoji": "📸"},
    "twitter": {"name": "X / Twitter", "color": 0x1D9BF0, "emoji": "🐦"},
}
KIND_LABEL = {"video": "New video", "short": "New Short", "reel": "New Reel", "tweet": "New post",
              "reply": "New reply", "repost": "New repost", "post": "New post", "count": "New upload"}


def send(dest, platform, post):
    """Send one post to one destination. Raises on failure."""
    if dest.get("type") == "discord":
        _discord(dest, platform, post)
    elif dest.get("type") == "telegram":
        _telegram(dest, platform, post)
    else:
        raise ValueError(f"Unknown destination type: {dest.get('type')}")


def _discord(dest, platform, post):
    info = PLATFORM_INFO[platform]
    embed = {
        "title": (post["title"] or KIND_LABEL.get(post["kind"], "New post"))[:256],
        "url": post["url"],
        "color": info["color"],
        "author": {"name": f"CarterPCs · {KIND_LABEL.get(post['kind'], 'New post')} on {info['name']}"},
        "footer": {"text": "CarterPCs Monitor"},
    }
    if post.get("thumbnail"):
        embed["image"] = {"url": post["thumbnail"]}
    if post.get("published"):
        embed["timestamp"] = datetime.fromtimestamp(post["published"], timezone.utc).isoformat()
    body = {"username": "CarterPCs Monitor", "embeds": [embed]}
    if dest.get("mention"):
        body["content"] = dest["mention"]
        body["allowed_mentions"] = {"parse": ["everyone", "roles", "users"]}
    r = requests.post(dest["webhook_url"].strip(), json=body, timeout=15)
    if r.status_code >= 300:
        raise RuntimeError(f"Discord returned HTTP {r.status_code}: {r.text[:200]}")


def _telegram(dest, platform, post):
    info = PLATFORM_INFO[platform]
    label = KIND_LABEL.get(post["kind"], "New post")
    text = (f"{info['emoji']} <b>CarterPCs · {label} on {info['name']}</b>\n"
            f"{html.escape(post['title'][:800])}\n\n<a href=\"{html.escape(post['url'])}\">Open on {info['name']}</a>")
    if dest.get("mention"):
        text = html.escape(dest["mention"]) + "\n" + text
    api = f"https://api.telegram.org/bot{dest['bot_token'].strip()}"
    chat_id = str(dest["chat_id"]).strip()
    if post.get("thumbnail"):
        r = requests.post(f"{api}/sendPhoto", timeout=15, data={
            "chat_id": chat_id, "photo": post["thumbnail"], "caption": text[:1024], "parse_mode": "HTML"})
        if r.ok:
            return
        # Some CDNs (Instagram) refuse Telegram's fetch, so fall back to plain text.
    r = requests.post(f"{api}/sendMessage", timeout=15, data={
        "chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    if not r.ok:
        raise RuntimeError(f"Telegram error: {r.json().get('description', r.status_code)}")
