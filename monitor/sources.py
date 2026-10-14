"""Fetchers for each platform. No logins or API keys needed.

Each fetcher returns {"stats": {...}, "posts": [...]}. A post is a dict with
id, url, title, thumbnail, published (unix seconds or None) and kind.
"""
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

BROWSER_UA = ("Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
TIMEOUT = 20

session = requests.Session()
session.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"})


def _get(url, **kw):
    r = session.get(url, timeout=TIMEOUT, **kw)
    if r.status_code == 429:
        raise RuntimeError("Rate limited (HTTP 429), will retry next check")
    r.raise_for_status()
    return r


def _post(id, url, title="", thumbnail="", published=None, kind="post"):
    return {"id": str(id), "url": url, "title": title.strip(), "thumbnail": thumbnail or "",
            "published": int(published) if published else None, "kind": kind}


def _parse_count(text):
    """'3.79M' -> 3790000, '2,160' -> 2160."""
    text = text.strip().replace(",", "")
    mult = {"K": 1e3, "M": 1e6, "B": 1e9}.get(text[-1:].upper(), 1)
    if mult != 1:
        text = text[:-1]
    return int(float(text) * mult)


def _iso_ts(s):
    from datetime import datetime
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------- YouTube --

def fetch_youtube(handle, cache):
    page = _get(f"https://www.youtube.com/@{handle}").text
    channel_id = cache.get("channel_id")
    if not channel_id:
        m = re.search(r'"externalId":"(UC[\w-]{22})"', page)
        if not m:
            raise RuntimeError("Could not find YouTube channel ID")
        channel_id = cache["channel_id"] = m.group(1)

    stats = {}
    if m := re.search(r'"([\d.,]+[KMB]?) subscribers"', page):
        stats["followers"] = _parse_count(m.group(1))
    if m := re.search(r'"([\d.,]+[KMB]?) videos"', page):
        stats["posts"] = _parse_count(m.group(1))

    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
          "media": "http://search.yahoo.com/mrss/"}
    feed = ET.fromstring(_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}").content)
    posts = []
    for e in feed.findall("a:entry", ns):
        vid = e.findtext("yt:videoId", "", ns)
        link = e.find("a:link", ns)
        url = link.get("href") if link is not None else f"https://www.youtube.com/watch?v={vid}"
        thumb = e.find("media:group/media:thumbnail", ns)
        posts.append(_post(vid, url, e.findtext("a:title", "", ns),
                           thumb.get("url") if thumb is not None else "",
                           _iso_ts(e.findtext("a:published", "", ns)),
                           "short" if "/shorts/" in url else "video"))
    return {"stats": stats, "posts": posts}


# ----------------------------------------------------------------- TikTok --

def fetch_tiktok(handle, cache):
    page = _get(f"https://www.tiktok.com/@{handle}").text
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise RuntimeError("TikTok page layout changed (no profile data found)")
    info = json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
    s = info.get("stats") or {}
    stats = {"followers": s.get("followerCount"), "posts": s.get("videoCount"),
             "likes": s.get("heartCount"), "following": s.get("followingCount")}
    # TikTok's video list needs signed requests, so detect uploads by the
    # video count going up instead. Add an RSS feed URL in settings for titles.
    posts = []
    count = stats["posts"]
    if count:
        posts.append(_post(f"count-{count}", f"https://www.tiktok.com/@{handle}",
                           f"New TikTok posted (video #{count:,})",
                           info.get("user", {}).get("avatarLarger", ""), time.time(), "count"))
    return {"stats": stats, "posts": posts}


# -------------------------------------------------------------- Instagram --

def fetch_instagram(handle, cache):
    # Best case: the web JSON API gives real posts. It is often rate limited,
    # so fall back to the link-preview tags that Facebook's crawler gets.
    try:
        r = _get("https://www.instagram.com/api/v1/users/web_profile_info/",
                 params={"username": handle},
                 headers={"x-ig-app-id": "936619743392459", "X-Requested-With": "XMLHttpRequest",
                          "Referer": f"https://www.instagram.com/{handle}/"})
        user = r.json()["data"]["user"]
        media = user["edge_owner_to_timeline_media"]
        posts = []
        for edge in media["edges"]:
            n = edge["node"]
            caps = n.get("edge_media_to_caption", {}).get("edges") or []
            caption = caps[0]["node"]["text"] if caps else ""
            kind = "reel" if n.get("product_type") == "clips" else ("video" if n.get("is_video") else "post")
            posts.append(_post(n["shortcode"], f"https://www.instagram.com/p/{n['shortcode']}/",
                               caption.split("\n")[0][:200], n.get("thumbnail_src") or n.get("display_url"),
                               n.get("taken_at_timestamp"), kind))
        stats = {"followers": user["edge_followed_by"]["count"],
                 "following": user["edge_follow"]["count"], "posts": media["count"]}
        return {"stats": stats, "posts": posts}
    except Exception:
        pass

    page = requests.get(f"https://www.instagram.com/{handle}/", timeout=TIMEOUT,
                        headers={"User-Agent": "facebookexternalhit/1.1"}).text
    m = re.search(r'content="([\d.,KMB]+) Followers, ([\d.,KMB]+) Following, ([\d.,KMB]+) Posts', page)
    if not m:
        raise RuntimeError("Instagram blocked the request, will retry next check")
    stats = {"followers": _parse_count(m.group(1)), "following": _parse_count(m.group(2)),
             "posts": _parse_count(m.group(3))}
    img = re.search(r'<meta property="og:image" content="([^"]+)"', page)
    count = stats["posts"]
    posts = [_post(f"count-{count}", f"https://www.instagram.com/{handle}/",
                   f"New Instagram post (post #{count:,})",
                   html.unescape(img.group(1)) if img else "", time.time(), "count")]
    return {"stats": stats, "posts": posts}


# ------------------------------------------------------------- Twitter/X --

def fetch_twitter(handle, cache):
    # FxTwitter is a free public mirror of X's API (the same one fxtwitter.com embeds use).
    headers = {"User-Agent": "carterpcs-monitor (+https://github.com)"}
    user = _get(f"https://api.fxtwitter.com/{handle}", headers=headers).json().get("user") or {}
    stats = {"followers": user.get("followers"), "following": user.get("following"),
             "posts": user.get("tweets"), "likes": user.get("likes")}
    data = _get(f"https://api.fxtwitter.com/2/profile/{handle}/statuses", headers=headers).json()
    posts = []
    for t in data.get("results") or []:
        media = (t.get("media") or {}).get("all") or []
        thumb = ""
        if media:
            thumb = media[0].get("thumbnail_url") or (media[0].get("url") if media[0].get("type") == "photo" else "")
        author = (t.get("author") or {}).get("screen_name", "")
        is_repost = bool(t.get("reposted_by")) or author.lower() != handle.lower()
        title = t.get("text") or ""
        if is_repost:
            title = f"Reposted @{author}: {title}"
        posts.append(_post(t["id"], t.get("url") or f"https://x.com/{handle}/status/{t['id']}",
                           title[:280], thumb, t.get("created_timestamp"),
                           "repost" if is_repost else ("reply" if t.get("replying_to") else "tweet")))
    return {"stats": stats, "posts": posts}


# ----------------------------------------------------- Custom RSS / Atom --

def fetch_feed(url):
    """Generic RSS/Atom reader, e.g. for an RSSHub feed of TikTok videos."""
    root = ET.fromstring(_get(url).content)
    atom = "{http://www.w3.org/2005/Atom}"
    media = "{http://search.yahoo.com/mrss/}"
    items = root.findall(".//item") or root.findall(f"{atom}entry")
    posts = []
    for it in items:
        if it.tag == "item":
            link = it.findtext("link", "")
            title = it.findtext("title", "")
            pid = it.findtext("guid") or link
            date = it.findtext("pubDate")
            try:
                ts = parsedate_to_datetime(date).timestamp() if date else None
            except (TypeError, ValueError):
                ts = None
            desc = it.findtext("description", "")
        else:
            el = it.find(f"{atom}link")
            link = el.get("href", "") if el is not None else ""
            title = it.findtext(f"{atom}title", "")
            pid = it.findtext(f"{atom}id") or link
            ts = _iso_ts(it.findtext(f"{atom}published") or it.findtext(f"{atom}updated") or "")
            desc = it.findtext(f"{atom}content", "") or it.findtext(f"{atom}summary", "")
        thumb = ""
        for tag in (f"{media}thumbnail", f".//{media}thumbnail", f"{media}content", "enclosure"):
            el = it.find(tag)
            if el is not None and el.get("url"):
                thumb = el.get("url")
                break
        if not thumb and (m := re.search(r'<img[^>]+src="([^"]+)"', desc or "")):
            thumb = html.unescape(m.group(1))
        if not title:
            title = re.sub(r"<[^>]+>", " ", html.unescape(desc or ""))[:200]
        posts.append(_post(pid, link, html.unescape(title), thumb, ts, "post"))
    return posts


FETCHERS = {
    "youtube": fetch_youtube,
    "tiktok": fetch_tiktok,
    "instagram": fetch_instagram,
    "twitter": fetch_twitter,
}
