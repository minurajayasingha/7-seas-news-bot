#!/usr/bin/env python3
"""
7 Seas News bot
---------------
Runs on GitHub Actions every ~15 minutes (and stays online LISTEN_MINUTES to answer Telegram fast):
  1. Reads your Telegram button taps (Post now / Queue / Skip)
  2. Publishes approved posts to the Facebook Page (now, or at the next time slot)
  3. Every 2 hours: collects news from trusted RSS feeds, keeps only stories
     confirmed by 2+ outlets, asks Gemini to write a neutral post, makes the
     image, and sends it to your Telegram for approval.

All settings you might want to change are in the CONFIG section below.
"""

import io
import zipfile
import shutil
import subprocess
import tempfile
import json
import math
import os
import random
import re
import sys
import time
import hashlib
import html
import traceback
import signal
import unicodedata
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import feedparser
import requests
from urllib.parse import urlparse
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# All settings (colors, sources, times, topics) are in bot/settings.py
from settings import *  # noqa: E402,F401,F403

# =============================================================================
# SECRETS (set in GitHub > Settings > Secrets and variables > Actions)
# =============================================================================

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip()
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "").strip()
FB_TOKEN = os.environ.get("FB_PAGE_TOKEN", "").strip()
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "").strip()   # optional
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "").strip()  # optional
FORCE_DRAFT = os.environ.get("FORCE_DRAFT", "").strip().lower() in ("1", "true", "yes")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT, "state", "state.json")
FONT_DIR = os.path.join(ROOT, "fonts")
LOGO_FILE = os.path.join(ROOT, "assets", "logo.png")

HTTP = requests.Session()
HTTP.headers["User-Agent"] = "Mozilla/5.0 (compatible; 7SeasNewsBot/1.0)"

W, H = 1080, 1350  # Facebook portrait post


def now_utc():
    return datetime.now(timezone.utc)


def log(*a):
    print(f"[{now_utc():%H:%M:%S}]", *a, flush=True)


# =============================================================================
# STATE (saved in state/state.json and committed back to the repo)
# =============================================================================

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    s.setdefault("tg_offset", 0)
    s.setdefault("drafts", {})
    s.setdefault("seen_links", [])
    s.setdefault("recent_topics", [])   # [[iso_time, [keywords], draft_id]]
    s.setdefault("last_draft_at", None)
    s.setdefault("last_slot", None)
    return s


def save_state(s):
    cutoff = now_utc() - timedelta(days=4)
    s["drafts"] = {
        k: d for k, d in s["drafts"].items()
        if datetime.fromisoformat(d["created_at"]) > cutoff
    }
    s["seen_links"] = s["seen_links"][-2000:]
    topic_cut = now_utc() - timedelta(days=3)
    s["recent_topics"] = [t for t in s["recent_topics"]
                          if datetime.fromisoformat(t[0]) > topic_cut][-300:]
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1, ensure_ascii=False)


# =============================================================================
# TELEGRAM
# =============================================================================

def tg(method, files=None, **data):
    for k, v in list(data.items()):
        if isinstance(v, (dict, list)):
            data[k] = json.dumps(v)
    r = HTTP.post(f"https://api.telegram.org/bot{TG_TOKEN}/{method}",
                  data=data, files=files, timeout=60)
    j = r.json()
    if not j.get("ok"):
        log(f"Telegram {method} error:", j.get("description"))
    return j


def tg_text(text):
    return tg("sendMessage", chat_id=TG_CHAT, text=text[:4000],
              parse_mode="HTML", disable_web_page_preview="true")


def reel_allowed(d):
    """🎬 Reel only for drafts with a real photo (people / place), unless REELS_ONLY_GOOD_PHOTOS is off."""
    if not REELS_ENABLED:
        return False
    if not REELS_ONLY_GOOD_PHOTOS:
        return True
    bg = (d or {}).get("bg") or {}
    return bg.get("type") in ("photo", "people") and bool(bg.get("photos"))


def draft_buttons(pid, d=None):
    first = [{"text": "🚀 Post now", "callback_data": f"now:{pid}"},
             {"text": "🕒 Queue", "callback_data": f"queue:{pid}"}]
    if reel_allowed(d):
        first.insert(1, {"text": "🎬 Reel", "callback_data": f"reel:{pid}"})
    return {"inline_keyboard": [
        first,
        [{"text": "🔄 Other photo", "callback_data": f"photo:{pid}"},
         {"text": "❌ Skip", "callback_data": f"skip:{pid}"}],
    ]}


def tg_status(draft, label, cancel=False):
    """Replace the buttons under a draft with a status label (and optional Cancel)."""
    if draft.get("tg_message_id"):
        rows = [[{"text": label, "callback_data": "noop"}]]
        if cancel:
            rows.append([{"text": "↩️ Cancel", "callback_data": f"cancel:{draft['id']}"}])
        tg("editMessageReplyMarkup", chat_id=TG_CHAT, message_id=draft["tg_message_id"],
           reply_markup={"inline_keyboard": rows})


def tg_reply(draft, text):
    """Send a small message as a reply to the draft (deleted later with the draft)."""
    j = tg("sendMessage", chat_id=TG_CHAT, text=text, parse_mode="HTML",
           reply_to_message_id=draft.get("tg_message_id", ""),
           allow_sending_without_reply="true", disable_web_page_preview="true")
    if j.get("ok"):
        draft.setdefault("extra_msgs", []).append(j["result"]["message_id"])
    return j


def tg_clear(draft):
    """Remove a finished draft (and its little reply messages) from the bot chat."""
    for mid in [draft.get("tg_message_id")] + draft.get("extra_msgs", []):
        if mid:
            tg("deleteMessage", chat_id=TG_CHAT, message_id=mid)
    draft["extra_msgs"] = []
    draft["cleared"] = True


def log_to_channel(state, d, fb_link):
    """Copy a published post to your 'published posts' channel (if linked)."""
    ch = state.get("log_channel")
    now = now_utc()
    text = (f"✅ <b>Published</b> · {ny_now():%b %d} · {ny_time(now)} New York · {lk_time(now)} Sri Lanka\n\n"
            f"<b>{html.escape(d['headline'])}</b>\n"
            f"<i>{html.escape(', '.join(d['sources']))}</i>"
            + (f"\n{news_time_text(d)}" if d.get("news_time") else "")
            + (f"\n\n🔗 <a href=\"{fb_link}\">Open on Facebook</a>" if fb_link else ""))
    d["log_text"] = text   # kept so the stats line can be added under it later
    if ch:
        j = tg("sendPhoto", chat_id=ch, photo=d["tg_file_id"], caption=text, parse_mode="HTML")
        if j.get("ok"):
            d.update(log_chat=ch, log_msg_id=j["result"]["message_id"], log_photo=True)
            return True
    j = tg_text(text)   # no channel linked (or it failed): tell you in the bot chat
    if j.get("ok"):
        d.update(log_chat=TG_CHAT, log_msg_id=j["result"]["message_id"], log_photo=False)
    return False


# ---------- Post stats (likes / comments / shares / reach) ----------

def short_num(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return str(n)


def fb_get(path, **params):
    r = HTTP.get(f"https://graph.facebook.com/{path}", params=dict(params, access_token=FB_TOKEN), timeout=30)
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"].get("message", str(j["error"])))
    return j


REACH_METRICS = ["post_total_media_view_unique", "post_impressions_unique"]


def fb_post_stats(state, post_id):
    """Reactions, comments, shares (+ reach if Facebook allows it) for one published post."""
    j = fb_get(post_id, fields="reactions.summary(total_count).limit(0),"
                               "comments.summary(total_count).limit(0),shares")
    s = {"likes": j.get("reactions", {}).get("summary", {}).get("total_count", 0),
         "comments": j.get("comments", {}).get("summary", {}).get("total_count", 0),
         "shares": j.get("shares", {}).get("count", 0)}
    if not state.get("reach_off"):
        metrics = [state["reach_metric"]] if state.get("reach_metric") else REACH_METRICS
        refused = 0
        for metric in metrics:
            try:
                data = fb_get(f"{post_id}/insights", metric=metric).get("data") or []
                if data:
                    s["reach"] = data[0]["values"][0]["value"]
                    state["reach_metric"] = metric
                    break
            except Exception as e:
                refused += 1
                log("Reach not available with", metric, ":", e)
        if refused == len(metrics) and not state.get("reach_metric"):
            state["reach_off"] = True   # Facebook refuses reach for this Page token: stop asking
    return s


def stats_line(s):
    line = (f"📊 👍 {short_num(s['likes'])} · 💬 {short_num(s['comments'])} · "
            f"🔁 {short_num(s['shares'])}")
    if s.get("reach") is not None:
        line += f" · 👀 {short_num(s['reach'])} reached"
    return line


def update_post_stats(state, force=False):
    """Refresh the numbers of recent published posts and show them under each post in the channel."""
    now = now_utc()
    last = state.get("last_stats_at")
    if not force and last and now - datetime.fromisoformat(last) < timedelta(minutes=STATS_EVERY_MINUTES - 5):
        return
    state["last_stats_at"] = now.isoformat()
    for d in state["drafts"].values():
        if d.get("status") != "posted" or not d.get("fb_post_id") or not d.get("posted_at"):
            continue
        if now - datetime.fromisoformat(d["posted_at"]) > timedelta(days=STATS_DAYS):
            continue
        try:
            s = fb_post_stats(state, d["fb_post_id"])
        except Exception as e:
            log("Stats error:", d["id"], e)
            continue
        changed = s != d.get("stats")
        d["stats"] = s
        d["stats_at"] = now.isoformat()
        if changed and d.get("log_msg_id") and d.get("log_text"):
            text = f"{d['log_text']}\n\n{stats_line(s)}\n<i>Updated {lk_time(now)} Sri Lanka</i>"
            if d.get("log_photo"):
                tg("editMessageCaption", chat_id=d["log_chat"], message_id=d["log_msg_id"],
                   caption=text[:1024], parse_mode="HTML")
            else:
                tg("editMessageText", chat_id=d["log_chat"], message_id=d["log_msg_id"],
                   text=text[:4000], parse_mode="HTML", disable_web_page_preview="true")


def stats_report(state):
    now = now_utc()
    posts = [d for d in state["drafts"].values() if d.get("status") == "posted" and d.get("posted_at")
             and now - datetime.fromisoformat(d["posted_at"]) <= timedelta(hours=24)]
    if not posts:
        return "📊 No posts published in the last 24 hours."
    score = lambda d: sum((d.get("stats") or {}).get(k, 0) for k in ("likes", "comments", "shares"))
    posts.sort(key=score, reverse=True)
    tot = {k: sum((d.get("stats") or {}).get(k, 0) for d in posts) for k in ("likes", "comments", "shares")}
    rows = []
    for n, d in enumerate(posts[:10], 1):
        link = f"https://www.facebook.com/{d['fb_post_id']}" if d.get("fb_post_id") else ""
        title = html.escape(d["headline"][:70])
        rows.append(f"{n}. " + (f'<a href="{link}">{title}</a>' if link else title) + "\n    "
                    + (stats_line(d["stats"]) if d.get("stats") else "📊 no numbers yet"))
    return (f"📊 <b>Last 24 hours</b> · {len(posts)} posts\n"
            f"Total: 👍 {short_num(tot['likes'])} · 💬 {short_num(tot['comments'])} · "
            f"🔁 {short_num(tot['shares'])}\n\n" + "\n\n".join(rows))


def tiktok_caption(d):
    """Short caption for TikTok: headline, summary, hashtags (TikTok captions can't have links)."""
    tags = " ".join("#" + re.sub(r"[^A-Za-z0-9_]", "", t) for t in d.get("hashtags", [])[:3]
                    if re.sub(r"[^A-Za-z0-9_]", "", t))
    head = f"🚨 BREAKING: {d['headline']}" if d.get("breaking") else d["headline"]
    text = "\n\n".join(x for x in with_follow_line([head, d.get("summary", "")])
                         + [f"{tags} {BRAND_HASHTAG} {TIKTOK_HASHTAGS}".strip()] if x)
    return text[:1000]


def send_to_tiktok_channel(state, d, image_bytes):
    """Send the post as a full-quality 1080x1920 file + caption to your TikTok channel (if linked)."""
    ch = state.get("tiktok_channel")
    if not ch:
        return False
    stamp = ny_now().strftime("%Y-%m-%d_%H%M") + "NY"
    j = tg("sendDocument", chat_id=ch, caption=tiktok_caption(d),
           files={"document": (f"7seas_{stamp}_{d['id']}.jpg", story_image(image_bytes), "image/jpeg")})
    return bool(j.get("ok"))


def ny_now():
    """Current time in New York (the page's home time zone)."""
    return now_utc().astimezone(ZoneInfo(SLOT_TIMEZONE))


def ny_day(iso):
    return datetime.fromisoformat(iso).astimezone(ZoneInfo(SLOT_TIMEZONE)).date()


def send_day_pack(state, day, so_far=False):
    """All posts published on one New York day, sent as just 2 messages to the content channel:
    1) the list of titles (+ "End of <day>")   2) ONE zip file: a folder named after the day
       (e.g. "2026-11-10 Tuesday") with every image of the day in order (DAY_PACK_SIZE)."""
    ch = state.get("tiktok_channel") or TG_CHAT
    posts = sorted([d for d in state["drafts"].values()
                    if d.get("status") == "posted" and d.get("posted_at") and ny_day(d["posted_at"]) == day],
                   key=lambda d: d["posted_at"])
    title = f"{day:%A, %b} {day.day}, {day.year}"
    if not posts:
        tg("sendMessage", chat_id=ch, parse_mode="HTML",
           text=f"📅 <b>{title}</b> (New York): no posts" + (" yet." if so_far else "."))
        return
    heads = [f"{n}. {d['headline']}" for n, d in enumerate(posts, 1)]
    end = (f"\n\n⏳ <b>So far</b> — the full pack comes after midnight New York." if so_far
           else f"\n\n✅ <b>End of {day:%b} {day.day}</b> (New York)")
    tg("sendMessage", chat_id=ch, parse_mode="HTML", disable_web_page_preview="true",
       text=(f"📅 <b>{title}</b> (New York) · {len(posts)} post{'s' if len(posts) != 1 else ''}\n\n"
             + html.escape("\n".join(heads))[:3800] + end))

    # ONE zip: a folder named after the day with every image of the day, in posting order
    folder = f"{day:%Y-%m-%d} {day:%A}"
    tall = str(DAY_PACK_SIZE).lower().replace(":", "x") != "4x5"
    parts, cur, size = [], [], 0
    for n, d in enumerate(posts, 1):
        try:
            img = tg_download(d["tg_file_id"])
            data = story_image(img) if tall else img
        except Exception as e:
            log("Day pack image failed:", d["id"], e)
            continue
        if cur and size + len(data) > 45 * 1024 * 1024:   # Telegram bots can send files up to 50 MB
            parts.append(cur)
            cur, size = [], 0
        cur.append((f"{folder}/7seas_{day:%Y-%m-%d}_{n:02d}.jpg", data))
        size += len(data)
    if cur:
        parts.append(cur)
    for i, files in enumerate(parts, 1):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:   # photos are already compressed
            for name, data in files:
                z.writestr(name, data)
        part = f"_part{i}" if len(parts) > 1 else ""
        tg("sendDocument", chat_id=ch, caption=(f"📦 {day:%b} {day.day} · {len(files)} images"
                                                + (f" · part {i}/{len(parts)}" if len(parts) > 1 else "")
                                                + (" · so far" if so_far else "")),
           files={"document": (f"7seas_{day:%Y-%m-%d}_{day:%A}{'_so-far' if so_far else ''}{part}.zip",
                               buf.getvalue(), "application/zip")})


def day_packs_due(state):
    """After midnight in New York, send the pack of the day that just ended (once)."""
    yesterday = ny_now().date() - timedelta(days=1)
    done = state.get("day_pack_done")
    if not done:   # first time: start with yesterday
        done = (yesterday - timedelta(days=1)).isoformat()
    day = datetime.fromisoformat(done).date() + timedelta(days=1)
    while day <= yesterday:
        if day >= yesterday - timedelta(days=2):   # posts older than that are no longer in memory
            send_day_pack(state, day)
        state["day_pack_done"] = day.isoformat()
        day += timedelta(days=1)


def lk_time(t):
    return t.astimezone(ZoneInfo("Asia/Colombo")).strftime("%I:%M %p").lstrip("0")


def ny_time(t):
    return t.astimezone(ZoneInfo(SLOT_TIMEZONE)).strftime("%I:%M %p").lstrip("0")


def ago_text(t):
    mins = int((now_utc() - t).total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    h, m = divmod(mins, 60)
    return f"{h}h {m}m ago" if m else f"{h}h ago"


def news_time_text(d):
    """When the outlets first reported the story, in Sri Lanka time."""
    if not d.get("news_time"):
        return ""
    first = datetime.fromisoformat(d["news_time"])
    last = datetime.fromisoformat(d["news_latest"]) if d.get("news_latest") else first
    hours = (now_utc() - last).total_seconds() / 3600
    dot = "🟢" if hours < 1 else ("🟡" if hours <= 3 else "🔴")
    txt = f"{dot} <b>Latest:</b> {lk_time(last)} Sri Lanka ({ago_text(last)})"
    if lk_time(first) != lk_time(last):
        txt += f" · first reported {lk_time(first)}"
    return txt


def when_text(t):
    now = now_utc()
    day = t.astimezone(ZoneInfo("Asia/Colombo")).date()
    today = now.astimezone(ZoneInfo("Asia/Colombo")).date()
    d = "today" if day == today else ("tomorrow" if day == today + timedelta(days=1) else f"{day:%b %d}")
    return f"{lk_time(t)} Sri Lanka {d}  ({ny_time(t)} New York)"


def set_commands_once(state):
    if state.get("commands_set") == 7:
        return
    tg("setMyCommands", commands=[
        {"command": "news", "description": "Look for fresh news right now"},
        {"command": "day", "description": "Today's posts as one TikTok pack"},
        {"command": "queue", "description": "What's queued and when it posts"},
        {"command": "status", "description": "Bot summary"},
        {"command": "stats", "description": "Likes, comments, shares (last 24h)"},
        {"command": "new", "description": "Make your own post"},
        {"command": "pause", "description": "Stop automatic news"},
        {"command": "resume", "description": "Start automatic news again"},
        {"command": "channel", "description": "Link the published-posts channel"},
        {"command": "tiktok", "description": "Link the TikTok files channel"},
        {"command": "help", "description": "How to use the bot"},
    ])
    state["commands_set"] = 7


def tg_download(file_id):
    j = tg("getFile", file_id=file_id)
    path = j["result"]["file_path"]
    r = HTTP.get(f"https://api.telegram.org/file/bot{TG_TOKEN}/{path}", timeout=60)
    r.raise_for_status()
    return r.content


# =============================================================================
# 1) READ BUTTON TAPS FROM TELEGRAM
# =============================================================================

def find_draft_by_message(state, message_id, caption=""):
    """The draft you replied to: by its message number, or else by its headline (first line)."""
    for d in state["drafts"].values():
        if d.get("tg_message_id") == message_id and d["status"] in ("pending", "queued"):
            return d
    headline = (caption or "").strip().split("\n")[0].strip()
    if headline:
        same = [d for d in state["drafts"].values()
                if d["status"] in ("pending", "queued") and d.get("headline", "").strip() == headline]
        if same:
            d = max(same, key=lambda x: x["created_at"])
            if message_id and message_id not in d.get("extra_msgs", []):
                d.setdefault("extra_msgs", []).append(message_id)   # delete that copy later too
            return d
    return None


def other_photo(state, d):
    """🔄 Other photo: rebuild the post with a different picture."""
    if not d.get("img_post"):
        tg_reply(d, "I can't find another photo for this one. Reply to the post with your own photo 📷")
        return
    used = set(d.get("used_urls", [])) | set(bg_urls(d.get("bg", {})))
    new_bg = choose_background(dict(d["img_post"], headline=d["headline"]), exclude=used, prefer_scene=True)
    if new_bg.get("type") == d.get("bg", {}).get("type") and not (set(bg_urls(new_bg)) - used):
        tg_reply(d, "No better photo found 🙁 — reply to the post with your own photo 📷")
        return
    new = {k: v for k, v in d.items()
           if k not in ("tg_message_id", "tg_file_id", "status", "queued_at", "post_now", "attempts", "extra_msgs")}
    new["bg"] = new_bg
    new["used_urls"] = sorted(used | set(bg_urls(new_bg)))
    new["id"] = hashlib.sha1(f"{d['id']}{time.time()}".encode()).hexdigest()[:10]
    new["created_at"] = now_utc().isoformat()
    if send_draft(state, new):
        d["status"] = "replaced"
        tg_clear(d)
        log("Other photo for", d["headline"])


def handle_reply(state, msg, d):
    """You replied to a draft with a photo (new image) or text (new headline)."""
    new = {k: v for k, v in d.items()
           if k not in ("tg_message_id", "tg_file_id", "status", "queued_at", "post_now", "attempts", "extra_msgs")}
    photo_id = None
    if msg.get("photo"):
        photo_id = msg["photo"][-1]["file_id"]
    elif str(msg.get("document", {}).get("mime_type", "")).startswith("image/"):
        photo_id = msg["document"]["file_id"]

    if photo_id:
        new["bg"] = {"type": "photo", "photos": [{"tg_file_id": photo_id, "credit": ""}]}
        what = "image"
    elif (msg.get("text") or "").strip() and not msg["text"].startswith("/"):
        new["headline"] = msg["text"].strip().rstrip(".")[:120]
        what = "headline"
    else:
        return
    new["id"] = hashlib.sha1(f"{d['id']}{time.time()}".encode()).hexdigest()[:10]
    new["created_at"] = now_utc().isoformat()
    if send_draft(state, new):
        d["status"] = "replaced"
        d.setdefault("extra_msgs", []).append(msg["message_id"])  # your reply message too
        tg_clear(d)
        log("Draft updated with new", what)


URL_RE = re.compile(r"https?://\S+")


def fetch_article(url):
    """Title, description and text of a news article you sent."""
    r = HTTP.get(url, timeout=25)
    r.raise_for_status()
    page = r.text

    def meta(name):
        for pat in (rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)',
                    rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(name)}["\']'):
            m_ = re.search(pat, page, re.I)
            if m_:
                return html.unescape(m_.group(1)).strip()
        return ""

    t = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    title = meta("og:title") or (clean_html(t.group(1)) if t else "")
    paras = [clean_html(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", page, re.I | re.S)]
    text = " ".join(p for p in paras if len(p) > 60)[:3000]
    site = meta("og:site_name") or urlparse(url).netloc.replace("www.", "")
    return {"title": title, "desc": meta("og:description") or meta("description"), "text": text, "site": site}


def handle_manual(state, msg):
    """You sent a link and/or a photo with a headline → make a post from it."""
    raw = (msg.get("text") or msg.get("caption") or "").strip()
    photo_id = None
    if msg.get("photo"):
        photo_id = msg["photo"][-1]["file_id"]
    elif str(msg.get("document", {}).get("mime_type", "")).startswith("image/"):
        photo_id = msg["document"]["file_id"]
    urls = URL_RE.findall(raw)
    lines = [ln.strip() for ln in URL_RE.sub("", raw).splitlines() if ln.strip()]
    breaking = False
    if lines and re.match(r"^breaking\b", lines[0], re.I):
        breaking = True
        lines[0] = re.sub(r"^breaking\s*[:\-–]?\s*", "", lines[0], flags=re.I)
        lines = [ln for ln in lines if ln]
    my_headline = lines[0].rstrip(".") if lines else ""
    my_text = " ".join(lines[1:])

    d = {"id": hashlib.sha1(f"{raw}{time.time()}".encode()).hexdigest()[:10],
         "created_at": now_utc().isoformat(), "manual": True, "label": "WORLD", "hashtags": [],
         "hook": "", "key_points": [], "breaking": breaking, "sources": [], "link": "", "links": []}
    if urls:
        url = urls[0].rstrip(").,")
        art = fetch_article(url)
        c = {"items": [{"source": art["site"], "title": art["title"],
                        "summary": f"{art['desc']} {art['text']}"[:2800]}]}
        post = gemini_write_neutral(c)
        if post.get("skip_reason") and not my_headline:
            tg_text("⚠️ I couldn't write a neutral headline for this link ("
                    f"{html.escape(post['skip_reason'])}). Reply to the draft with your own headline.")
        d.update({
            "headline": my_headline or str(post["headline"]).strip().rstrip("."),
            "summary": my_text or str(post["summary"]).strip(),
            "label": str(post.get("label") or "WORLD").upper()[:18],
            "hashtags": [str(t) for t in (post.get("hashtags") or [])][:3],
            "hook": clean_hook(dict(post, breaking=breaking or post.get("breaking"))),
            "key_points": [str(k).strip() for k in (post.get("key_points") or []) if str(k).strip()][:3],
            "breaking": breaking or bool(post.get("breaking")),
            "sources": [art["site"]], "link": url, "links": [[art["site"], url]],
        })
        bg_post = dict(post, headline=d["headline"])
    else:
        if not my_headline:
            tg_text("To make a post, send me:\n• a <b>news link</b> (I write the post), or\n"
                    "• a <b>photo</b> with a caption: first line = headline, next lines = text.\n"
                    "Start with <b>BREAKING:</b> for breaking news.")
            return
        d.update({"headline": my_headline, "summary": my_text})
        bg_post = None
    if bg_post:
        d["img_post"] = {k: bg_post.get(k) for k in ("headline", "people", "image_query", "image_queries", "image_style", "location")}
    if photo_id:
        d["bg"] = {"type": "photo", "photos": [{"tg_file_id": photo_id, "credit": ""}]}
    elif bg_post:
        d["bg"] = choose_background(bg_post)
    else:
        d["bg"] = {"type": "brand", "photos": []}
    if send_draft(state, d):
        tg("deleteMessage", chat_id=TG_CHAT, message_id=msg["message_id"])
        log("Manual draft made:", d["headline"])


def process_telegram(state, wait=0):
    """Handle new button taps and messages. wait = seconds to wait for new ones (long polling)."""
    j = tg("getUpdates", offset=state["tg_offset"], timeout=wait,
           allowed_updates=["callback_query", "message"])
    for u in j.get("result", []):
        state["tg_offset"] = u["update_id"] + 1

        cq = u.get("callback_query")
        if cq:
            chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
            if chat_id != TG_CHAT:
                continue  # ignore anyone else
            data = cq.get("data", "")
            tg("answerCallbackQuery", callback_query_id=cq["id"])
            if ":" not in data:
                continue
            action, pid = data.split(":", 1)
            d = state["drafts"].get(pid)
            if not d:
                continue
            if action == "cancel" and d["status"] == "queued":
                d["status"] = "pending"
                d.pop("queued_at", None)
                d.pop("post_now", None)
                d.pop("make_reel", None)
                tg("editMessageReplyMarkup", chat_id=TG_CHAT, message_id=d["tg_message_id"],
                   reply_markup=draft_buttons(pid, d))
                tg_reply(d, "↩️ Cancelled. It's back to waiting for your choice.")
                continue
            if d["status"] != "pending":
                continue
            if action == "photo":
                other_photo(state, d)
                continue
            if action == "skip":
                d["status"] = "skipped"
                tg_clear(d)
                log("Skipped", pid)
            elif action in ("now", "queue", "reel") and duplicate_blocked(
                    state, d, {"now": "🚀 Post now", "queue": "🕒 Queue", "reel": "🎬 Reel"}[action]):
                continue
            elif action in ("now", "reel"):
                d["status"] = "queued"
                d["queued_at"] = now_utc().isoformat()
                d["post_now"] = True
                if action == "reel" and reel_allowed(d):
                    d["make_reel"] = True
                    left = REELS_PER_DAY - reels_today(state)
                    tg_status(d, "🎬 Posting + making Reel…" if left > 0 else "🚀 Posting now (Reel limit reached)…")
                else:
                    tg_status(d, "🚀 Posting now…", cancel=False)
                log("Approved", pid, action)
            elif action == "queue":
                d["status"] = "queued"
                d["queued_at"] = now_utc().isoformat()
                d["post_now"] = False
                plan = dict((x["id"], t) for x, t in queue_schedule(state))
                t = plan.get(pid)
                pos = list(plan).index(pid) + 1 if pid in plan else "?"
                tg_status(d, f"🕒 Queued · {lk_time(t)} SL" if t else "🕒 Queued", cancel=True)
                warn = ""
                if t and t > news_age_limit(d):
                    warn = ("\n\n⚠️ The news will be more than "
                            f"{QUEUE_EXPIRE_HOURS} hours old by then, so it will probably be removed "
                            "before its turn. Tap ↩️ Cancel and use 🚀 Post now if you want it out.")
                tg_reply(d, f"🕒 <b>Queued</b> (#{pos} in line)\nWill post at <b>{when_text(t)}</b>{warn}"
                         if t else "🕒 Queued")
                log("Approved", pid, "queue")
            continue

        msg = u.get("message")
        if not msg or str(msg.get("chat", {}).get("id")) != TG_CHAT:
            continue

        fwd = msg.get("forward_from_chat") or (msg.get("forward_origin") or {}).get("chat")
        if fwd and fwd.get("type") == "channel":
            kind = "tiktok_channel" if state.pop("linking", None) == "tiktok" else "log_channel"
            state[kind] = fwd["id"]
            what = ("TikTok files (9:16) + captions" if kind == "tiktok_channel" else "Published posts")
            t = tg("sendMessage", chat_id=fwd["id"],
                   text=f"✅ 7 Seas News bot connected. {what} will appear here.")
            if t.get("ok"):
                tg_text(f"✅ Channel <b>{html.escape(fwd.get('title', ''))}</b> linked. "
                        + ("Every published post will be sent there as a TikTok-size file with its caption."
                           if kind == "tiktok_channel" else "Every published post will be logged there."))
            else:
                state.pop(kind, None)
                tg_text("⚠️ I can't post in that channel yet. Add me to the channel as an "
                        "<b>admin</b> (with 'Post messages'), then forward a message again.")
            continue

        rep = msg.get("reply_to_message")
        if rep:
            d = find_draft_by_message(state, rep.get("message_id"), rep.get("caption") or rep.get("text") or "")
            if d:
                try:
                    handle_reply(state, msg, d)
                except Exception as e:
                    tg_text(f"⚠️ Could not update that post: {html.escape(str(e))[:300]}")
            else:
                tg_text("That post can't be changed anymore (already posted, skipped or replaced).")
            continue

        raw = (msg.get("text") or msg.get("caption") or "").strip()
        has_photo = bool(msg.get("photo")) or str(msg.get("document", {}).get("mime_type", "")).startswith("image/")
        if has_photo or (raw and not raw.startswith("/")):
            try:
                handle_manual(state, msg)
            except Exception as e:
                tg_text(f"⚠️ Could not make that post: <code>{html.escape(str(e))[:300]}</code>")
            continue

        text = raw.lower()
        if text.startswith("/pause"):
            state["paused"] = True
            tg_text("⏸ Paused. I won't look for new news until you send /resume.\n"
                    "(Queued posts still publish, and you can still send your own posts.)")
        elif text.startswith("/resume"):
            state["paused"] = False
            tg_text("▶️ Resumed. I'll send new news again.")
        elif text.startswith("/new") and not text.startswith("/news"):
            tg_text("✍️ <b>Make your own post</b>\n\n"
                    "<b>Option 1 — a link:</b> paste a news article link. I read it and write the post.\n"
                    "Add a line of text above the link to use your own headline.\n\n"
                    "<b>Option 2 — a photo:</b> send a photo with a caption:\n"
                    "first line = headline, next lines = text.\n\n"
                    "Start with <b>BREAKING:</b> for breaking news.\n"
                    "I'll send it back with the buttons to approve.")
        elif text.startswith("/queue"):
            plan = queue_schedule(state)
            if not plan:
                tg_text("📭 Nothing is queued right now.")
            else:
                rows = [f"{n}. <b>{html.escape(d['headline'])}</b>\n    🕒 Posts: {when_text(t)}"
                        + (f"\n    🕐 News: {lk_time(datetime.fromisoformat(d['news_time']))} SL "
                           f"({ago_text(datetime.fromisoformat(d['news_time']))})" if d.get("news_time") else "")
                        for n, (d, t) in enumerate(plan, 1)]
                tg_text("🗓 <b>Queue</b>\n\n" + "\n\n".join(rows) +
                        "\n\nTo cancel one, tap ↩️ Cancel under that post.")
        elif text.startswith("/channel"):
            state.pop("linking", None)  # next forwarded channel = published-posts channel
            tg_text("📢 <b>Published-posts channel</b>\n"
                    "1. Create a Telegram channel (e.g. '7 Seas – Published')\n"
                    "2. Channel info → Administrators → Add admin → add this bot\n"
                    "3. Post any message in the channel and <b>forward it to me</b>\n\n"
                    + ("Currently linked ✅" if state.get("log_channel") else "Not linked yet."))
        elif text.startswith("/tiktok"):
            if "off" in text.lower():
                state.pop("tiktok_channel", None)
                state.pop("linking", None)
                tg_text("🎵 TikTok channel unlinked. Posts won't be sent there any more.")
            else:
                state["linking"] = "tiktok"
                tg_text("🎵 <b>Content channel</b>\n"
                        "After midnight New York, the day's pack is sent there: the list of titles "
                        "+ ONE zip file with a folder of all the day's images.\n\n"
                        "1. Create a Telegram channel (e.g. '7 Seas – TikTok')\n"
                        "2. Channel info → Administrators → Add admin → add this bot\n"
                        "3. Post any message in the channel and <b>forward it to me</b> now\n\n"
                        + ("Currently linked ✅ (send /tiktok off to unlink)"
                           if state.get("tiktok_channel") else "Not linked yet."))
        elif text.startswith("/day"):
            tg_text("📦 Sending today's pack so far" + (" to your content channel…" if state.get("tiktok_channel") else "…"))
            send_day_pack(state, ny_now().date(), so_far=True)
        elif text.startswith("/news"):
            state["news_now"] = True
            tg_text("🔎 Looking for fresh news now…")
        elif text.startswith("/stats"):
            try:
                update_post_stats(state, force=True)
            except Exception as e:
                log("Stats error:", e)
            tg_text(stats_report(state))
        elif text.startswith("/status"):
            q = [d for d in state["drafts"].values() if d["status"] == "queued"]
            p = [d for d in state["drafts"].values() if d["status"] == "pending"]
            tg_text(f"📊 <b>{BRAND_NAME} bot</b>\n"
                    f"Waiting for your approval: {len(p)}\n"
                    f"Queued to post: {len(q)}\n"
                    f"Next time slot: {next_slot_text()}\n"
                    f"Automatic news: {'⏸ paused' if state.get('paused') else '▶️ on'}")
        elif text.startswith("/start") or text.startswith("/help"):
            tg_text("👋 I send you news posts to approve.\n\n"
                    "🚀 <b>Post now</b> – publishes within a minute\n"
                    "🕒 <b>Queue</b> – publishes at the next US time slot\n"
                    "🔄 <b>Other photo</b> – tries a different picture\n"
                    "❌ <b>Skip</b> – drops it\n\n"
                    "✏️ <b>Change a post:</b> reply to it with\n"
                    "• a <b>photo</b> → new background image\n"
                    "• <b>text</b> → new headline\n"
                    "I send back the new version to approve.\n\n"
                    "✍️ <b>Your own post:</b> send a news link, or a photo with a headline (/new)\n\n"
                    "/news – look for fresh news right now\n"
                    "/day – today's posts (New York day) as one pack for TikTok\n"
                    "/queue – what's queued and when it posts\n"
                    "/pause · /resume – stop/start automatic news\n"
                    "/channel – link a channel that logs every published post\n"
                    "/tiktok – link a content channel that gets the daily pack (titles + 1 zip file)\n"
                    "/stats – likes, comments and shares of the last 24 hours\n"
                    "/status – bot summary")


# =============================================================================
# 2) PUBLISH TO FACEBOOK
# =============================================================================

def slot_times_around(now):
    tz = ZoneInfo(SLOT_TIMEZONE)
    local = now.astimezone(tz)
    out = []
    for day in (-1, 0, 1):
        base = (local + timedelta(days=day)).date()
        for s in POST_SLOTS:
            hh, mm = map(int, s.split(":"))
            out.append(datetime(base.year, base.month, base.day, hh, mm, tzinfo=tz))
    return sorted(out)


def current_slot(now):
    """Most recent slot that started within the last 3 hours, or None."""
    past = [t for t in slot_times_around(now) if t <= now]
    if past and now - past[-1] <= timedelta(hours=3):
        return past[-1]
    return None


def next_slot_text():
    now = now_utc()
    nxt = [t for t in slot_times_around(now) if t > now][0]
    lk = nxt.astimezone(ZoneInfo("Asia/Colombo"))
    return f"{nxt:%I:%M %p} New York  ({lk:%I:%M %p} Sri Lanka)"


def facebook_post_photo(image_bytes, caption):
    r = HTTP.post(
        f"https://graph.facebook.com/{FB_PAGE_ID}/photos",
        data={"message": caption, "access_token": FB_TOKEN, "published": "true"},
        files={"source": ("post.jpg", image_bytes, "image/jpeg")},
        timeout=120,
    )
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"].get("message", str(j["error"])))
    return j.get("post_id") or j.get("id")


# =============================================================================
# SINGLE-STORY REELS (🎬 Reel button) — 1080x1920, 30 fps, H.264 + AAC (typing / breaking sounds)
# =============================================================================

RW, RH, FPS = 1080, 1920, 30
GRAPH_VERSION = "v25.0"                # Graph API version for the Reels upload
REEL_IMG_Y = 285                       # where the 1080x1350 post sits in the 9:16 frame


def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg                # optional fallback (pip install imageio-ffmpeg)
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError("ffmpeg is not installed")


def reel_frames_setup(d):
    """Background (blur top + post without headline + bottom colour), headline layout and end card."""
    lay = {}
    label = "BREAKING NEWS" if d.get("breaking") else d.get("label", "WORLD")
    clean = Image.open(io.BytesIO(render_image(d["headline"], label, d.get("sources", []), d["bg"],
                                               hide_headline=True, layout=lay))).convert("RGB")
    frame = Image.new("RGB", (RW, RH), BLACK)
    # top: blurred, 45 % darker zoom of the post's photo area
    photo_area = clean.crop((0, 120, W, int(H * 0.55)))
    top = cover(photo_area, RW, REEL_IMG_Y + 80, 0.5).filter(ImageFilter.GaussianBlur(28))
    top = Image.blend(top, Image.new("RGB", top.size, BLACK), 0.45)
    frame.paste(top, (0, 0))
    # bottom: the post's own bottom colour
    strip = clean.crop((0, H - 6, W, H)).resize((1, 1), Image.LANCZOS).getpixel((0, 0))
    frame.paste(Image.new("RGB", (RW, RH - REEL_IMG_Y - H), strip), (0, REEL_IMG_Y + H))
    frame.paste(clean, (0, REEL_IMG_Y))
    return frame, lay


def reel_end_card():
    card = Image.new("RGB", (RW, RH), BLACK)
    dr = ImageDraw.Draw(card)
    y = 700
    if os.path.exists(LOGO_FILE):
        logo = Image.open(LOGO_FILE).convert("RGBA")
        lw = 560
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        card.paste(logo, ((RW - lw) // 2, y - logo.height - 70), logo)
    else:
        dr.text((RW // 2, y - 120), "7 SEAS NEWS", font=font("Poppins-Bold.ttf", 90), fill=WHITE, anchor="mm")
    dr.rectangle([RW // 2 - 70, y, RW // 2 + 70, y + 8], fill=RED)
    dr.text((RW // 2, y + 110), "FOLLOW FOR MORE", font=font("Poppins-Bold.ttf", 92), fill=WHITE, anchor="mm")
    sub = "VERIFIED WORLD NEWS · EVERY DAY"
    sf = font("Poppins-Medium.ttf", 36)
    sw = spaced_width(dr, sub, sf, 4)
    spaced(dr, ((RW - sw) / 2, y + 190), sub, sf, (200, 200, 205), 4)
    return card


AUDIO_SR = 48000


def _add(buf, start, samples):
    i0 = int(start * AUDIO_SR)
    for k, v in enumerate(samples):
        i = i0 + k
        if 0 <= i < len(buf):
            buf[i] += v


def _key_click(rng, space=False):
    """One keyboard click: short bright noise tick + a small low 'thock' (made from scratch)."""
    n = int(0.045 * AUDIO_SR)
    tone = rng.uniform(120, 170) if space else rng.uniform(190, 280)
    amp = rng.uniform(0.75, 1.0) * (1.15 if space else 1.0)
    out, lp, prev = [], 0.0, 0.0
    for k in range(n):
        t = k / AUDIO_SR
        noise = rng.uniform(-1, 1)
        hp = noise - prev                                    # simple high-pass → crisp tick
        prev = noise
        lp += 0.35 * (hp - lp)
        tick = lp * math.exp(-t / 0.0045) * 0.55
        thock = math.sin(2 * math.pi * tone * t) * math.exp(-t / 0.012) * (0.5 if space else 0.3)
        out.append((tick + thock) * amp)
    return out


def _breaking_sting():
    """Short original news-alert sound: low hit + three bright rising notes."""
    out = [0.0] * int(1.0 * AUDIO_SR)
    for k in range(int(0.7 * AUDIO_SR)):                     # low hit with falling pitch
        t = k / AUDIO_SR
        f = 48 + 40 * math.exp(-t / 0.08)
        out[k] += math.sin(2 * math.pi * f * t) * math.exp(-t / 0.22) * 0.9
    for start, f, length in ((0.02, 784.0, 0.22), (0.20, 988.0, 0.22), (0.38, 1319.0, 0.55)):
        i0 = int(start * AUDIO_SR)
        for k in range(int(length * AUDIO_SR)):
            t = k / AUDIO_SR
            env = min(1.0, t / 0.004) * math.exp(-t / (length * 0.45))
            v = (math.sin(2 * math.pi * f * t) + 0.35 * math.sin(4 * math.pi * f * t)
                 + 0.12 * math.sin(6 * math.pi * f * t))
            out[i0 + k] += v * env * 0.32
    return out


def _whoosh(length=0.6, seed=7):
    """Soft air whoosh for the end-card change."""
    rng = random.Random(seed)
    n, out, lp = int(length * AUDIO_SR), [], 0.0
    for k in range(n):
        x = k / n
        cut = 0.02 + 0.25 * math.sin(math.pi * x)            # filter opens then closes
        lp += cut * (rng.uniform(-1, 1) - lp)
        out.append(lp * math.sin(math.pi * x) ** 2 * 0.9)
    return out


def reel_audio(seconds, key_times, breaking, whoosh_at):
    """Mono 16-bit WAV: typing clicks, breaking sting, end whoosh. Silent if sounds are off."""
    import wave
    import array
    buf = [0.0] * int(seconds * AUDIO_SR)
    rng = random.Random(len(key_times))
    if REEL_BREAKING_SOUND and breaking:
        _add(buf, 0.05, _breaking_sting())
    if REEL_TYPING_SOUND:
        for t, ch in key_times:
            _add(buf, t + rng.uniform(-0.006, 0.006), _key_click(rng, ch == " "))
        _add(buf, whoosh_at - 0.3, _whoosh())
    peak = max(1e-9, max(abs(v) for v in buf))
    gain = min(1.0, 0.89 / peak) * max(0.0, min(1.0, REEL_SOUND_VOLUME))
    pcm = array.array("h", (int(max(-1.0, min(1.0, v * gain)) * 32767) for v in buf))
    mem = io.BytesIO()
    with wave.open(mem, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(AUDIO_SR)
        w.writeframes(pcm.tobytes())
    return mem.getvalue()


def make_reel(d, seconds=None):
    """Build the Reel video for one post and return the MP4 bytes."""
    seconds = max(6, int(seconds or REEL_SECONDS))
    base, lay = reel_frames_setup(d)
    end = reel_end_card()
    lines, size = lay["lines"], lay["size"]
    hf = font("Poppins-Bold.ttf", size)
    x0, y0, lh = lay["x"], lay["y"] + REEL_IMG_Y, lay["line_h"]
    total_chars = sum(len(ln) for ln in lines)

    n_frames = seconds * FPS
    breaking = bool(d.get("breaking"))
    t_type0 = int((1.1 if breaking and REEL_BREAKING_SOUND else 0.4) * FPS)   # typing starts (after the sting)
    type_frames = int(min(4.5, max(1.8, total_chars * 0.055)) * FPS)
    end_start = n_frames - int(2.6 * FPS)                    # end card
    fade = int(0.4 * FPS)

    def shown_at(f):
        return 0 if f < t_type0 else min(total_chars, int((f - t_type0) / type_frames * total_chars) + 1)

    text = "".join(lines)
    key_times, last = [], 0
    for f in range(end_start):                               # one click per new letter
        now = shown_at(f)
        if now > last:
            key_times.append((f / FPS, text[now - 1]))
            last = now

    measure = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}", "-r", str(FPS), "-i", "-",
           "-i", "AUDIO",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000", "-t", str(seconds), "-movflags", "+faststart"]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "reel.mp4")
        wav = os.path.join(tmp, "sound.wav")
        with open(wav, "wb") as fh:
            fh.write(reel_audio(seconds, key_times, breaking, end_start / FPS))
        cmd = [wav if c == "AUDIO" else c for c in cmd]
        proc = subprocess.Popen(cmd + [out], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        cache = {}
        try:
            for f in range(n_frames):
                if f >= end_start + fade:
                    img = end
                else:
                    shown = shown_at(f)
                    blink_on = shown < total_chars or (f // 15) % 2 == 0     # cursor blinks when done
                    key = (shown, blink_on)
                    if key not in cache:
                        img = base.copy()
                        dr = ImageDraw.Draw(img)
                        left, y, cx, cy = shown, y0, x0, y0
                        for ln in lines:
                            part = ln[:max(0, left)]
                            if part:
                                dr.text((x0 + 2, y + 3), part, font=hf, fill=(0, 0, 0))
                                dr.text((x0, y), part, font=hf, fill=WHITE)
                            if left > 0:
                                cx, cy = x0 + measure.textlength(part, font=hf), y
                            left -= len(ln)
                            y += lh
                            if left <= 0:
                                break
                        if blink_on:
                            dr.rectangle([cx + 6, cy + int(size * 0.18), cx + 6 + max(5, size // 12),
                                          cy + int(size * 1.12)], fill=RED)
                        cache = {key: img}                           # keep memory small
                    img = cache[key]
                    if f >= end_start:                               # cross-fade into the end card
                        img = Image.blend(img, end, (f - end_start + 1) / fade)
                proc.stdin.write(img.tobytes())
            proc.stdin.close()
            err = proc.stderr.read().decode(errors="ignore")
            if proc.wait() != 0:
                raise RuntimeError("ffmpeg failed: " + err[-300:])
        except BrokenPipeError:
            proc.wait()
            raise RuntimeError("ffmpeg stopped: " + proc.stderr.read().decode(errors="ignore")[-300:])
        return open(out, "rb").read()


def reel_caption(d):
    """Headline, one-line summary, FOLLOW_LINE, 3–5 lowercase hashtags."""
    first = re.split(r"(?<=[.!?])\s+", str(d.get("summary", "")).strip())[0] if d.get("summary") else ""
    tags = ["#" + re.sub(r"[^A-Za-z0-9_]", "", t).lower() for t in d.get("hashtags", [])[:3]]
    tags += [BRAND_HASHTAG.lower()] + REEL_HASHTAGS.lower().split()
    tags = [t for t in dict.fromkeys(tags) if len(t) > 1][:5]
    head = f"🚨 BREAKING: {d['headline']}" if d.get("breaking") else d["headline"]
    return "\n\n".join(x for x in with_follow_line([head, first]) + [" ".join(tags)] if x)


def facebook_post_reel(video_bytes, caption):
    """Facebook Reels for Pages: start → upload to rupload.facebook.com → finish (PUBLISHED)."""
    base = f"https://graph.facebook.com/{GRAPH_VERSION}/{FB_PAGE_ID}/video_reels"
    j = HTTP.post(base, data={"upload_phase": "start", "access_token": FB_TOKEN}, timeout=60).json()
    if "error" in j or not j.get("video_id"):
        raise RuntimeError("Reel start: " + str(j.get("error", {}).get("message", j)))
    vid = j["video_id"]
    up = j.get("upload_url") or f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}/{vid}"
    r = HTTP.post(up, data=video_bytes, timeout=300, headers={
        "Authorization": f"OAuth {FB_TOKEN}", "offset": "0", "file_size": str(len(video_bytes))})
    u = r.json() if r.text.strip().startswith("{") else {"error": {"message": r.text[:200]}}
    if not u.get("success"):
        raise RuntimeError("Reel upload: " + str(u.get("error", {}).get("message", u)))
    j = HTTP.post(base, timeout=60, data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                          "description": caption, "access_token": FB_TOKEN}).json()
    if "error" in j or not j.get("success", True):
        raise RuntimeError("Reel finish: " + str(j.get("error", {}).get("message", j)))
    return vid


def reels_today(state):
    return state.get("reels_count", {}).get(ny_now().date().isoformat(), 0)


def publish_reel(state, d):
    """After the post is live: make + publish its Reel (if under REELS_PER_DAY) and log the link."""
    day = ny_now().date().isoformat()
    if reels_today(state) >= REELS_PER_DAY:
        tg_text(f"🎬 Reel limit reached ({REELS_PER_DAY} today, New York day). The post is live, "
                f"but no Reel was made for: <b>{html.escape(d['headline'])}</b>")
        return
    try:
        video = make_reel(d)
        vid = facebook_post_reel(video, reel_caption(d))
    except Exception as e:
        log("Reel error:", e)
        tg_text(f"⚠️ The post is live, but the Reel failed:\n<code>{html.escape(str(e))[:500]}</code>\n\n"
                "If it mentions a permission, your Page token may need the pages_manage_posts and "
                "publish_video permissions (make a new token in the Graph API Explorer).")
        return
    counts = state.setdefault("reels_count", {})
    counts[day] = counts.get(day, 0) + 1
    for k in sorted(counts)[:-7]:            # keep one week
        counts.pop(k)
    d["fb_reel_id"] = vid
    link = f"https://www.facebook.com/reel/{vid}"
    log("Reel published", d["id"], vid)
    now = now_utc()
    text = (f"🎬 <b>Reel published</b> · {ny_now():%b %d} · {ny_time(now)} New York · {lk_time(now)} Sri Lanka\n\n"
            f"<b>{html.escape(d['headline'])}</b>\n"
            f"Reels today: {counts[day]}/{REELS_PER_DAY}\n\n🔗 <a href=\"{link}\">Open the Reel</a>")
    ch = state.get("log_channel")
    if not (ch and tg("sendMessage", chat_id=ch, text=text, parse_mode="HTML").get("ok")):
        tg_text(text)


def story_wanted(d):
    """Should this post also go to the Facebook Story? (SHARE_TO_STORY in settings.py)"""
    mode = str(SHARE_TO_STORY).strip().lower()
    if mode in ("all", "true", "yes"):
        return True
    if mode == "breaking":
        return bool(d.get("breaking"))
    return False


def story_image(image_bytes):
    """Put the 1080x1350 post image in the middle of a 1080x1920 black Story canvas."""
    post = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    post = post.resize((1080, round(post.height * 1080 / post.width)))
    canvas = Image.new("RGB", (1080, 1920), BLACK)
    canvas.paste(post, (0, (1920 - post.height) // 2))
    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=92)
    return out.getvalue()


def facebook_post_story(image_bytes):
    """Share an image to the Page's Facebook Story (upload unpublished photo, then publish it as a Story)."""
    r = HTTP.post(
        f"https://graph.facebook.com/{FB_PAGE_ID}/photos",
        data={"access_token": FB_TOKEN, "published": "false"},
        files={"source": ("story.jpg", story_image(image_bytes), "image/jpeg")},
        timeout=120,
    )
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"].get("message", str(j["error"])))
    r = HTTP.post(
        f"https://graph.facebook.com/{FB_PAGE_ID}/photo_stories",
        data={"photo_id": j["id"], "access_token": FB_TOKEN},
        timeout=120,
    )
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"].get("message", str(j["error"])))
    return j.get("post_id") or j.get("id")


def news_age_limit(d):
    """The moment this post's news becomes too old to publish (QUEUE_EXPIRE_HOURS after the latest report).
    Your own posts have no report time, so the time you made them counts."""
    t = d.get("news_latest") or d.get("news_time") or d.get("created_at")
    return datetime.fromisoformat(t) + timedelta(hours=QUEUE_EXPIRE_HOURS)


def find_duplicate(state, d, loose=False):
    """A queued or published post (last 3 days) about the same story as d, or None.
    loose=True also matches looser look-alikes (used only for a warning on new drafts)."""
    mine = keywords(d.get("headline", ""))
    links = {u for _, u in d.get("links", [])} | ({d["link"]} if d.get("link") else set())
    cutoff = now_utc() - timedelta(days=3)
    for o in state["drafts"].values():
        if o is d or o.get("status") not in ("queued", "posted"):
            continue
        if datetime.fromisoformat(o.get("posted_at") or o.get("queued_at") or o["created_at"]) < cutoff:
            continue
        other_links = {u for _, u in o.get("links", [])} | ({o["link"]} if o.get("link") else set())
        theirs = keywords(o.get("headline", ""))
        shared = mine & theirs
        same_words = len(shared) >= 3 and (loose or len(shared) >= 0.5 * min(len(mine), len(theirs)))
        if (links & other_links) or same_words:
            return o
    return None


def duplicate_blocked(state, d, button):
    """Stop the first tap if the same story is already queued/posted; a second tap goes ahead."""
    o = find_duplicate(state, d)
    if not o or d.get("dup_ok"):
        return False
    d["dup_ok"] = True   # next tap = "yes, I'm sure"
    if o["status"] == "posted":
        when = f"was already <b>published</b> at {when_text(datetime.fromisoformat(o['posted_at']))}"
    else:
        plan = dict((x["id"], t) for x, t in queue_schedule(state))
        t = plan.get(o["id"])
        when = "is already <b>queued</b>" + (f" for {when_text(t)}" if t else "")
    tg_reply(d, f"✋ <b>Looks like the same story</b>\n\n“{html.escape(o['headline'])}”\n{when}.\n\n"
                f"Tap ❌ Skip to drop this one, or tap {button} again if it's different news.")
    return True


def queue_schedule(state, now=None):
    """Planned posting time for each queued post (Post-now items first, then slots in order)."""
    now = now or now_utc()
    queued = sorted([d for d in state["drafts"].values() if d["status"] == "queued"],
                    key=lambda d: d["queued_at"])
    plan = [(d, now) for d in queued if d.get("post_now")]
    waiting = [d for d in queued if not d.get("post_now")]
    slots = []
    cur = current_slot(now)
    if cur and state.get("last_slot") != cur.isoformat():
        slots.append(now)
    tz = ZoneInfo(SLOT_TIMEZONE)
    day = 0
    while len(slots) < len(waiting):
        base = (now.astimezone(tz) + timedelta(days=day)).date()
        for s_ in POST_SLOTS:
            hh, mm = map(int, s_.split(":"))
            t = datetime(base.year, base.month, base.day, hh, mm, tzinfo=tz)
            if t > now and len(slots) < len(waiting):
                slots.append(t)
        day += 1
    plan += list(zip(waiting, slots))
    return plan


def publish_due(state):
    now = now_utc()
    queued = sorted([d for d in state["drafts"].values() if d["status"] == "queued"],
                    key=lambda d: d["queued_at"])

    # drop queued posts whose news has become too old (waiting in line alone never removes a post)
    for d in queued:
        if now > news_age_limit(d):
            d["status"] = "expired"
            tg_clear(d)
            tg_text(f"🗑 Removed from the queue: <b>{html.escape(d['headline'])}</b>\n"
                    f"The news is now more than {QUEUE_EXPIRE_HOURS} hours old, so it wasn't posted.")
    queued = [d for d in queued if d["status"] == "queued"]

    to_post = [d for d in queued if d.get("post_now")]
    slot = current_slot(now)
    if slot and state.get("last_slot") != slot.isoformat():
        waiting = [d for d in queued if not d.get("post_now")]
        if waiting:
            to_post.append(waiting[0])
            state["last_slot"] = slot.isoformat()

    for d in to_post:
        try:
            img = tg_download(d["tg_file_id"])
            post_id = facebook_post_photo(img, d["caption"])
            d["status"] = "posted"
            d["fb_post_id"] = post_id
            d["posted_at"] = now.isoformat()
            link = f"https://www.facebook.com/{post_id}" if post_id else ""
            log_to_channel(state, d, link)
            tg_clear(d)
            log("Posted", d["id"], post_id)
            if story_wanted(d):
                try:
                    d["fb_story_id"] = facebook_post_story(img)
                    log("Shared to Story", d["id"])
                except Exception as e:  # the post itself is already live, so just report it
                    log("Story error:", e)
                    if not state.get("story_error_told"):
                        state["story_error_told"] = True
                        tg_text("⚠️ The post is live, but sharing it to the Facebook Story failed:\n"
                                f"<code>{html.escape(str(e))[:400]}</code>\n\n"
                                "Set SHARE_TO_STORY = \"off\" in settings.py to turn Stories off.")
            try:
                if SEND_EACH_POST_TO_CONTENT_CHANNEL and send_to_tiktok_channel(state, d, img):
                    log("Sent to TikTok channel", d["id"])
            except Exception as e:  # never block publishing because of this
                log("TikTok channel error:", e)
            if d.pop("make_reel", None) and REELS_ENABLED:
                publish_reel(state, d)          # tells you itself if the daily limit is reached
        except Exception as e:
            d["attempts"] = d.get("attempts", 0) + 1
            log("Facebook error:", e)
            if d["attempts"] >= 3:
                d["status"] = "failed"
                tg_status(d, "⚠️ Failed to post")
                tg_text(f"⚠️ Could not post to Facebook:\n<code>{html.escape(str(e))[:500]}</code>\n\n"
                        "If it says the token is invalid, create a new Page token and update the "
                        "FB_PAGE_TOKEN secret on GitHub.")


# =============================================================================
# 3) COLLECT AND CONFIRM NEWS
# =============================================================================

STOP = set("""a an the of to in on for and or but with at by from as is are was were be been
being has have had will would could should may might says say said after over into about than
this that these those it its his her their they them he she we you who what when where why how
not no new more amid up out off just also new news latest report reports amid during before
while under against between first two three one year years day week top us""".split())


_WORD_RE_CACHE = {}


def has_any(text, words):
    key = tuple(words)
    if key not in _WORD_RE_CACHE:
        alts = "|".join(re.escape(w.strip().lower()) for w in words if w.strip())
        # allows simple endings: strike→strikes, russia→russian, iran→iranian, bomb→bombing
        _WORD_RE_CACHE[key] = re.compile(
            rf"(?<![a-z0-9])(?:{alts})(?:s|es|ed|ing|n|ns|ian|ians|i|is)?(?![a-z0-9])")
    return bool(_WORD_RE_CACHE[key].search(text.lower()))


def clean_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


COMPOUNDS = [(r"\bair[\s-]+strikes?\b", "airstrike"), (r"\bcease[\s-]+fire\b", "ceasefire"),
             (r"\bgun[\s-]+man\b", "gunman"), (r"\bu\.?s\.?\b", "us")]


def stem(w):
    """Very simple word root, so 'killed'/'kills'/'kill' and 'strikes'/'strike' match."""
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        w = w[:-1]
    for suf in ("ing", "ed"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)]
            break
    return w[:-1] if w.endswith("e") and len(w) > 3 else w


STOP_STEMS = {stem(w) for w in STOP}


def plain(text):
    """Kraków → Krakow, so accents don't make the same word look different."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()


def keywords(title, summary=""):
    words = set()
    title, summary = plain(title), plain(summary)
    t = title.lower()
    for pat, rep in COMPOUNDS:
        t = re.sub(pat, rep, t)
    for w in re.findall(r"[a-z][a-z'\-]+", t):
        w = w.strip("'-")
        w = w[:-2] if w.endswith("'s") else w
        if len(w) > 2 and w not in STOP and stem(w) not in STOP_STEMS:
            words.add(stem(w))
    # numbers ("33 killed") help match the same story; years don't
    for n in re.findall(r"\b\d[\d,]*\b", title + " " + summary):
        n = n.replace(",", "")
        if len(n) >= 2 and not re.fullmatch(r"(19|20)\d\d", n):
            words.add(n)
    # proper nouns from the summary help match the same story
    for w in re.findall(r"\b[A-Z][a-z]{2,}\b", summary):
        lw = w.lower()
        if lw not in STOP and stem(lw) not in STOP_STEMS:
            words.add(stem(lw))
    return words


def read_feed(url):
    """Download one RSS feed; gives up after ~15 s so one slow site can't hold up the run."""
    r = HTTP.get(url, timeout=(5, 10), stream=True)
    body, start = b"", time.time()
    for chunk in r.iter_content(65536):
        body += chunk
        if time.time() - start > 15 or len(body) > 5_000_000:
            raise RuntimeError("too slow")
    return feedparser.parse(body)


def fetch_articles():
    now = now_utc()
    items = []
    jobs = [(source, url) for source, urls in FEEDS.items() for url in urls]
    results = {}

    def worker(n, url):
        try:
            results[n] = read_feed(url)
        except Exception as e:
            results[n] = e

    # Read all feeds at the same time. A site that hasn't answered within 45 s is skipped
    # this run (some sites sometimes hang for minutes and would block everything).
    threads = [threading.Thread(target=worker, args=(n, url), daemon=True) for n, (_, url) in enumerate(jobs)]
    for t in threads:
        t.start()
    deadline = time.time() + 45
    for t in threads:
        t.join(max(0, deadline - time.time()))
    feeds = []
    for n, (source, url) in enumerate(jobs):
        res = results.get(n)
        if res is None:
            log("Feed too slow, skipped this time:", source, url)
        elif isinstance(res, Exception):
            log("Feed failed:", source, url, res)
        else:
            feeds.append((source, url, res))
    for source, url, feed in feeds:
        for e in feed.entries[:40]:
            title = clean_html(e.get("title", ""))
            link = e.get("link", "")
            if not title or not link:
                continue
            t = e.get("published_parsed") or e.get("updated_parsed")
            published = datetime(*t[:6], tzinfo=timezone.utc) if t else now
            if now - published > timedelta(hours=MAX_AGE_HOURS):
                continue
            summary = clean_html(e.get("summary", ""))[:700]
            text = f"{title} {summary}".lower()
            if has_any(text, EXCLUDE_WORDS):
                continue
            if any(w in title.lower() for w in SKIP_TITLE_WORDS):
                continue
            items.append({
                "source": source, "title": title, "summary": summary, "link": link,
                "published": published, "kw": keywords(title, summary),
                "title_kw": keywords(title),
            })
    # de-duplicate same link from two feeds of one outlet
    seen, uniq = set(), []
    for it in items:
        if it["link"] not in seen:
            seen.add(it["link"])
            uniq.append(it)
    log(f"Fetched {len(uniq)} recent articles")
    return uniq


def similar(a, b):
    shared = len(a & b)
    if shared < 3:
        return False
    return shared / max(1, min(len(a), len(b))) >= 0.3


def cluster(items):
    clusters = []
    for it in sorted(items, key=lambda x: x["published"], reverse=True):
        best = None
        for c in clusters:
            # same story = similar words overall AND at least 2 shared headline words
            if similar(it["kw"], c["kw"]) and len(it["title_kw"] & c["title_kw"]) >= 2:
                best = c
                break
        if best:
            best["items"].append(it)
            best["kw"] |= it["kw"]
            best["title_kw"] |= it["title_kw"]
        else:
            clusters.append({"items": [it], "kw": set(it["kw"]), "title_kw": set(it["title_kw"])})
    return clusters


def topic_status(state, t):
    """Status of the draft a saved topic came from. Older topics have no draft id:
    find the draft sent at that moment whose headline shares words with the topic."""
    if len(t) >= 3:
        return state["drafts"].get(t[2], {}).get("status")
    when, roots = datetime.fromisoformat(t[0]), {stem(w) for w in t[1]}
    for d in state["drafts"].values():
        if abs((datetime.fromisoformat(d["created_at"]) - when).total_seconds()) < 300 and \
                len({stem(w) for w in keywords(d.get("headline", ""))} & roots) >= 2:
            return d.get("status")
    return None


def pick_stories(state, items):
    now = now_utc()
    seen = set(state["seen_links"])
    # Topics already handled. A draft that expired without your choice doesn't block its topic.
    recent = [{stem(w) for w in t[1]} for t in state["recent_topics"]
              if topic_status(state, t) != "expired"]
    good = []
    for c in cluster(items):
        new_items = [i for i in c["items"] if i["link"] not in seen]   # articles not used before
        sources = {i["source"] for i in new_items}
        if len(sources) < MIN_SOURCES:
            continue  # needs 2+ outlets among the NEW articles
        title_roots = {stem(w) for i in new_items for w in i["title_kw"]}   # judge only the new articles
        if any(len(title_roots & r) >= 4 for r in recent):
            continue  # same topic handled recently
        c["items"] = new_items   # Gemini only sees the new reports
        newest = max(i["published"] for i in new_items)
        first = min(i["published"] for i in c["items"])
        hours_since_newest = (now - newest).total_seconds() / 3600
        if hours_since_newest > FRESH_HOURS:
            continue  # nobody has reported on it recently: old news
        text = " ".join(f"{i['title']} {i['summary']}" for i in c["items"])
        is_us, is_war = has_any(text, US_WORDS), has_any(text, WAR_WORDS)
        if FOCUS_ONLY and not (is_us or is_war) and len(sources) < OTHER_NEWS_MIN_SOURCES:
            continue  # not our focus and not huge news
        # Fresh news wins: a new 2-source story beats an old 5-source one.
        c["score"] = (min(len(sources), 5) * 6 + (8 if is_us else 0) + (6 if is_war else 0)
                      - 8 * hours_since_newest + (15 if hours_since_newest < 1 else 0))
        c["first"], c["newest"] = first, newest
        c["sources"] = sorted(sources)
        good.append(c)
    good.sort(key=lambda c: c["score"], reverse=True)
    log(f"{len(good)} confirmed stories (2+ sources)")
    return good


# =============================================================================
# 4) GEMINI WRITES THE POST
# =============================================================================

PROMPT = """You are the editor of "7 Seas News", a neutral, factual world-politics news page on Facebook.
Below are reports of ONE news story from different trusted news outlets.

{reports}

Write a Facebook news post about this story. Strict rules:
- Use ONLY facts that appear in the reports above. Never add facts, numbers, names or quotes that are not there. Never guess.
- If the reports disagree about a fact, leave that fact out.
- Be strictly neutral: no opinions, no loaded or emotional words, no taking sides. Attribute claims ("officials said", "according to ...").
- Write in your own words. Do not copy sentences from the reports.
- Simple, clear English for a global audience.
- Make people want to read it: lead with the most important or surprising FACT, use strong active verbs
  and concrete names, numbers and places from the reports. Catchy, but never exaggerated, misleading or invented.

Return ONLY JSON with these keys:
"headline": 6 to 12 words. A PLAIN FACT: who did what, where (and how many, if known). Use a neutral, simple verb (says, wins, loses, signs, votes, meets, arrives, kills, injures, announces). The headline must be something every side would agree is true.
  NEVER judge, interpret or predict: no metaphors, no loaded or emotional words (e.g. cracks, slams, blasts, destroys, crushing, stunning, humiliates, vulnerability, "win for", "blow to", "disaster for", "red wall"), no claims about what an event "exposes", "signals" or "means".
  Good: "Republicans lose several Florida House seats in midterms", "Pope Leo arrives in Uruguay on first stop of South America tour".
  Bad: "Florida red wall cracks: midterms expose Republican vulnerability", "Trump slams Democrats in fiery speech".
  No question headlines, no ALL-CAPS words (except abbreviations like US, UN), no emojis, no ending period.
"summary": 2 or 3 short sentences (max 60 words) saying what happened and the facts around it, in the same neutral words (no judging, no loaded words; "why it matters" only if a report states it, attributed).
"hook": ONE short, specific question about THIS story that people would genuinely want to answer, without taking any side. Mention the actual decision, person or place, not generic.
  Good: "Should Congress be able to block tariffs like these?", "Can these talks in Abu Dhabi end the fighting?"
  Bad (never use): "What are your thoughts?", "Let us know in the comments", "Comment below", "Share this", "Tag a friend", "Like if you agree".
  Return "" if the story involves deaths, victims, injuries, an attack, a disaster or a tragedy, or if there is no real question people would debate.
"breaking": true ONLY if this is a sudden, major event that has just happened or just been announced (attack, disaster, death or resignation of a leader, coup, declaration of war, final election result, major surprise announcement). Otherwise false.
"key_points": a list of 2 or 3 very short facts from the reports (max 12 words each) that add context. Used for breaking news.
"image_style": "incident" if the story is about violence or a disaster (shooting, bombing, explosion, attack, airstrike, crash, fire, earthquake, flood); otherwise "person" if it is mainly about what a person said or did; otherwise "scene" (a visit, tour, summit, protest, vote, policy).
"location": where it happened, "City, Country" (or just "Country"/"US State"), e.g. "Krakow, Poland". Empty string if unclear.
"label": exactly one of "US POLITICS", "WORLD", "CONFLICT", "DIPLOMACY", "ELECTIONS", "ECONOMY".
"hashtags": a list of 3 relevant hashtags, e.g. ["#USPolitics", "#WorldNews", "#Congress"].
"image_query": 2 to 4 words for a photo of the most relevant PLACE or landmark (never a person), as specific as possible, e.g. "Montevideo skyline", "US Capitol building", "Kyiv city", "United Nations Security Council". Pick the place that fits THIS story: Congress/party stories → "US Capitol dome", "Senate chamber", "House of Representatives chamber" or the state capitol/city involved; courts → "Supreme Court building"; military → "Pentagon building". Use "White House" only when the story really happens at the White House.
"image_queries": a list of 4 OTHER, different photo ideas for this story (2 to 4 words each, places or things, never a person), e.g. for a story about Democrats in Congress: ["Senate chamber", "Capitol Hill", "Democratic National Convention", "voting booth"].
"people": a list of 0 to 3 real people who are the MAIN subject of the story AND are named in your headline, full names exactly as written in the reports, e.g. ["Donald Trump", "Vladimir Putin"]. People who are only mentioned in the background must NOT be listed. Use [] if the headline names no person (for example a story about a country, party, vote or attack).
"skip": true if this is about South Asia, is not hard news (opinion, sport, entertainment, live blog), or the reports describe different events. Otherwise false.
{fix}"""


def gemini_models():
    models = [GEMINI_MODEL] if GEMINI_MODEL else []
    models += ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
    return list(dict.fromkeys(models))


def banned_words_in(post):
    """Loaded/opinion words from BANNED_HEADLINE_WORDS found in the headline or summary."""
    text = plain(f"{post.get('headline', '')} {post.get('summary', '')}").lower()
    return [w for w in BANNED_HEADLINE_WORDS
            if re.search(r"(?<![a-z])" + re.escape(w.lower()) + r"(?![a-z])", text)]


def gemini_write_neutral(c):
    """Write the post; if it uses loaded words, ask once for a neutral rewrite; still bad → skip."""
    post = gemini_write(c)
    bad = banned_words_in(post)
    if not bad or post.get("skip"):
        return post
    log("Loaded words, asking for a rewrite:", bad, "|", post.get("headline"))
    fix = (f"\nIMPORTANT: your last headline was \"{post.get('headline')}\". It used judging or loaded words "
           f"({', '.join(bad)}). Rewrite the headline and summary as plain facts and do NOT use any of these "
           f"words: {', '.join(BANNED_HEADLINE_WORDS)}.\n")
    post = gemini_write(c, fix)
    bad = banned_words_in(post)
    if bad:
        log("Still loaded words, skipping story:", bad, "|", post.get("headline"))
        post["skip"] = True
        post["skip_reason"] = "loaded words: " + ", ".join(bad)
    return post


def gemini_write(c, fix=""):
    reports = "\n\n".join(
        f"Outlet: {i['source']}\nTitle: {i['title']}\nSummary: {i['summary']}"
        for i in c["items"][:6]
    )
    body = {
        "contents": [{"parts": [{"text": PROMPT.format(reports=reports, fix=fix)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
    }
    last_err = None
    for model in gemini_models():
        try:
            r = HTTP.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": GEMINI_KEY}, json=body, timeout=90)
            if r.status_code == 404:
                continue
            if r.status_code == 429:
                last_err = "Gemini free limit reached (429)"
                time.sleep(5)
                continue
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(json)?|```$", "", text.strip()).strip()
            data = json.loads(text)
            if isinstance(data, list):
                data = data[0]
            if not data.get("headline") or not data.get("summary"):
                raise ValueError("missing headline/summary")
            return data
        except Exception as e:
            last_err = f"{model}: {e}"
            log("Gemini error:", last_err)
    raise RuntimeError(last_err or "No Gemini model available")


# =============================================================================
# 5) MAKE THE IMAGE
# =============================================================================

FONT_URLS = {
    "Poppins-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Bold.ttf",
    "Poppins-SemiBold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-SemiBold.ttf",
    "Poppins-Medium.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Medium.ttf",
}

WIKI_HEADERS = {"User-Agent": "7SeasNewsBot/1.1 (https://github.com/minurajayasingha/7-seas-news-bot) python-requests"}


def commons_api(params, timeout=30):
    """Ask Wikimedia Commons. If it says 'slow down' (not JSON / 429), wait and try again."""
    for wait in (0, 4, 10):
        time.sleep(wait)
        try:
            r = HTTP.get("https://commons.wikimedia.org/w/api.php", headers=WIKI_HEADERS,
                         timeout=timeout, params=dict(params, format="json", maxlag=5))
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                return r.json()
            log("Wikimedia busy:", r.status_code)
        except Exception as e:
            log("Wikimedia error:", e)
    return {}


def has_words(text, phrase):
    """True if all words of phrase are in text as whole words ('pentagon' is not 'pentagonal')."""
    words = [w for w in phrase.split() if len(w) > 1]
    return bool(words) and all(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text) for w in words)
FREE_LICENSES = ("public domain", "pd", "cc0", "cc by", "cc-by")


def font(name, size):
    path = os.path.join(FONT_DIR, name)
    if not os.path.exists(path):
        try:
            os.makedirs(FONT_DIR, exist_ok=True)
            r = HTTP.get(FONT_URLS[name], timeout=30)
            r.raise_for_status()
            with open(path, "wb") as f:
                f.write(r.content)
        except Exception as e:
            log("Font download failed:", e)
    for p in (path, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


# ---------- where background photos come from ----------

def wiki_main_photo(name):
    """Main photo of a person's Wikipedia article, only if it is free to use."""
    try:
        r = HTTP.get("https://en.wikipedia.org/w/api.php", headers=WIKI_HEADERS, timeout=20, params={
            "action": "query", "prop": "pageimages", "piprop": "name",
            "titles": name, "redirects": 1, "format": "json"})
        page = next(iter(r.json()["query"]["pages"].values()))
        fname = page.get("pageimage")
        if not fname:
            return None
        data = commons_api({
            "action": "query", "titles": "File:" + fname, "prop": "imageinfo",
            "iiprop": "url|extmetadata", "iiurlwidth": 1200}, timeout=20)
        page = next(iter(data["query"]["pages"].values()))
        if "imageinfo" not in page:
            return None  # not on Commons = not a free image
        info = page["imageinfo"][0]
        meta = info.get("extmetadata", {})
        lic = clean_html(meta.get("LicenseShortName", {}).get("value", ""))
        if not lic.lower().startswith(FREE_LICENSES):
            return None
        if str(meta.get("NonFree", {}).get("value", "")).lower() == "true":
            return None
        artist = clean_html(meta.get("Artist", {}).get("value", ""))[:60] or "Unknown author"
        return {"url": info.get("thumburl") or info["url"],
                "credit": f"{artist} / Wikimedia Commons ({lic})", "short": "WIKIMEDIA COMMONS"}
    except Exception as e:
        log("Wikimedia photo failed:", name, e)
        return None


# Memory of photos (pools per person + recently used photos). Points into state["photo_memory"].
PHOTO_MEM = {}

BAD_PERSON_TITLE = (" and ", " with ", " meets ", " meeting", "&", " signing", "signature", "logo", "caricature",
                    "cartoon", "mural", "statue", "wax", "painting", "drawing", "poster", "flag", "coin", "stamp",
                    "mask", "graffiti", "sign ", "crowd", "protest", "supporters", "tweet", "screenshot")


def recent_photos():
    return set(PHOTO_MEM.get("recent", []))


def remember_photos(urls):
    rec = [u for u in PHOTO_MEM.get("recent", []) if u not in urls] + list(urls)
    PHOTO_MEM["recent"] = rec[-NO_REPEAT_PHOTOS:]


def commons_person_photos(name, limit):
    """More free photos of a person from Wikimedia Commons (file name must contain the name)."""
    data = commons_api({
        "action": "query", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f'intitle:"{name}" filetype:bitmap', "gsrlimit": 40,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 1200})
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    cands = []
    last = name.lower().split()[-1]
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        title = " " + page.get("title", "").lower().replace("_", " ") + " "
        if not url or last not in title or any(w in title for w in BAD_PERSON_TITLE):
            continue
        before = title.split(name.lower().split()[0])[0].strip().split()
        if before and before[-1] in ("to", "for", "by", "from", "greets", "welcomes", "toasts", "thanks"):
            continue                                    # someone else is the main subject
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        w, h = info.get("width", 0), info.get("height", 0)
        if w < 800 or h < 800 or w > h * 1.6:          # big enough, not a wide group/panorama shot
            continue
        meta = info.get("extmetadata", {})
        lic = clean_html(meta.get("LicenseShortName", {}).get("value", ""))
        if not lic.lower().startswith(FREE_LICENSES):
            continue
        if str(meta.get("NonFree", {}).get("value", "")).lower() == "true":
            continue
        yr = re.search(r"(19\d\d|20\d\d)", clean_html(meta.get("DateTimeOriginal", {}).get("value", "")) + title)
        if yr and int(yr.group(1)) < 2012:             # recent looks only
            continue
        artist = clean_html(meta.get("Artist", {}).get("value", ""))[:60] or "Unknown author"
        cands.append({"url": url, "credit": f"{artist} / Wikimedia Commons ({lic})", "short": "WIKIMEDIA COMMONS",
                      "portrait": h >= w})
    good = []
    for c in cands[:limit * 2]:                         # check colours/quality, keep the good ones
        if photo_quality(c["url"]) >= 0:
            good.append(c)
        if len(good) >= limit:
            break
    return good


def person_photo_pool(name):
    """A collection of ~PHOTOS_PER_PERSON free photos of a person, kept for PHOTO_POOL_DAYS."""
    pools = PHOTO_MEM.setdefault("pools", {})
    key = name.lower().strip()
    p = pools.get(key)
    if p and p.get("photos") and now_utc() - datetime.fromisoformat(p["t"]) < timedelta(days=PHOTO_POOL_DAYS):
        return p["photos"]
    photos = []
    main_photo = wiki_main_photo(name)
    if main_photo:
        photos.append(main_photo)
    for c in commons_person_photos(name, PHOTOS_PER_PERSON):
        if c["url"] not in {x["url"] for x in photos}:
            photos.append(c)
        if len(photos) >= PHOTOS_PER_PERSON:
            break
    if photos:
        pools[key] = {"t": now_utc().isoformat(), "photos": photos}
        if len(pools) > 60:                             # forget the oldest people
            for k in sorted(pools, key=lambda k: pools[k]["t"])[:len(pools) - 60]:
                pools.pop(k)
    log(f"Photo pool for {name}: {len(photos)} photos")
    return photos


def wiki_person_photo(name, exclude=()):
    """A free photo of a person, different from the ones used lately."""
    photos = person_photo_pool(name)
    if not photos:
        return None
    fresh = [p for p in photos if p["url"] not in exclude and p["url"] not in recent_photos()]
    if not fresh:                                       # all used lately: take the one used longest ago
        rec = PHOTO_MEM.get("recent", [])
        fresh = sorted([p for p in photos if p["url"] not in exclude],
                       key=lambda p: rec.index(p["url"]) if p["url"] in rec else -1)[:1]
    if not fresh:
        return None
    pick = random.choice(fresh)
    return {k: v for k, v in pick.items() if k != "portrait"}


def pexels_photo(query, exclude=(), countries=()):
    if not PEXELS_KEY or not query:
        return None
    try:
        r = HTTP.get("https://api.pexels.com/v1/search", timeout=30,
                     params={"query": query, "orientation": "portrait", "per_page": 15},
                     headers={"Authorization": PEXELS_KEY})
        allp = [p for p in r.json().get("photos", []) if p["src"]["large2x"] not in exclude
                and place_ok(f"{query} {p.get('alt', '')} {p.get('url', '')}", countries)]
        photos = [p for p in allp if p["src"]["large2x"] not in recent_photos()] or allp
        if not photos:
            return None
        p = random.choice(photos[:5])
        return {"url": p["src"]["large2x"],
                "credit": f"{p.get('photographer', 'Pexels')} / Pexels", "short": "PEXELS"}
    except Exception as e:
        log("Pexels failed:", e)
        return None


def pixabay_photo(query, exclude=(), countries=()):
    if not PIXABAY_KEY or not query:
        return None
    try:
        r = HTTP.get("https://pixabay.com/api/", timeout=30, params={
            "key": PIXABAY_KEY, "q": query[:100], "image_type": "photo", "order": "popular",
            "safesearch": "true", "per_page": 20, "min_width": 1600})
        allh = [h for h in r.json().get("hits", []) if h["largeImageURL"] not in exclude
                and place_ok(f"{h.get('tags', '')} {h.get('pageURL', '')}", countries)]
        hits = [h for h in allh if h["largeImageURL"] not in recent_photos()] or allh
        if not hits:
            return None
        top = sorted(hits, key=lambda h: -(h.get("likes", 0) + h.get("downloads", 0) / 100))[:8]
        p = random.choice(top)
        return {"url": p["largeImageURL"],
                "credit": f"{p.get('user', 'Pixabay')} / Pixabay", "short": "PIXABAY"}
    except Exception as e:
        log("Pixabay failed:", e)
        return None


# ---------- which country is a story / a photo about? (STRICT_PHOTO_MATCH) ----------
US_STATES = ("alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|"
             "illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|"
             "mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|"
             "north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|"
             "south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming")
# country: words that point to it (name, people, capital, big cities). One line each.
COUNTRY_WORDS = {
    "United States": "united states|usa|u s a|u s|us|america|american|americans|washington d c|district of columbia|"
                     "capitol hill|white house|pentagon|chicago|los angeles|san francisco|miami|boston|houston|"
                     "philadelphia|seattle|atlanta|dallas|las vegas|detroit|denver|phoenix|" + US_STATES,
    "United Kingdom": "united kingdom|uk|britain|british|england|english|scotland|scottish|wales|welsh|"
                      "northern ireland|london|manchester|birmingham|liverpool|edinburgh|glasgow|royal mail|westminster",
    "Canada": "canada|canadian|ottawa|toronto|montreal|vancouver|quebec|ontario|alberta",
    "Mexico": "mexico|mexican|mexico city|tijuana|guadalajara|monterrey",
    "Ireland": "ireland|irish|dublin",
    "France": "france|french|paris|marseille|lyon",
    "Germany": "germany|german|berlin|munich|hamburg|frankfurt",
    "Italy": "italy|italian|rome|milan|naples|venice",
    "Spain": "spain|spanish|madrid|barcelona",
    "Portugal": "portugal|portuguese|lisbon",
    "Netherlands": "netherlands|dutch|amsterdam|the hague|rotterdam",
    "Belgium": "belgium|belgian|brussels",
    "Switzerland": "switzerland|swiss|geneva|zurich|bern",
    "Austria": "austria|austrian|vienna",
    "Poland": "poland|polish|warsaw|krakow",
    "Ukraine": "ukraine|ukrainian|kyiv|kiev|kharkiv|odesa|odessa|lviv|dnipro|zaporizhzhia|donetsk|crimea",
    "Russia": "russia|russian|moscow|kremlin|st petersburg|saint petersburg",
    "Belarus": "belarus|belarusian|minsk",
    "Lithuania": "lithuania|lithuanian|vilnius|kaunas|trakai",
    "Latvia": "latvia|latvian|riga",
    "Estonia": "estonia|estonian|tallinn",
    "Moldova": "moldova|moldovan|chisinau",
    "Georgia (country)": "tbilisi|georgian",
    "Armenia": "armenia|armenian|yerevan",
    "Azerbaijan": "azerbaijan|azerbaijani|baku",
    "Serbia": "serbia|serbian|belgrade",
    "Croatia": "croatia|croatian|zagreb",
    "Czech Republic": "czech|czechia|prague",
    "Slovakia": "slovakia|slovak|bratislava",
    "Bulgaria": "bulgaria|bulgarian|sofia",
    "Hungary": "hungary|hungarian|budapest",
    "Romania": "romania|romanian|bucharest",
    "Greece": "greece|greek|athens",
    "Turkey": "turkey|turkish|turkiye|ankara|istanbul",
    "Sweden": "sweden|swedish|stockholm",
    "Norway": "norway|norwegian|oslo",
    "Denmark": "denmark|danish|copenhagen|greenland",
    "Finland": "finland|finnish|helsinki",
    "Israel": "israel|israeli|jerusalem|tel aviv|haifa|knesset",
    "Palestine": "palestine|palestinian|gaza|west bank|ramallah|rafah|khan younis",
    "Lebanon": "lebanon|lebanese|beirut",
    "Syria": "syria|syrian|damascus|aleppo",
    "Iraq": "iraq|iraqi|baghdad|mosul|erbil",
    "Iran": "iran|iranian|tehran|isfahan",
    "Saudi Arabia": "saudi arabia|saudi|riyadh|jeddah|mecca",
    "Yemen": "yemen|yemeni|sanaa|aden|houthi",
    "Qatar": "qatar|qatari|doha",
    "United Arab Emirates": "united arab emirates|uae|emirati|dubai|abu dhabi",
    "Egypt": "egypt|egyptian|cairo",
    "Jordan": "jordan|jordanian|amman",
    "China": "china|chinese|beijing|shanghai|hong kong",
    "Taiwan": "taiwan|taiwanese|taipei",
    "Japan": "japan|japanese|tokyo|osaka",
    "South Korea": "south korea|south korean|seoul",
    "North Korea": "north korea|north korean|pyongyang",
    "Australia": "australia|australian|sydney|melbourne|canberra",
    "New Zealand": "new zealand|wellington|auckland",
    "Brazil": "brazil|brazilian|brasilia|rio de janeiro|sao paulo",
    "Argentina": "argentina|argentine|argentinian|buenos aires",
    "Venezuela": "venezuela|venezuelan|caracas",
    "Colombia": "colombia|colombian|bogota",
    "Cuba": "cuba|cuban|havana",
    "Uruguay": "uruguay|uruguayan|montevideo",
    "Chile": "chile|chilean|santiago",
    "Peru": "peru|peruvian|lima",
    "Nigeria": "nigeria|nigerian|abuja|lagos",
    "South Africa": "south africa|south african|johannesburg|cape town|pretoria",
    "Kenya": "kenya|kenyan|nairobi",
    "Ethiopia": "ethiopia|ethiopian|addis ababa",
    "Sudan": "sudan|sudanese|khartoum",
    "Afghanistan": "afghanistan|afghan|kabul",
    "Libya": "libya|libyan|tripoli|benghazi",
    "Morocco": "morocco|moroccan|rabat|casablanca",
    "Algeria": "algeria|algerian|algiers",
    "Tunisia": "tunisia|tunisian|tunis",
    "Somalia": "somalia|somali|mogadishu",
    "Congo": "congo|congolese|kinshasa|goma",
    "Haiti": "haiti|haitian|port au prince",
    "Ecuador": "ecuador|ecuadorian|quito",
    "Bolivia": "bolivia|bolivian|la paz",
    "Panama": "panama|panamanian",
    "Malaysia": "malaysia|malaysian|kuala lumpur",
    "Singapore": "singapore|singaporean",
    "Philippines": "philippines|filipino|manila",
    "Indonesia": "indonesia|indonesian|jakarta",
    "Vietnam": "vietnam|vietnamese|hanoi",
    "Thailand": "thailand|thai|bangkok",
}
_COUNTRY_RE = {c: re.compile(r"(?<![a-z])(" + w + r")(?![a-z])") for c, w in COUNTRY_WORDS.items()}


def countries_in(text):
    t = re.sub(r"[^a-z0-9]+", " ", plain(str(text)).lower())
    return {c for c, rx in _COUNTRY_RE.items() if rx.search(t)}


def story_countries(post):
    """Countries a story is about (from location + headline). US politics labels count as the US."""
    found = countries_in(post.get("location", "")) or countries_in(post.get("headline", ""))
    if not found and str(post.get("label", "")).upper() in ("US POLITICS", "ELECTIONS"):
        found = {"United States"}
    return found


def place_ok(text, countries):
    """STRICT_PHOTO_MATCH: the photo's text must name the story's country and no other country."""
    if not STRICT_PHOTO_MATCH or not countries:
        return True
    named = countries_in(text)
    if not named & countries:
        return False
    if named - countries and re.search(r"(?<![a-z])borders?(?![a-z])", plain(text).lower()):
        return True                                     # e.g. US story + "Mexico–United States border"
    return not (named - countries)


def _small(url, w=400):
    """Small version of a Wikimedia thumbnail URL (for a quick quality check)."""
    return re.sub(r"/\d+px-", f"/{w}px-", url) if "/thumb/" in url else url


def photo_quality(url):
    """Score how good a photo looks: colourful, not too dark/bright, not black & white or sepia."""
    try:
        r = HTTP.get(_small(url), headers=WIKI_HEADERS, timeout=20)
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        im.thumbnail((240, 240))
        h, sat, val = im.convert("HSV").split()
        from PIL import ImageStat
        s_mean = ImageStat.Stat(sat).mean[0]
        v_mean = ImageStat.Stat(val).mean[0]
        h_std = ImageStat.Stat(h).stddev[0]
        if s_mean < 28 or h_std < 14:           # black & white / sepia / washed out
            return -1
        light = 1 - abs(v_mean - 135) / 135     # best around medium brightness
        return s_mean * 0.6 + h_std * 0.5 + light * 40
    except Exception:
        return 0


def wiki_search_photo(query, exclude=(), countries=()):
    """Best free-licensed photo from Wikimedia Commons. No key needed.
    Looks at 'Quality images' first, skips old/black-and-white pictures, checks colour and sharpness."""
    if not query:
        return None
    cands, seen = [], set()
    # "Wall Street, New York": the photo name must have "Wall Street"; "New York" only helps the search
    must = re.sub(r"[^a-z0-9]+", " ", plain(query.split(",")[0]).lower()).strip()
    search, banned = query.replace(",", " "), []
    core = re.sub(r"^(the|us|u s) |\b(building|washington|dc)\b", " ", must)
    core = re.sub(r"\s+", " ", re.sub(r"^(the|us|u s) ", "", core.strip())).strip()
    if core in PHOTO_SEARCH_FIX:                        # only for exactly "White House" / "US Capitol (building)"
        search, banned = PHOTO_SEARCH_FIX[core]
        must = core
    rec = recent_photos()
    for bonus, q in ((25, f"{search} incategory:Quality_images"), (0, search)):
        data = commons_api({
            "action": "query", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"{q} filetype:bitmap filew:>1500", "gsrlimit": 15,
            "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 1600})
        pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        for rank, page in enumerate(pages):
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("thumburl") or info.get("url")
            if not url or url in exclude or url in seen:
                continue
            if info.get("mime") != "image/jpeg" or info.get("width", 0) < 1200:   # real photos only (PNG = maps/graphics)
                continue
            meta = info.get("extmetadata", {})
            lic = clean_html(meta.get("LicenseShortName", {}).get("value", ""))
            if not lic.lower().startswith(FREE_LICENSES):
                continue
            title = page.get("title", "").lower()
            if re.search(r"(?<!\d)(1[0-8]\d\d|19[0-8]\d)(?!\d)", title) or any(
                    w in title for w in ("old ", "historic", "postcard", "vintage", "engraving", "painting",
                                         "drawing", "map", "lithograph", "sepia", "diagram", "logo", "flag of",
                                         " sign", "sign.", "closure", "chart", "graph", "screenshot", "poster",
                                         "obama", "biden", "bush", "clinton", "reagan", "speech by", "meeting with")):
                continue
            yr = re.search(r"(1[89]\d\d|20\d\d)", clean_html(meta.get("DateTimeOriginal", {}).get("value", "")))
            year = int(yr.group(1)) if yr else 0
            if year and year < 2000:
                continue
            seen.add(url)
            artist = clean_html(meta.get("Artist", {}).get("value", ""))[:60] or "Unknown author"
            t = " " + re.sub(r"[^a-z0-9]+", " ", plain(title).lower()) + " "
            hit = 30 if f" {must} " in t else (10 if has_words(t, must) else 0)
            if not hit or any(b in t for b in banned):
                continue                                # the place must be in the file name
            about = " ".join([title, clean_html(meta.get("ImageDescription", {}).get("value", ""))[:600],
                              meta.get("Categories", {}).get("value", "").replace("|", " ")])
            if not place_ok(about, countries):
                continue                                # photo from another country (or not clearly ours)
            score = bonus + hit + (10 if year >= 2015 else 0) + max(0, 12 - rank) - (60 if url in rec else 0) \
                + min(10, info.get("width", 0) / 600)
            cands.append((score, {"url": url, "credit": f"{artist} / Wikimedia Commons ({lic})",
                                  "short": "WIKIMEDIA COMMONS"}))
    good = []
    for score, c in sorted(cands, key=lambda x: -x[0])[:8]:   # check the top 8 by eye (used lately = last)
        q = photo_quality(c["url"])
        if q >= 0:
            good.append((score + q, c))
    if not good:
        return None
    good.sort(key=lambda x: -x[0])
    close = [c for sc, c in good[:4] if sc >= good[0][0] - 20]      # one of the best few = variety
    return random.choice(close)


def person_names_in_headline(post):
    headline = re.sub(r"[^a-z0-9 ]", " ", str(post.get("headline", "")).lower())
    words = set(headline.split())
    skip = {"the", "of", "and", "de", "von", "van", "bin", "al", "ii", "iii", "iv", "xiv", "jr", "sr",
            "pope", "king", "queen", "prince", "president", "minister", "prime", "general"}
    people = []
    for p in post.get("people") or []:
        if not isinstance(p, str) or not p.strip():
            continue
        tokens = [t for t in re.sub(r"[^a-z0-9 ]", " ", p.lower()).split() if len(t) > 2 and t not in skip]
        if any(t in words for t in tokens):            # only people named in the headline
            people.append(p.strip())
    return people[:3]


def choose_background(post, exclude=(), prefer_scene=False):
    """Pick a background and remember its photos so the next posts use different ones."""
    bg = _choose_background(post, exclude, prefer_scene)
    remember_photos(bg_urls(bg))
    return bg


def photo_ideas(post):
    """Different photo ideas for this story, in a fresh random order (ideas used lately go last)."""
    text = " " + plain(" ".join(str(post.get(k) or "") for k in ("headline", "image_query", "label"))).lower() + " "
    ideas = [str(q).strip() for q in (post.get("image_queries") or []) if str(q).strip()]
    for words, extra in TOPIC_PHOTO_IDEAS.items():
        if any(re.search(r"(?<![a-z])" + re.escape(w), text) for w in words):
            ideas += extra
    first = str(post.get("image_query") or "").strip()
    ideas = list(dict.fromkeys([first] + ideas if first else ideas))   # no doubles
    random.shuffle(ideas)
    recent = PHOTO_MEM.get("recent_ideas", [])
    return sorted(ideas, key=lambda q: q.lower() in recent)   # fresh ideas first


def _choose_background(post, exclude=(), prefer_scene=False):
    """1) photos of the people in the story  2) best matching photo  3) brand design.
    prefer_scene=True is used by the 🔄 Other photo button."""
    found = [x for x in (wiki_person_photo(p, exclude) for p in person_names_in_headline(post)) if x]

    if post.get("image_style") == "incident" and not found and not prefer_scene:
        # no random photos for shootings/bombings: strong news design with a location tag
        return {"type": "incident", "photos": [], "location": str(post.get("location") or "")[:40]}

    scene = None
    if prefer_scene or post.get("image_style") == "scene" or not found:
        tries = photo_ideas(post)[:4]
        tries += [str(post.get(k) or "").strip() for k in ("image_query", "location")]
        countries = story_countries(post)
        for q in dict.fromkeys(tries):
            if q:
                scene = (pexels_photo(q, exclude, countries) or pixabay_photo(q, exclude, countries)
                         or wiki_search_photo(q, exclude, countries))
            if scene:
                PHOTO_MEM["recent_ideas"] = (PHOTO_MEM.get("recent_ideas", []) + [q.lower()])[-12:]
                break

    if found and scene and len(found) == 1:
        # place photo in the background + the main person in a small circle
        return {"type": "photo", "photos": [scene], "inset": found[0]}
    if found and not (prefer_scene and scene):
        return {"type": "people", "photos": found}
    if scene:
        return {"type": "photo", "photos": [scene]}
    if post.get("image_style") == "incident":
        return {"type": "incident", "photos": [], "location": str(post.get("location") or "")[:40]}
    return {"type": "brand", "photos": []}


def bg_urls(bg):
    return [p["url"] for p in bg.get("photos", []) + ([bg["inset"]] if bg.get("inset") else []) if p.get("url")]


def load_photo(p):
    if p.get("tg_file_id"):
        data = tg_download(p["tg_file_id"])
    elif p.get("path"):
        data = open(p["path"], "rb").read()
    else:
        r = HTTP.get(p["url"], headers=WIKI_HEADERS, timeout=60)
        r.raise_for_status()
        data = r.content
    return Image.open(io.BytesIO(data)).convert("RGB")


# ---------- drawing ----------

def cover(img, w, h, anchor_y=0.4):
    """Resize + crop to fill w×h. anchor_y=0.1 keeps the top (faces), 0.5 = centre."""
    s = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
    left = (img.width - w) // 2
    top = int((img.height - h) * anchor_y)
    return img.crop((left, top, left + w, top + h))


def branded_background():
    """Black/charcoal background with a faint globe — used when there is no photo."""
    bg = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(bg)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(CHARCOAL[i] * (1 - k) + BLACK[i] * k) for i in range(3)))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(layer)
    cx, cy, r = W // 2 + 160, 520, 480
    line = (255, 255, 255, 26)
    g.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 50), width=3)
    for lon in range(15, 90, 15):
        hw = r * math.cos(math.radians(lon))
        g.ellipse([cx - hw, cy - r, cx + hw, cy + r], outline=line, width=2)
    g.line([(cx, cy - r), (cx, cy + r)], fill=line, width=2)
    for lat in range(-75, 90, 15):
        y = cy + r * math.sin(math.radians(lat))
        hw = r * math.cos(math.radians(lat))
        g.line([(cx - hw, y), (cx + hw, y)], fill=line, width=2)
    rnd = random.Random(7)
    for _ in range(40):
        a, rr = rnd.uniform(0, 6.28), r * math.sqrt(rnd.uniform(0, 1))
        x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
        g.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 255, 255, 60))
    g.ellipse([cx - 128, cy - 68, cx - 112, cy - 52], fill=RED + (240,))
    bg.paste(layer, (0, 0), layer.filter(ImageFilter.GaussianBlur(0.6)))
    return bg


def wrap(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=f) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def spaced(draw, xy, text, f, fill, spacing):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + spacing
    return x


def spaced_width(draw, text, f, spacing):
    return sum(draw.textlength(ch, font=f) + spacing for ch in text) - spacing


def vertical_fade(alpha_top, alpha_bottom, y0, y1):
    """Grayscale mask: transparent above y0, ramps to alpha_bottom at y1."""
    col = Image.new("L", (1, H), 0)
    for y in range(H):
        if y < y0:
            a = alpha_top
        elif y >= y1:
            a = alpha_bottom
        else:
            k = (y - y0) / (y1 - y0)
            a = int(alpha_top + (alpha_bottom - alpha_top) * (k ** 0.85))
        col.putpixel((0, y), a)
    return col.resize((W, H))


def people_strips(imgs):
    """2 or 3 portraits side by side, blended softly into each other (no lines)."""
    n = len(imgs)
    ph = int(H * 0.8)
    feather = 70
    step = W / n
    base = Image.new("RGB", (W, H), BLACK)
    for i, im in enumerate(imgs):
        x0 = int(round(i * step)) - (feather // 2 if i > 0 else 0)
        x1 = int(round((i + 1) * step)) + (feather // 2 if i < n - 1 else 0)
        sw = x1 - x0
        strip = cover(im, sw, ph, 0.06)
        mask = Image.new("L", (sw, 1), 255)
        for x in range(sw):
            a = 255
            if i > 0 and x < feather:
                a = int(255 * x / feather)
            if i < n - 1 and x > sw - feather:
                a = min(a, int(255 * (sw - x) / feather))
            mask.putpixel((x, 0), a)
        base.paste(strip, (x0, 0), mask.resize((sw, ph)))
    return base


def render_image(headline, label, sources, bg, hide_headline=False, layout=None):
    """The 1080x1350 post image. hide_headline=True leaves the headline out (for the Reel typing effect);
    layout (a dict) is filled with where the headline goes: lines, font size, x, y, line height."""
    imgs = []
    for p in bg.get("photos", []):
        try:
            imgs.append(load_photo(p))
        except Exception as e:
            log("Photo load failed:", e)

    black = Image.new("RGB", (W, H), BLACK)
    if bg.get("type") == "people" and len(imgs) >= 2:
        base = people_strips(imgs[:3])
    elif imgs:
        anchor = 0.08 if bg.get("type") == "people" else 0.45
        base = cover(imgs[0], W, int(H * 0.8) if bg.get("type") == "people" else H, anchor)
        if base.height < H:
            full = Image.new("RGB", (W, H), BLACK)
            full.paste(base, (0, 0))
            base = full
    else:
        base = branded_background()

    if imgs:
        base = Image.blend(base, black, 0.10)
        # darken the top so the logo is always readable
        top = Image.new("L", (1, H), 0)
        for y in range(300):
            top.putpixel((0, y), int(200 * (1 - y / 300) ** 1.3))
        base.paste(black, (0, 0), top.resize((W, H)))

    # dark fade at the bottom for the text
    base.paste(black, (0, 0), vertical_fade(0, 250, int(H * 0.40), int(H * 0.78)))

    d = ImageDraw.Draw(base)

    M = 64
    max_w = W - 2 * M

    # --- logo ---
    if os.path.exists(LOGO_FILE):
        logo = Image.open(LOGO_FILE).convert("RGBA")
        lw = 330
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        base.paste(logo, (M, 64), logo)
    else:
        d.text((M, 60), "7 Seas", font=font("Poppins-SemiBold.ttf", 56), fill=WHITE)
        d.text((M + 200, 60), "News", font=font("Poppins-SemiBold.ttf", 56), fill=RED)

    # --- headline (auto size) ---
    size = 80
    while size > 46:
        hf = font("Poppins-Bold.ttf", size)
        lines = wrap(d, headline, hf, max_w)
        if len(lines) <= 4:
            break
        size -= 4
    line_h = int(size * 1.2)
    footer_top = H - 112
    y = footer_top - 40 - line_h * len(lines)

    # --- incident: pin on the globe + location tag ---
    if bg.get("type") == "incident":
        px, py = W // 2 + 160 - 120, 520 - 60
        for rr, a in ((150, 40), (105, 70), (62, 110)):
            ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse([px - rr, py - rr, px + rr, py + rr], outline=RED + (a,), width=5)
            base.paste(ring, (0, 0), ring)
        d.ellipse([px - 24, py - 24, px + 24, py + 24], fill=RED)
        d.ellipse([px - 9, py - 9, px + 9, py + 9], fill=WHITE)
        loc = (bg.get("location") or "").upper()
        if loc:
            tf = font("Poppins-SemiBold.ttf", 30)
            ty = y - 70 - 62
            d.ellipse([M, ty + 6, M + 26, ty + 32], fill=RED)
            d.polygon([(M + 3, ty + 24), (M + 23, ty + 24), (M + 13, ty + 44)], fill=RED)
            d.ellipse([M + 8, ty + 14, M + 18, ty + 24], fill=WHITE)
            spaced(d, (M + 40, ty), loc, tf, WHITE, 2)

    # --- main person in a circle (scene photos) ---
    if bg.get("inset"):
        try:
            face = cover(load_photo(bg["inset"]), 300, 300, 0.12)
            r = 300
            mask = Image.new("L", (r * 4, r * 4), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, r * 4 - 1, r * 4 - 1], fill=255)
            mask = mask.resize((r, r), Image.LANCZOS)
            cx, cy = W - M - r, y - 70 - 30 - r
            d.ellipse([cx - 14, cy - 14, cx + r + 14, cy + r + 14], fill=RED)
            d.ellipse([cx - 6, cy - 6, cx + r + 6, cy + r + 6], fill=WHITE)
            base.paste(face, (cx, cy), mask)
        except Exception as e:
            log("Inset photo failed:", e)

    # --- label ---
    lf = font("Poppins-SemiBold.ttf", 24)
    lwid = spaced_width(d, label, lf, 3)
    d.rectangle([M, y - 70, M + lwid + 36, y - 22], fill=RED)
    spaced(d, (M + 18, y - 66), label, lf, WHITE, 3)

    if layout is not None:
        layout.update(lines=lines, size=size, x=M, y=y, line_h=line_h)
    for ln in lines:
        if not hide_headline:
            d.text((M + 2, y + 3), ln, font=hf, fill=(0, 0, 0))
            d.text((M, y), ln, font=hf, fill=WHITE)
        y += line_h

    # --- footer ---
    d.rectangle([M, footer_top, W - M, footer_top + 3], fill=RED)
    sf = font("Poppins-Medium.ttf", 22)
    src = ("SOURCES: " + " · ".join(s.upper() for s in sources[:3])) if sources else ""
    while d.textlength(src, font=sf) > max_w - 230 and " · " in src:
        src = src.rsplit(" · ", 1)[0]
    has_credit = imgs and any(needs_credit(p) for p in bg.get("photos", []) +
                              ([bg["inset"]] if bg.get("inset") else []))
    ty = footer_top + (20 if has_credit else 30)
    d.text((M, ty), src, font=sf, fill=SOFT)
    d.text((W - M, ty), ny_now().strftime("%b %d, %Y").upper(), font=sf, fill=SOFT, anchor="ra")  # US date
    if has_credit:
        cf = font("Poppins-Medium.ttf", 17)
        credit = "PHOTO: " + " · ".join(re.sub(r"\s*/\s*Wikimedia Commons", " / WIKIMEDIA", p["credit"]).upper()
                                       for p in bg.get("photos", []) + ([bg["inset"]] if bg.get("inset") else [])
                                       if needs_credit(p))
        while d.textlength(credit, font=cf) > max_w and len(credit) > 20:
            credit = credit[:-4] + "…"
        d.text((M, ty + 36), credit, font=cf, fill=(150, 150, 156))

    out = io.BytesIO()
    base.save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


# =============================================================================
# 6) DRAFT → TELEGRAM
# =============================================================================

def needs_credit(p):
    """Creative Commons 'BY' licences require naming the photographer; public domain/CC0 don't."""
    c = (p.get("credit") or "").lower()
    return "cc by" in c or "cc-by" in c


GENERIC_HOOK_WORDS = ["thoughts", "let us know", "comment below", "in the comments", "share this",
                      "tag a friend", "like if", "share if", "what do you think"]


def clean_hook(post):
    """The comment question, or "" when we should not ask one (see ASK_QUESTION in settings)."""
    hook = str(post.get("hook") or "").replace("👇", "").replace("💬", "").strip()
    if ASK_QUESTION == "never" or not hook:
        return ""
    if ASK_QUESTION == "sometimes" and (
            post.get("image_style") == "incident" or post.get("breaking")
            or any(w in hook.lower() for w in GENERIC_HOOK_WORDS)):
        return ""
    return hook


def build_caption(d):
    tags = " ".join("#" + re.sub(r"[^A-Za-z0-9_]", "", t) for t in d.get("hashtags", [])[:3]
                    if re.sub(r"[^A-Za-z0-9_]", "", t))
    head = f"🚨 BREAKING: {d['headline']}" if d.get("breaking") else d["headline"]
    lines = [head] + (["", d["summary"]] if d.get("summary") else [])
    if d.get("breaking") and d.get("key_points"):
        lines += ["", "What we know so far:"] + [f"• {k}" for k in d["key_points"][:3]]
    if d.get("hook") and ASK_QUESTION != "never":
        lines += ["", "💬 " + d["hook"]]
    # sources + photo credit are printed small on the image itself
    if SHOW_READ_MORE_LINK and d.get("link"):
        lines += ["", f"📖 Read more: {d['link']}"]
    lines = with_follow_line(lines)
    lines += ["", f"{tags} {BRAND_HASHTAG}".strip()]
    return "\n".join(lines)


def with_follow_line(lines):
    """Add FOLLOW_LINE (settings) before the hashtags, unless the text already has a follow line."""
    text = "\n".join(lines).lower()
    if FOLLOW_LINE and FOLLOW_LINE.lower() not in text and "follow 7 seas" not in text:
        lines = lines + ["", FOLLOW_LINE]
    return lines


def send_draft(state, d):
    """Make the image, send it to Telegram with buttons, remember it."""
    img = render_image(d["headline"], "BREAKING NEWS" if d.get("breaking") else d["label"],
                       d["sources"], d["bg"])
    d["caption"] = build_caption(d)
    links = "\n".join(f'• <a href="{html.escape(u)}">{html.escape(s)}</a>' for s, u in d["links"][:4])
    nt = news_time_text(d)
    if d.get("breaking"):
        nt = "🚨 <b>BREAKING</b>" + (f"\n{nt}" if nt else "")
    dup = find_duplicate(state, d, loose=True)
    if dup:
        nt = (f"⚠️ <b>Similar to a post you already {'published' if dup['status'] == 'posted' else 'queued'}:</b> "
              f"“{html.escape(dup['headline'])}”" + (f"\n{nt}" if nt else ""))
    preview = (f"<b>{html.escape(d['headline'])}</b>\n"
               + (f"{nt}\n" if nt else "") + "\n"
               f"{html.escape(d['summary'])}\n"
               + ("".join(f"• {html.escape(k)}\n" for k in d.get("key_points", [])) if d.get("breaking") else "")
               + (f"💬 {html.escape(d['hook'])}\n" if d.get("hook") else "")
               + "\n"
               + ("✍️ <i>Your post" + (f" · from {html.escape(', '.join(d['sources']))} (single source, please double-check)"
                                       if d.get("sources") else "") + "</i>\n\n"
                  if d.get("manual") else
                  f"<i>Confirmed by: {html.escape(', '.join(d['sources']))}</i>\n{links}\n\n")
               +
               "✏️ <i>Reply with a photo to change the image, or with text to change the headline.</i>")
    j = tg("sendPhoto", chat_id=TG_CHAT, caption=preview, parse_mode="HTML",
           files={"photo": ("post.jpg", img, "image/jpeg")},
           reply_markup=draft_buttons(d["id"], d))
    if not j.get("ok"):
        return False
    res = j["result"]
    d["status"] = "pending"
    d["tg_message_id"] = res["message_id"]
    d["tg_file_id"] = res["photo"][-1]["file_id"]
    d.setdefault("created_at", now_utc().isoformat())
    state["drafts"][d["id"]] = d
    return True


def draft_new_posts(state):
    items = fetch_articles()
    stories = pick_stories(state, items)
    made = 0
    for c in stories:
        if made >= DRAFTS_PER_RUN:
            break
        state["seen_links"].extend(i["link"] for i in c["items"])  # never reconsider these
        try:
            post = gemini_write_neutral(c)
        except Exception as e:
            log("Skipping story, Gemini failed:", e)
            if "429" in str(e):
                break
            continue
        if post.get("skip"):
            log("Gemini marked skip:", c["items"][0]["title"], post.get("skip_reason", ""))
            continue
        d = {
            "id": hashlib.sha1(c["items"][0]["link"].encode()).hexdigest()[:10],
            "headline": str(post["headline"]).strip().rstrip("."),
            "summary": str(post["summary"]).strip(),
            "label": str(post.get("label") or "WORLD").upper()[:18],
            "hook": clean_hook(post),
            "key_points": [str(k).strip() for k in (post.get("key_points") or []) if str(k).strip()][:3],
            "breaking": bool(post.get("breaking")) and
                        (now_utc() - min(i["published"] for i in c["items"])) <= timedelta(hours=BREAKING_MAX_HOURS),
            "hashtags": [str(t) for t in (post.get("hashtags") or [])][:3],
            "sources": c["sources"],
            "link": c["items"][0]["link"],
            "links": [[i["source"], i["link"]] for i in c["items"][:4]],
            "bg": choose_background(post),
            "img_post": {k: post.get(k) for k in ("headline", "people", "image_query", "image_queries", "image_style", "location")},
            "created_at": now_utc().isoformat(),
            "news_time": min(i["published"] for i in c["items"]).isoformat(),
            "news_latest": max(i["published"] for i in c["items"]).isoformat(),
        }
        if send_draft(state, d):
            state["recent_topics"].append([now_utc().isoformat(), sorted(c["title_kw"]), d["id"]])
            made += 1
            log("Draft sent:", d["headline"], "| image:", d["bg"]["type"])
    if made == 0:
        log("No new drafts this run")


def expire_pending(state):
    now = now_utc()
    for d in state["drafts"].values():
        if d["status"] != "pending":
            continue
        news_t = d.get("news_latest") or d.get("news_time")
        too_old = now - datetime.fromisoformat(d["created_at"]) > timedelta(hours=PENDING_EXPIRE_HOURS)
        news_old = bool(news_t) and now - datetime.fromisoformat(news_t) > timedelta(hours=PENDING_EXPIRE_HOURS)
        if too_old or news_old:
            d["status"] = "expired"
            tg_clear(d)


# =============================================================================
# MAIN
# =============================================================================

def note(state, text):
    """Short run diary kept in state.json (last 40 lines), to see what each run did."""
    state.setdefault("run_log", []).append(f"{now_utc():%m-%d %H:%M:%S} {text}")
    state["run_log"] = state["run_log"][-40:]


def listen(state, until):
    """Stay online until `until`, so taps and replies are handled within seconds."""
    if until - time.time() < 40:
        return
    log(f"Listening to Telegram for {int((until - time.time()) / 60)} min")
    note(state, f"listening {int((until - time.time()) / 60)} min")
    while until - time.time() > 35:
        try:
            process_telegram(state, wait=25)   # returns as soon as you tap or send something
            publish_due(state)                 # 🚀 Post now / queue times
            expire_pending(state)
            day_packs_due(state)               # New York midnight → daily pack
            if state.pop("news_now", None):    # /news command
                state["last_draft_at"] = now_utc().isoformat()
                draft_new_posts(state)
            save_state(state)
        except Exception as e:
            log("Listen error:", e)
            note(state, f"listen error: {str(e)[:150]}")
            time.sleep(10)
    note(state, "listening done")


def main():
    missing = [n for n, v in [("TELEGRAM_BOT_TOKEN", TG_TOKEN), ("TELEGRAM_CHAT_ID", TG_CHAT),
                              ("GEMINI_API_KEY", GEMINI_KEY), ("FB_PAGE_ID", FB_PAGE_ID),
                              ("FB_PAGE_TOKEN", FB_TOKEN)] if not v]
    if missing:
        print("Missing secrets:", ", ".join(missing))
        sys.exit(1)

    # If GitHub stops the run, turn that into a normal exit so the memory is still saved.
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(143))
    started = time.time()
    state = load_state()
    global PHOTO_MEM
    PHOTO_MEM = state.setdefault("photo_memory", {})
    note(state, "run start" + (" (forced news search)" if FORCE_DRAFT else ""))
    try:
        set_commands_once(state)
        process_telegram(state)
        publish_due(state)
        expire_pending(state)
        try:
            day_packs_due(state)
        except Exception as e:
            log("Day pack error:", e)
        try:
            update_post_stats(state)
        except Exception as e:  # numbers are a bonus: never stop the bot because of them
            log("Stats error:", e)

        last = state.get("last_draft_at")
        due = FORCE_DRAFT or (not state.get("paused") and (
            not last or now_utc() - datetime.fromisoformat(last) >= timedelta(minutes=DRAFT_EVERY_MINUTES - 5)))
        if due or state.pop("news_now", None):
            state["last_draft_at"] = now_utc().isoformat()
            draft_new_posts(state)
        save_state(state)
        listen(state, started + LISTEN_MINUTES * 60)
    except BaseException as e:   # also catches stops like KeyboardInterrupt/SystemExit, so memory is saved
        traceback.print_exc()
        note(state, f"run error: {type(e).__name__}: {str(e)[:150]}")
        try:
            tg_text(f"⚠️ Bot error:\n<code>{html.escape(str(e))[:800]}</code>")
        except Exception:
            pass
    finally:
        note(state, f"run end after {int(time.time() - started)} s")
        save_state(state)


if __name__ == "__main__":
    main()