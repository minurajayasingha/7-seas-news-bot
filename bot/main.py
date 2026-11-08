#!/usr/bin/env python3
"""
7 Seas News bot
---------------
Runs on GitHub Actions every ~15 minutes:
  1. Reads your Telegram button taps (Post now / Queue / Skip)
  2. Publishes approved posts to the Facebook Page (now, or at the next time slot)
  3. Every 2 hours: collects news from trusted RSS feeds, keeps only stories
     confirmed by 2+ outlets, asks Gemini to write a neutral post, makes the
     image, and sends it to your Telegram for approval.

All settings you might want to change are in the CONFIG section below.
"""

import io
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
    s.setdefault("recent_topics", [])   # [[iso_time, [keywords]]]
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


def draft_buttons(pid):
    return {"inline_keyboard": [
        [{"text": "🚀 Post now", "callback_data": f"now:{pid}"},
         {"text": "🕒 Queue", "callback_data": f"queue:{pid}"}],
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
    text = (f"✅ <b>Published</b> · {lk_time(now)} Sri Lanka · {ny_time(now)} New York · "
            f"{now.astimezone(ZoneInfo('Asia/Colombo')):%b %d}\n\n"
            f"<b>{html.escape(d['headline'])}</b>\n"
            f"<i>{html.escape(', '.join(d['sources']))}</i>"
            + (f"\n{news_time_text(d)}" if d.get("news_time") else "")
            + (f"\n\n🔗 <a href=\"{fb_link}\">Open on Facebook</a>" if fb_link else ""))
    if ch:
        j = tg("sendPhoto", chat_id=ch, photo=d["tg_file_id"], caption=text, parse_mode="HTML")
        if j.get("ok"):
            return True
    tg_text(text)   # no channel linked (or it failed): tell you in the bot chat
    return False


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
    if state.get("commands_set") == 3:
        return
    tg("setMyCommands", commands=[
        {"command": "queue", "description": "What's queued and when it posts"},
        {"command": "status", "description": "Bot summary"},
        {"command": "new", "description": "Make your own post"},
        {"command": "pause", "description": "Stop automatic news"},
        {"command": "resume", "description": "Start automatic news again"},
        {"command": "channel", "description": "Link the published-posts channel"},
        {"command": "help", "description": "How to use the bot"},
    ])
    state["commands_set"] = 3


def tg_download(file_id):
    j = tg("getFile", file_id=file_id)
    path = j["result"]["file_path"]
    r = HTTP.get(f"https://api.telegram.org/file/bot{TG_TOKEN}/{path}", timeout=60)
    r.raise_for_status()
    return r.content


# =============================================================================
# 1) READ BUTTON TAPS FROM TELEGRAM
# =============================================================================

def find_draft_by_message(state, message_id):
    for d in state["drafts"].values():
        if d.get("tg_message_id") == message_id and d["status"] in ("pending", "queued"):
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
        post = gemini_write(c)
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
        d["img_post"] = {k: bg_post.get(k) for k in ("headline", "people", "image_query", "image_style", "location")}
    if photo_id:
        d["bg"] = {"type": "photo", "photos": [{"tg_file_id": photo_id, "credit": ""}]}
    elif bg_post:
        d["bg"] = choose_background(bg_post)
    else:
        d["bg"] = {"type": "brand", "photos": []}
    if send_draft(state, d):
        tg("deleteMessage", chat_id=TG_CHAT, message_id=msg["message_id"])
        log("Manual draft made:", d["headline"])


def process_telegram(state):
    j = tg("getUpdates", offset=state["tg_offset"], timeout=0,
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
                tg("editMessageReplyMarkup", chat_id=TG_CHAT, message_id=d["tg_message_id"],
                   reply_markup=draft_buttons(pid))
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
            elif action == "now":
                d["status"] = "queued"
                d["queued_at"] = now_utc().isoformat()
                d["post_now"] = True
                tg_status(d, "🚀 Posting now…", cancel=False)
                log("Approved", pid, "now")
            elif action == "queue":
                d["status"] = "queued"
                d["queued_at"] = now_utc().isoformat()
                d["post_now"] = False
                plan = dict((x["id"], t) for x, t in queue_schedule(state))
                t = plan.get(pid)
                pos = list(plan).index(pid) + 1 if pid in plan else "?"
                tg_status(d, f"🕒 Queued · {lk_time(t)} SL" if t else "🕒 Queued", cancel=True)
                tg_reply(d, f"🕒 <b>Queued</b> (#{pos} in line)\nWill post at <b>{when_text(t)}</b>"
                         if t else "🕒 Queued")
                log("Approved", pid, "queue")
            continue

        msg = u.get("message")
        if not msg or str(msg.get("chat", {}).get("id")) != TG_CHAT:
            continue

        fwd = msg.get("forward_from_chat") or (msg.get("forward_origin") or {}).get("chat")
        if fwd and fwd.get("type") == "channel":
            state["log_channel"] = fwd["id"]
            t = tg("sendMessage", chat_id=fwd["id"],
                   text="✅ 7 Seas News bot connected. Published posts will appear here.")
            if t.get("ok"):
                tg_text(f"✅ Channel <b>{html.escape(fwd.get('title', ''))}</b> linked. "
                        "Every published post will be logged there.")
            else:
                state.pop("log_channel", None)
                tg_text("⚠️ I can't post in that channel yet. Add me to the channel as an "
                        "<b>admin</b> (with 'Post messages'), then forward a message again.")
            continue

        rep = msg.get("reply_to_message")
        if rep:
            d = find_draft_by_message(state, rep.get("message_id"))
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
        elif text.startswith("/new"):
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
            tg_text("📢 <b>Published-posts channel</b>\n"
                    "1. Create a Telegram channel (e.g. '7 Seas – Published')\n"
                    "2. Channel info → Administrators → Add admin → add this bot\n"
                    "3. Post any message in the channel and <b>forward it to me</b>\n\n"
                    + ("Currently linked ✅" if state.get("log_channel") else "Not linked yet."))
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
                    "🚀 <b>Post now</b> – publishes within ~15 min\n"
                    "🕒 <b>Queue</b> – publishes at the next US time slot\n"
                    "🔄 <b>Other photo</b> – tries a different picture\n"
                    "❌ <b>Skip</b> – drops it\n\n"
                    "✏️ <b>Change a post:</b> reply to it with\n"
                    "• a <b>photo</b> → new background image\n"
                    "• <b>text</b> → new headline\n"
                    "I send back the new version to approve.\n\n"
                    "✍️ <b>Your own post:</b> send a news link, or a photo with a headline (/new)\n\n"
                    "/queue – what's queued and when it posts\n"
                    "/pause · /resume – stop/start automatic news\n"
                    "/channel – link a channel that logs every published post\n"
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

    # drop stale queue items
    for d in queued:
        if now - datetime.fromisoformat(d["queued_at"]) > timedelta(hours=QUEUE_EXPIRE_HOURS):
            d["status"] = "expired"
            tg_clear(d)
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


def keywords(title, summary=""):
    words = set()
    for w in re.findall(r"[A-Za-z][A-Za-z'\-]+", title.lower()):
        w = w.strip("'-")
        if len(w) > 2 and w not in STOP:
            words.add(w[:-2] if w.endswith("'s") else w)
    # proper nouns from the summary help match the same story
    for w in re.findall(r"\b[A-Z][a-z]{2,}\b", summary):
        lw = w.lower()
        if lw not in STOP:
            words.add(lw)
    return words


def fetch_articles():
    now = now_utc()
    items = []
    for source, urls in FEEDS.items():
        for url in urls:
            try:
                r = HTTP.get(url, timeout=25)
                feed = feedparser.parse(r.content)
            except Exception as e:
                log("Feed failed:", source, url, e)
                continue
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
            if similar(it["kw"], c["kw"]) and len(it["title_kw"] & c["title_kw"]) >= 1:
                best = c
                break
        if best:
            best["items"].append(it)
            best["kw"] |= it["kw"]
            best["title_kw"] |= it["title_kw"]
        else:
            clusters.append({"items": [it], "kw": set(it["kw"]), "title_kw": set(it["title_kw"])})
    return clusters


def pick_stories(state, items):
    now = now_utc()
    seen = set(state["seen_links"])
    recent = [set(t[1]) for t in state["recent_topics"]]
    good = []
    for c in cluster(items):
        sources = {i["source"] for i in c["items"]}
        if len(sources) < MIN_SOURCES:
            continue
        if any(i["link"] in seen for i in c["items"]):
            continue
        if any(len(c["title_kw"] & r) >= 4 for r in recent):
            continue  # same topic posted recently
        newest = max(i["published"] for i in c["items"])
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
"headline": 6 to 12 words. Catchy and 100% factual: the most striking fact first, strong verb, names/numbers from the reports. A colon is allowed for impact (e.g. "Pope Leo lands in Uruguay: first stop of South America tour"). No question headlines, no "you won't believe", no ALL-CAPS words (except abbreviations like US, UN), no emojis, no ending period.
"summary": 2 or 3 short sentences (max 60 words) saying what happened and why it matters.
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
"image_query": 2 to 4 words for a photo of the most relevant PLACE or landmark (never a person), as specific as possible, e.g. "Montevideo skyline", "US Capitol building", "Kyiv city", "United Nations Security Council".
"people": a list of 0 to 3 real people who are the MAIN subject of the story AND are named in your headline, full names exactly as written in the reports, e.g. ["Donald Trump", "Vladimir Putin"]. People who are only mentioned in the background must NOT be listed. Use [] if the headline names no person (for example a story about a country, party, vote or attack).
"skip": true if this is about South Asia, is not hard news (opinion, sport, entertainment, live blog), or the reports describe different events. Otherwise false.
"""


def gemini_models():
    models = [GEMINI_MODEL] if GEMINI_MODEL else []
    models += ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
    return list(dict.fromkeys(models))


def gemini_write(c):
    reports = "\n\n".join(
        f"Outlet: {i['source']}\nTitle: {i['title']}\nSummary: {i['summary']}"
        for i in c["items"][:6]
    )
    body = {
        "contents": [{"parts": [{"text": PROMPT.format(reports=reports)}]}],
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

WIKI_HEADERS = {"User-Agent": "7SeasNewsBot/1.0 (news page image bot; runs on GitHub Actions)"}
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

def wiki_person_photo(name):
    """Main photo of a person's Wikipedia article, only if it is free to use."""
    try:
        r = HTTP.get("https://en.wikipedia.org/w/api.php", headers=WIKI_HEADERS, timeout=20, params={
            "action": "query", "prop": "pageimages", "piprop": "name",
            "titles": name, "redirects": 1, "format": "json"})
        page = next(iter(r.json()["query"]["pages"].values()))
        fname = page.get("pageimage")
        if not fname:
            return None
        r = HTTP.get("https://commons.wikimedia.org/w/api.php", headers=WIKI_HEADERS, timeout=20, params={
            "action": "query", "titles": "File:" + fname, "prop": "imageinfo",
            "iiprop": "url|extmetadata", "iiurlwidth": 1200, "format": "json"})
        page = next(iter(r.json()["query"]["pages"].values()))
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


def pexels_photo(query):
    if not PEXELS_KEY or not query:
        return None
    try:
        r = HTTP.get("https://api.pexels.com/v1/search", timeout=30,
                     params={"query": query, "orientation": "portrait", "per_page": 6},
                     headers={"Authorization": PEXELS_KEY})
        photos = r.json().get("photos", [])
        if not photos:
            return None
        p = random.choice(photos[:4])
        return {"url": p["src"]["large2x"],
                "credit": f"{p.get('photographer', 'Pexels')} / Pexels", "short": "PEXELS"}
    except Exception as e:
        log("Pexels failed:", e)
        return None


def pixabay_photo(query, exclude=()):
    if not PIXABAY_KEY or not query:
        return None
    try:
        r = HTTP.get("https://pixabay.com/api/", timeout=30, params={
            "key": PIXABAY_KEY, "q": query[:100], "image_type": "photo", "order": "popular",
            "safesearch": "true", "per_page": 20, "min_width": 1600})
        hits = [h for h in r.json().get("hits", []) if h["largeImageURL"] not in exclude]
        if not hits:
            return None
        p = max(hits[:10], key=lambda h: h.get("likes", 0) + h.get("downloads", 0) / 100)
        return {"url": p["largeImageURL"],
                "credit": f"{p.get('user', 'Pixabay')} / Pixabay", "short": "PIXABAY"}
    except Exception as e:
        log("Pixabay failed:", e)
        return None


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


def wiki_search_photo(query, exclude=()):
    """Best free-licensed photo from Wikimedia Commons. No key needed.
    Looks at 'Quality images' first, skips old/black-and-white pictures, checks colour and sharpness."""
    if not query:
        return None
    cands, seen = [], set()
    for bonus, q in ((25, f"{query} incategory:Quality_images"), (0, query)):
        try:
            r = HTTP.get("https://commons.wikimedia.org/w/api.php", headers=WIKI_HEADERS, timeout=30, params={
                "action": "query", "generator": "search", "gsrnamespace": 6,
                "gsrsearch": f"{q} filetype:bitmap filew:>1500", "gsrlimit": 15,
                "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime",
                "iiurlwidth": 1600, "format": "json"})
            pages = sorted(r.json().get("query", {}).get("pages", {}).values(),
                           key=lambda p: p.get("index", 99))
        except Exception as e:
            log("Wikimedia search failed:", e)
            continue
        for rank, page in enumerate(pages):
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("thumburl") or info.get("url")
            if not url or url in exclude or url in seen:
                continue
            if info.get("mime") not in ("image/jpeg", "image/png") or info.get("width", 0) < 1200:
                continue
            meta = info.get("extmetadata", {})
            lic = clean_html(meta.get("LicenseShortName", {}).get("value", ""))
            if not lic.lower().startswith(FREE_LICENSES):
                continue
            title = page.get("title", "").lower()
            if re.search(r"(?<!\d)(1[0-8]\d\d|19[0-8]\d)(?!\d)", title) or any(
                    w in title for w in ("old ", "historic", "postcard", "vintage", "engraving", "painting",
                                         "drawing", "map", "lithograph", "sepia", "diagram", "logo", "flag of")):
                continue
            yr = re.search(r"(1[89]\d\d|20\d\d)", clean_html(meta.get("DateTimeOriginal", {}).get("value", "")))
            year = int(yr.group(1)) if yr else 0
            if year and year < 2000:
                continue
            seen.add(url)
            artist = clean_html(meta.get("Artist", {}).get("value", ""))[:60] or "Unknown author"
            score = bonus + (10 if year >= 2015 else 0) + max(0, 12 - rank) \
                + min(10, info.get("width", 0) / 600)
            cands.append((score, {"url": url, "credit": f"{artist} / Wikimedia Commons ({lic})",
                                  "short": "WIKIMEDIA COMMONS"}))
    best, best_score = None, -1
    for score, c in sorted(cands, key=lambda x: -x[0])[:6]:   # check the top 6 by eye
        q = photo_quality(c["url"])
        if q < 0:
            continue
        if score + q > best_score:
            best, best_score = c, score + q
    return best


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
    """1) photos of the people in the story  2) best matching photo  3) brand design.
    prefer_scene=True is used by the 🔄 Other photo button."""
    found = [x for x in (wiki_person_photo(p) for p in person_names_in_headline(post)) if x]

    if post.get("image_style") == "incident" and not found and not prefer_scene:
        # no random photos for shootings/bombings: strong news design with a location tag
        return {"type": "incident", "photos": [], "location": str(post.get("location") or "")[:40]}

    scene = None
    if prefer_scene or post.get("image_style") == "scene" or not found:
        for q in [post.get("image_query", ""), post.get("location", "")]:
            q = str(q or "").strip()
            if q:
                scene = pexels_photo(q) or pixabay_photo(q, exclude) or wiki_search_photo(q, exclude)
            if scene:
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


def render_image(headline, label, sources, bg):
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

    for ln in lines:
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
    d.text((W - M, ty), now_utc().strftime("%b %d, %Y").upper(), font=sf, fill=SOFT, anchor="ra")
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
    lines += ["", f"{tags} {BRAND_HASHTAG}".strip()]
    return "\n".join(lines)


def send_draft(state, d):
    """Make the image, send it to Telegram with buttons, remember it."""
    img = render_image(d["headline"], "BREAKING NEWS" if d.get("breaking") else d["label"],
                       d["sources"], d["bg"])
    d["caption"] = build_caption(d)
    links = "\n".join(f'• <a href="{html.escape(u)}">{html.escape(s)}</a>' for s, u in d["links"][:4])
    nt = news_time_text(d)
    if d.get("breaking"):
        nt = "🚨 <b>BREAKING</b>" + (f"\n{nt}" if nt else "")
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
           reply_markup=draft_buttons(d["id"]))
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
            post = gemini_write(c)
        except Exception as e:
            log("Skipping story, Gemini failed:", e)
            if "429" in str(e):
                break
            continue
        if post.get("skip"):
            log("Gemini marked skip:", c["items"][0]["title"])
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
            "img_post": {k: post.get(k) for k in ("headline", "people", "image_query", "image_style", "location")},
            "created_at": now_utc().isoformat(),
            "news_time": min(i["published"] for i in c["items"]).isoformat(),
            "news_latest": max(i["published"] for i in c["items"]).isoformat(),
        }
        if send_draft(state, d):
            state["recent_topics"].append([now_utc().isoformat(), sorted(c["title_kw"])])
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

def main():
    missing = [n for n, v in [("TELEGRAM_BOT_TOKEN", TG_TOKEN), ("TELEGRAM_CHAT_ID", TG_CHAT),
                              ("GEMINI_API_KEY", GEMINI_KEY), ("FB_PAGE_ID", FB_PAGE_ID),
                              ("FB_PAGE_TOKEN", FB_TOKEN)] if not v]
    if missing:
        print("Missing secrets:", ", ".join(missing))
        sys.exit(1)

    state = load_state()
    try:
        set_commands_once(state)
        process_telegram(state)
        publish_due(state)
        expire_pending(state)

        last = state.get("last_draft_at")
        due = FORCE_DRAFT or (not state.get("paused") and (
            not last or now_utc() - datetime.fromisoformat(last) >= timedelta(minutes=DRAFT_EVERY_MINUTES - 5)))
        if due:
            state["last_draft_at"] = now_utc().isoformat()
            draft_new_posts(state)
    except Exception as e:
        traceback.print_exc()
        try:
            tg_text(f"⚠️ Bot error:\n<code>{html.escape(str(e))[:800]}</code>")
        except Exception:
            pass
    finally:
        save_state(state)


if __name__ == "__main__":
    main()