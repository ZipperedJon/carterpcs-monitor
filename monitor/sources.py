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
    stats, errors = {}, []
    try:
        page = _get(f"https://www.tiktok.com/@{handle}").text
        m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', page, re.S)
        s = json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]["stats"]
        stats = {"followers": s.get("followerCount"), "posts": s.get("videoCount"),
                 "likes": s.get("heartCount"), "following": s.get("followingCount")}
    except Exception as e:
        errors.append(f"Stats: {e}")

    # The creator embed (used for "embed my profile" widgets) lists the latest
    # videos without needing TikTok's signed API.
    page = _get(f"https://www.tiktok.com/embed/@{handle}").text
    m = re.search(r'<script id="__FRONTITY_CONNECT_STATE__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise RuntimeError("TikTok embed layout changed (no video list found)")
    data = json.loads(m.group(1))["source"]["data"]
    videos = next((v["videoList"] for v in data.values() if isinstance(v, dict) and "videoList" in v), [])
    posts = []
    for v in videos:
        vid = str(v["id"])
        posts.append(_post(vid, f"https://www.tiktok.com/@{handle}/video/{vid}",
                           (v.get("desc") or "New TikTok").split("\n")[0][:200],
                           v.get("coverUrl") or v.get("originCoverUrl") or "",
                           int(vid) >> 32,  # TikTok IDs start with the upload time
                           "video"))
    return {"stats": stats, "posts": posts, "warning": "; ".join(errors) or None}


# -------------------------------------------------------------- Instagram --

def _instagram_meta(handle):
    """Follower/post counts from the link-preview tags. Rarely rate limited."""
    page = requests.get(f"https://www.instagram.com/{handle}/", timeout=TIMEOUT,
                        headers={"User-Agent": "facebookexternalhit/1.1"}).text
    m = re.search(r'content="([\d.,KMB]+) Followers, ([\d.,KMB]+) Following, ([\d.,KMB]+) Posts', page)
    if not m:
        raise RuntimeError("Instagram blocked the profile request, will retry next check")
    img = re.search(r'<meta property="og:image" content="([^"]+)"', page)
    return ({"followers": _parse_count(m.group(1)), "following": _parse_count(m.group(2)),
             "posts": _parse_count(m.group(3))}, html.unescape(img.group(1)) if img else "")


def _instagram_api(handle):
    """Real posts with links. Instagram rate limits this hard, so call it sparingly."""
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
        is_reel = n.get("product_type") == "clips"
        path = "reel" if is_reel else "p"
        posts.append(_post(n["shortcode"], f"https://www.instagram.com/{path}/{n['shortcode']}/",
                           caption.split("\n")[0][:200] or "New Instagram post",
                           n.get("thumbnail_src") or n.get("display_url"), n.get("taken_at_timestamp"),
                           "reel" if is_reel else ("video" if n.get("is_video") else "post")))
    stats = {"followers": user["edge_followed_by"]["count"],
             "following": user["edge_follow"]["count"], "posts": media["count"]}
    return stats, posts


IG_GIVE_UP_AFTER = 4  # failed API tries before falling back to a profile-link alert


def fetch_instagram(handle, cache):
    stats, avatar = _instagram_meta(handle)
    count = stats["posts"]
    cache.setdefault("known_count", count)  # first run: baseline, nothing is "new"
    if count < cache["known_count"]:
        cache["known_count"] = count  # a post was deleted
    changed = count > cache["known_count"]
    warning = None
    # Only hit the rate-limited API when there's a new post, or to fill the dashboard.
    if changed or not cache.get("posts"):
        try:
            api_stats, posts = _instagram_api(handle)
            stats.update(api_stats)
            cache.update(posts=posts, known_count=count, tries=0)
        except Exception as e:
            warning = "Instagram is rate limiting post lookups, will retry next check"
            if changed:
                cache["tries"] = cache.get("tries", 0) + 1
                if cache["tries"] >= IG_GIVE_UP_AFTER:
                    # Still blocked: alert anyway so the post isn't missed, linking the profile.
                    fallback = _post(f"count-{count}", f"https://www.instagram.com/{handle}/",
                                     f"New Instagram post (post #{count:,})", avatar, time.time(), "count")
                    cache.update(posts=[fallback] + cache.get("posts", []), known_count=count, tries=0)
    return {"stats": stats, "posts": cache.get("posts", []), "warning": warning}


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
}
