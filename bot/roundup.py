"""7 Seas News — daily roundup videos (Stage 3 + 4 of docs/AUTOMATION_PLAN.md).

Run by .github/workflows/roundup.yml after you approve the plan in Telegram (or after 3 hours by itself):
    python bot/roundup.py --day 2026-11-16 [--test]

1. reads the approved plan + the day's posts from state/state.json (read only: the normal bot owns that file)
2. per part: the TikTok slides (1080x1350 cover + each post), the 1080x1920 video and its cover
3. uploads: Facebook Reel (scheduled), YouTube Short (scheduled) — not in --test
4. sends the TikTok slides + texts and a backup package to Telegram
5. writes the results to state/roundup.json (the normal bot reads it for the reminders)
"""
import argparse
import copy
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main as M                                   # noqa: E402  (all the bot's tools: images, Telegram, Facebook)
from main import Image, ImageDraw, ImageFilter     # noqa: E402
from settings import *                             # noqa: E402,F401,F403

RW, RH, FPS, W, H = M.RW, M.RH, M.FPS, M.W, M.H
POST_Y = M.REEL_IMG_Y                              # 285: where the 1080x1350 post sits in the 9:16 frame
TOP_FILL, BOTTOM_FILL = (25, 25, 27), (8, 8, 8)
YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "").strip()
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN", "").strip()
log = M.log


# =============================================================================
# TEXTS (titles, captions, tags) — the approved rules
# =============================================================================

def trim(text, n):
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[:n - 1].rsplit(" ", 1)[0].rstrip(",;:-–·") + "…"


def lower_tags(xs):
    return [t for t in dict.fromkeys("#" + re.sub(r"[^a-z0-9]", "", str(x).lower().lstrip("#")) for x in xs) if len(t) > 1]


def part_texts(day, n, part, posts, post_at):
    """All words for one part: TikTok title/caption, YouTube title/description/tags, Facebook caption."""
    weekday, mon = f"{day:%A}", f"{day:%b} {day.day}"
    title = part.get("title") or posts[0]["headline"]
    hook = part.get("hook") or ""
    q = part.get("question") or ""
    tags_tt = lower_tags(part.get("hashtags", []) + ["#7seasnews", "#newstok", "#news", "#worldnews"])[:7]
    tags_fb = lower_tags(part.get("hashtags", [])[:2] + ["#7seasnews", "#news", "#worldnews"])[:5]
    tags_yt = lower_tags(part.get("hashtags", []) + ["#7seasnews", "#news", "#shorts"])[:6]

    end = f" · {weekday}'s top stories (Part {n}/3)"
    tiktok_title = trim(title, 90 - len(end)) + end
    tiktok_caption = "\n".join(x for x in [hook, "", f"Part {n}/3 · {weekday}, {mon}", "Follow 7 Seas News for more 🔔",
                                           "", q, "", " ".join(tags_tt)])
    tiktok_caption = re.sub(r"\n{3,}", "\n\n", tiktok_caption)
    yt_end = f" | {weekday}'s Top Stories, {mon} (Part {n}/3) #shorts"
    yt_title = trim(title, 100 - len(yt_end)) + yt_end
    yt_desc = "\n".join([hook, "", f"{weekday}'s top stories, {mon}, {day.year} — Part {n}/3 · {part['name']}", ""]
                        + [f"{k}. {d['headline']}" for k, d in enumerate(posts, 1)]
                        + ["", "Real News. No Noise.", "Follow 7 Seas News for verified world news every day.", "",
                           " ".join(tags_yt)])
    yt_tags, total = [], 0
    for t in list(part.get("tags", [])) + ["7 seas news", "world news", "news", "us news", "breaking news",
                                           part["name"].lower(), f"news {mon.lower()}"]:
        t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", str(t).lower().replace("&", " and "))).strip()
        if t and t not in yt_tags and total + len(t) + 1 < 450:
            yt_tags.append(t)
            total += len(t) + 1
    fb_caption = "\n\n".join(x for x in [hook, f"{weekday}'s top stories · Part {n}/3", FOLLOW_LINE,
                                         " ".join(tags_fb)] if x)
    return {"tiktok_title": tiktok_title, "tiktok_caption": tiktok_caption.strip(), "yt_title": yt_title,
            "yt_description": yt_desc[:4900], "yt_tags": yt_tags, "fb_caption": fb_caption,
            "post_at": post_at.isoformat()}


# =============================================================================
# PICTURES: cover, story frames
# =============================================================================

def make_cover(day, n, part):
    """1080x1350 cover: PART n/3 · NAME → huge NOV 16 (day red) → TOP STORIES → hook with red bar → MONDAY · 2026."""
    img = M.branded_background()
    d = ImageDraw.Draw(img)
    X = 64
    if os.path.exists(M.LOGO_FILE):
        logo = Image.open(M.LOGO_FILE).convert("RGBA")
        lw = 330
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        img.paste(logo, (X, 64), logo)
    label = f"PART {n}/3 · {part['name']}"
    lf = M.font("Poppins-SemiBold.ttf", 30)
    lw = M.spaced_width(d, label, lf, 3)
    y = 420
    d.rectangle([X, y, X + lw + 44, y + 60], fill=RED)
    M.spaced(d, (X + 22, y + 11), label, lf, WHITE, 3)
    # huge date: month white, day number red
    mon, num = f"{day:%b}".upper() + " ", str(day.day)
    size = 230
    while True:
        df = M.font("Poppins-Bold.ttf", size)
        if d.textlength(mon + num, font=df) <= W - 2 * X or size <= 120:
            break
        size -= 10
    y += 80
    d.text((X, y), mon, font=df, fill=WHITE)
    d.text((X + d.textlength(mon, font=df), y), num, font=df, fill=RED)
    y += int(size * 1.08)
    tf = M.font("Poppins-Bold.ttf", 92)
    d.text((X, y), "TOP STORIES", font=tf, fill=WHITE)
    y += 140
    hf = M.font("Poppins-SemiBold.ttf", 44)
    lines = M.wrap(d, part.get("hook") or "", hf, W - 2 * X - 40)
    while len(lines) > 2 and hf.size > 32:
        hf = M.font("Poppins-SemiBold.ttf", hf.size - 3)
        lines = M.wrap(d, part.get("hook") or "", hf, W - 2 * X - 40)
    lines = lines[:2]
    lh = int(hf.size * 1.3)
    d.rectangle([X, y + 4, X + 10, y + lh * len(lines) - 6], fill=RED)
    for k, ln in enumerate(lines):
        d.text((X + 36, y + k * lh), ln, font=hf, fill=WHITE)
    y += lh * max(1, len(lines)) + 34
    sf = M.font("Poppins-Medium.ttf", 30)
    M.spaced(d, (X, y), f"{day:%A} · {day.year}".upper(), sf, SOFT, 4)
    # footer
    ft = H - 112
    d.rectangle([X, ft, W - X, ft + 3], fill=RED)
    ff = M.font("Poppins-Medium.ttf", 24)
    M.spaced(d, (X, ft + 30), "VERIFIED WORLD NEWS · EVERY DAY", ff, SOFT, 3)
    sw = M.font("Poppins-Bold.ttf", 28)
    ax, ay = W - X, ft + 47                              # arrow drawn (Poppins has no → sign)
    d.line([(ax - 34, ay), (ax - 2, ay)], fill=WHITE, width=4)
    d.polygon([(ax, ay), (ax - 13, ay - 10), (ax - 13, ay + 10)], fill=WHITE)
    d.text((ax - 48, ft + 26), "SWIPE", font=sw, fill=WHITE, anchor="ra")
    return img


def tall(img_4x5):
    """1080x1350 picture in the middle of a 1080x1920 frame: top (25,25,27), bottom (8,8,8)."""
    frame = Image.new("RGB", (RW, RH), BOTTOM_FILL)
    frame.paste(Image.new("RGB", (RW, POST_Y), TOP_FILL), (0, 0))
    frame.paste(img_4x5, (0, POST_Y))
    return frame


def jpg(img, q=92):
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=q, optimize=True)
    return out.getvalue()


FEATHER = 120
_FEATHER_MASK = {}


def feather_mask():
    if "m" not in _FEATHER_MASK:
        m = Image.new("L", (W, H), 255)
        dr = ImageDraw.Draw(m)
        for y in range(FEATHER):
            k = y / FEATHER
            dr.line([(0, y), (W, y)], fill=int(255 * (k * k * (3 - 2 * k))))      # smooth 0 → 255
        _FEATHER_MASK["m"] = m
    return _FEATHER_MASK["m"]


def story_frame(d, day, k, total):
    """(frame without headline, layout) for one story. layout None = the headline is already in the picture
    (the photo would not download: the published image is used as it is)."""
    label = "BREAKING NEWS" if d.get("breaking") else d.get("label", "WORLD")
    lay, bg = {}, copy.deepcopy(d.get("bg") or {"type": "brand", "photos": []})
    clean = Image.open(io.BytesIO(M.render_image(d["headline"], label, d.get("sources", []), bg,
                                                 hide_headline=True, layout=lay, date=day))).convert("RGB")
    if bg.get("photos") and not bg.get("_loaded"):
        clean = Image.open(io.BytesIO(M.tg_download(d["tg_file_id"]))).convert("RGB").resize((W, H))
        lay = None
    frame = Image.new("RGB", (RW, RH), BLACK)
    # top: blurred (r 34), 45 % darker zoom of the photo area (post rows 170–900), feathered into the post
    area = clean.crop((0, 170, W, 900))
    top = M.cover(area, RW, POST_Y + FEATHER, 0.5).filter(ImageFilter.GaussianBlur(34))
    top = Image.blend(top, Image.new("RGB", top.size, BLACK), 0.45)
    frame.paste(top, (0, 0))
    strip = clean.crop((0, H - 6, W, H)).resize((1, 1), Image.LANCZOS).getpixel((0, 0))
    frame.paste(Image.new("RGB", (RW, RH - POST_Y - H), strip), (0, POST_Y + H))
    frame.paste(clean, (0, POST_Y), feather_mask())
    # counter pill "01 / 13" top-right
    dr = ImageDraw.Draw(frame)
    pf = M.font("Poppins-Bold.ttf", 34)
    txt = f"{k:02d} / {total}"
    tw = dr.textlength(txt, font=pf)
    x1, y1 = RW - 48, 48
    dr.rounded_rectangle([x1 - tw - 48, y1, x1, y1 + 66], radius=33, fill=(0, 0, 0), outline=(255, 255, 255), width=2)
    dr.text((x1 - tw - 24, y1 + 12), txt, font=pf, fill=WHITE)
    return frame, lay


def end_card():
    return M.reel_end_card()                      # logo + FOLLOW FOR MORE + VERIFIED WORLD NEWS · EVERY DAY


# =============================================================================
# SOUND
# =============================================================================

def _boom():
    import math
    n = int(1.2 * M.AUDIO_SR)
    out = []
    for k in range(n):
        t = k / M.AUDIO_SR
        f = 42 + 30 * math.exp(-t / 0.15)
        out.append(math.sin(2 * math.pi * f * t) * math.exp(-t / 0.45) * min(1.0, t / 0.01) * 0.95)
    return out


def part_audio(seconds, keys, whooshes):
    import wave
    import array
    buf = [0.0] * int(seconds * M.AUDIO_SR)
    rng = random.Random(len(keys))
    M._add(buf, 0.0, _boom())
    if REEL_TYPING_SOUND:
        click = {False: [M._key_click(rng) for _ in range(6)], True: [M._key_click(rng, True) for _ in range(3)]}
        for t, ch in keys:
            M._add(buf, t + rng.uniform(-0.006, 0.006), rng.choice(click[ch == " "]))
    wh = M._whoosh(0.5)
    for t in whooshes:
        M._add(buf, max(0.0, t - 0.1), wh)
    peak = max(1e-9, max(abs(v) for v in buf))
    gain = min(1.0, 0.89 / peak) * max(0.0, min(1.0, REEL_SOUND_VOLUME))
    pcm = array.array("h", (int(max(-1.0, min(1.0, v * gain)) * 32767) for v in buf))
    mem = io.BytesIO()
    with wave.open(mem, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(M.AUDIO_SR)
        w.writeframes(pcm.tobytes())
    return mem.getvalue()


def music_file():
    if str(ROUNDUP_MUSIC).lower() == "off":
        return None
    folder = os.path.join(M.ROOT, ROUNDUP_MUSIC) if not os.path.isabs(ROUNDUP_MUSIC) else ROUNDUP_MUSIC
    try:
        files = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                 if f.lower().endswith((".mp3", ".m4a", ".wav", ".aac", ".ogg"))]
    except FileNotFoundError:
        return None
    return random.choice(files) if files else None


# =============================================================================
# VIDEO
# =============================================================================

COVER_S, SWIPE_S, HOLD_S, END_S = 1.3, 0.4, 2.2, 2.4
MAX_SECONDS = 88                                   # Facebook Reels: max 90 s


def make_part_video(day, n, part, posts, cover_4x5):
    """MP4 bytes of one part (1080x1920, 30 fps, H.264 + AAC)."""
    t0 = time.time()
    frames = [story_frame(d, day, k, len(posts)) for k, d in enumerate(posts, 1)]
    cover_t = tall(cover_4x5)
    end = end_card()
    hfonts = {}

    def typing_s(lay):
        chars = sum(len(x) for x in lay["lines"]) if lay else 0
        return min(3.0, max(1.2, chars * 0.042)) if lay else 0.6

    hold = HOLD_S
    fixed = COVER_S + END_S + SWIPE_S * (len(posts) + 1) + sum(typing_s(l) for _, l in frames)
    if fixed + hold * len(posts) > MAX_SECONDS:
        hold = max(1.2, (MAX_SECONDS - fixed) / len(posts))
    # timeline: ("cover", f0, f1) ("swipe", f0, f1, from, to) ("story", f0, f1, i, type_frames)
    segs, f = [], 0

    def add(kind, seconds, *extra):
        nonlocal f
        nf = max(1, int(round(seconds * FPS)))
        segs.append((kind, f, f + nf) + extra)
        f += nf
    add("cover", COVER_S)
    prev = ("cover", None)
    for i, (img, lay) in enumerate(frames):
        add("swipe", SWIPE_S, prev, ("story", i))
        ts = typing_s(lay)
        add("story", ts + hold, i, int(ts * FPS))
        prev = ("story", i)
    add("swipe", SWIPE_S, prev, ("end", None))
    add("end", END_S)
    total = f
    seconds = total / FPS

    # sounds: one click per letter, a whoosh per swipe
    keys, whooshes = [], []
    for s in segs:
        if s[0] == "swipe":
            whooshes.append(s[1] / FPS)
        if s[0] == "story":
            lay = frames[s[3]][1]
            if lay:
                text = "".join(lay["lines"])
                for c in range(len(text)):
                    keys.append(((s[1] + s[4] * (c + 1) / len(text)) / FPS, text[c]))
    measure = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    def still(which, typed=None, blink=True):
        kind, i = which
        if kind == "cover":
            return cover_t
        if kind == "end":
            return end
        img, lay = frames[i]
        if not lay:
            return img
        lines, size = lay["lines"], lay["size"]
        if size not in hfonts:
            hfonts[size] = M.font("Poppins-Bold.ttf", size)
        hf = hfonts[size]
        total_c = sum(len(x) for x in lines)
        shown = total_c if typed is None else typed
        out = img.copy()
        dr = ImageDraw.Draw(out)
        x0, y, lh = lay["x"], lay["y"] + POST_Y, lay["line_h"]
        left, cx, cy = shown, x0, y
        for ln in lines:
            part_ = ln[:max(0, left)]
            if part_:
                dr.text((x0 + 2, y + 3), part_, font=hf, fill=(0, 0, 0))
                dr.text((x0, y), part_, font=hf, fill=WHITE)
            if left > 0:
                cx, cy = x0 + measure.textlength(part_, font=hf), y
            left -= len(ln)
            y += lh
            if left <= 0:
                break
        if blink:
            dr.rectangle([cx + 6, cy + int(size * 0.18), cx + 6 + max(5, size // 12), cy + int(size * 1.12)], fill=RED)
        return out

    ff = M.ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        wav, out = os.path.join(tmp, "sound.wav"), os.path.join(tmp, "part.mp4")
        with open(wav, "wb") as fh:
            fh.write(part_audio(seconds + 0.5, keys, whooshes))
        cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}",
               "-r", str(FPS), "-i", "-", "-i", wav]
        mus = music_file()
        if mus:
            cmd += ["-stream_loop", "-1", "-i", mus, "-filter_complex",
                    "[2:a]volume=0.12[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]", "-map", "0:v", "-map", "[a]"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "3500k", "-bufsize", "7000k",
                "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000",
                "-t", f"{seconds:.2f}", "-movflags", "+faststart", out]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        cache = {}
        try:
            for s in segs:
                kind, a, b = s[0], s[1], s[2]
                for fr in range(a, b):
                    if kind in ("cover", "end"):
                        img = still((kind, None))
                    elif kind == "story":
                        i, tf = s[3], s[4]
                        lay = frames[i][1]
                        total_c = sum(len(x) for x in lay["lines"]) if lay else 0
                        typed = min(total_c, int((fr - a + 1) / max(1, tf) * total_c)) if fr - a < tf else total_c
                        blink = typed < total_c or ((fr - a) // 15) % 2 == 0
                        key = (i, typed, blink)
                        if key not in cache:
                            cache = {key: still(("story", i), typed, blink)}
                        img = cache[key]
                    else:                                       # red swipe with a white edge
                        p = (fr - a + 1) / (b - a)
                        src, dst = s[3], s[4]
                        if p <= 0.5:
                            base = still(src) if src[0] != "story" else still(src)
                            img = base.copy()
                            x = int(RW * p * 2)
                            dr = ImageDraw.Draw(img)
                            dr.rectangle([0, 0, x, RH], fill=RED)
                            dr.rectangle([x, 0, x + 12, RH], fill=WHITE)
                        else:
                            base = still(dst, 0, True) if dst[0] == "story" else still(dst)
                            img = base.copy()
                            x = int(RW * (p - 0.5) * 2)
                            dr = ImageDraw.Draw(img)
                            dr.rectangle([x, 0, RW, RH], fill=RED)
                            dr.rectangle([x - 12, 0, x, RH], fill=WHITE)
                    if kind != "swipe":
                        img = img.copy()
                    ImageDraw.Draw(img).rectangle([0, 0, int(RW * (fr + 1) / total), 8], fill=RED)   # progress
                    proc.stdin.write(img.tobytes())
            proc.stdin.close()
            err = proc.stderr.read().decode(errors="ignore")
            if proc.wait() != 0:
                raise RuntimeError("ffmpeg failed: " + err[-300:])
        except BrokenPipeError:
            proc.wait()
            raise RuntimeError("ffmpeg stopped: " + proc.stderr.read().decode(errors="ignore")[-300:])
        data = open(out, "rb").read()
    log(f"Part {n}: {len(posts)} stories, {seconds:.1f} s, {len(data) / 1e6:.1f} MB, made in {time.time() - t0:.0f} s")
    return data, seconds


# =============================================================================
# UPLOADS
# =============================================================================

def retry_once(what, fn):
    try:
        return fn()
    except Exception as e:
        log(f"{what} failed, trying once more:", e)
        time.sleep(20)
        return fn()


def facebook_upload(video, cover_jpg, texts, post_at):
    """Reel scheduled for post_at. If Facebook refuses to schedule Reels: saved as a draft, and the normal bot
    publishes it at the time."""
    vid = retry_once("Facebook upload", lambda: M.fb_reel_upload(video))
    try:
        retry_once("Facebook schedule", lambda: M.fb_reel_finish(vid, texts["fb_caption"], "SCHEDULED", post_at))
        st = "scheduled"
    except Exception as e:
        log("Facebook won't schedule the Reel, saving it as a draft:", e)
        M.fb_reel_finish(vid, texts["fb_caption"], "DRAFT")
        st = "draft"
    M.fb_reel_cover(vid, cover_jpg)
    return {"id": vid, "state": st, "caption": texts["fb_caption"]}


def yt_token():
    r = M.HTTP.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": YT_CLIENT_ID, "client_secret": YT_CLIENT_SECRET, "refresh_token": YT_REFRESH_TOKEN,
        "grant_type": "refresh_token"})
    j = r.json()
    if "access_token" not in j:
        raise RuntimeError("YouTube login: " + str(j.get("error_description") or j.get("error") or j)[:200])
    return j["access_token"]


def youtube_upload(video, thumb_jpg, texts, post_at):
    """YouTube Data API v3: resumable upload as private + publishAt (= scheduled), then the thumbnail."""
    tok = yt_token()
    body = {"snippet": {"title": texts["yt_title"], "description": texts["yt_description"], "tags": texts["yt_tags"],
                        "categoryId": "25", "defaultLanguage": "en-US", "defaultAudioLanguage": "en-US"},
            "status": {"privacyStatus": "private", "publishAt": post_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False}}

    def go():
        r = M.HTTP.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                        json=body, timeout=60, headers={"Authorization": f"Bearer {tok}",
                                                        "X-Upload-Content-Type": "video/mp4",
                                                        "X-Upload-Content-Length": str(len(video))})
        if r.status_code >= 300 or not r.headers.get("Location"):
            raise RuntimeError(f"YouTube start {r.status_code}: {r.text[:300]}")
        u = M.HTTP.put(r.headers["Location"], data=video, timeout=900,
                       headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4"})
        if u.status_code >= 300:
            raise RuntimeError(f"YouTube upload {u.status_code}: {u.text[:300]}")
        return u.json()
    j = retry_once("YouTube upload", go)
    vid = j["id"]
    status = (j.get("status") or {})
    try:
        t = M.HTTP.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}", data=thumb_jpg,
                        timeout=60, headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"})
        if t.status_code >= 300:
            log("YouTube thumbnail not set (needs a verified channel):", t.text[:200])
    except Exception as e:
        log("YouTube thumbnail failed:", e)
    return {"id": vid, "state": "scheduled" if status.get("publishAt") else status.get("privacyStatus", "uploaded"),
            "url": f"https://youtube.com/shorts/{vid}"}


# =============================================================================
# TELEGRAM: TikTok slides + backup package
# =============================================================================

def esc(t):
    return M.html.escape(str(t))


def when(post_at):
    return f"{M.ny_time(post_at)} NY ({M.lk_time(post_at)} SL)"


def send_tiktok(ch, n, part, texts, slides, post_at, day):
    """a) text with title + caption to copy  b) the slides as photo albums  c) one zip of full-quality slides."""
    ny_date = post_at.astimezone(M.ZoneInfo(SLOT_TIMEZONE))
    M.tg("sendMessage", chat_id=ch, parse_mode="HTML", disable_web_page_preview="true", text=(
        f"📲 <b>TikTok Part {n}/3</b> · {esc(part['name'])} · post at {when(post_at)} · "
        f"{ny_date:%b} {ny_date.day}, {ny_date.year} (New York, for TikTok Studio)\n\n"
        f"<b>Title</b> (tap to copy):\n<code>{esc(texts['tiktok_title'])}</code>\n\n"
        f"<b>Caption</b> (tap to copy):\n<code>{esc(texts['tiktok_caption'])}</code>\n\n"
        f"📱 Open the album below → ⋮ → <b>Save to gallery</b> → TikTok ＋ → Photos → tap 1, 2, 3… in order."))
    kind = "document" if str(TIKTOK_SLIDES_AS).lower() == "files" else "photo"
    total = len(slides)
    chunks = [list(range(a, min(total, a + 10))) for a in range(0, total, 10)]
    if len(chunks) > 1 and len(chunks[-1]) == 1:          # an album needs 2+ photos: 11 → 9 + 2
        chunks[-1].insert(0, chunks[-2].pop())
    for chunk in chunks:
        media, files = [], {}
        for k in chunk:
            name, data, label = slides[k]
            files[f"s{k}"] = (name, data, "image/jpeg")
            media.append({"type": kind, "media": f"attach://s{k}", "caption": f"{k + 1}/{total} · {label}"[:200]})
        j = M.tg("sendMediaGroup", chat_id=ch, media=media, files=files)
        if not j.get("ok"):
            raise RuntimeError("Telegram album: " + str(j.get("description")))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, data, _ in slides:
            z.writestr(f"part{n}/{name}", data)
    M.tg("sendDocument", chat_id=ch, caption=f"🗂 TikTok Part {n}/3 slides, full quality ({total} images)",
         files={"document": (f"tiktok_{day:%Y-%m-%d}_part{n}.zip", buf.getvalue(), "application/zip")})


def descriptions_txt(day, parts_out):
    out = [f"7 SEAS NEWS — ROUNDUP OF {day:%A, %B} {day.day}, {day.year} (New York)", "=" * 60, ""]
    for n, p in enumerate(parts_out, 1):
        t, at = p["texts"], datetime.fromisoformat(p["texts"]["post_at"])
        out += [f"PART {n}/3 · {p['name']} · {len(p['posts'])} stories · {p['seconds']:.0f} s",
                f"Post at: {when(at)}", "",
                "TIKTOK TITLE:", t["tiktok_title"], "", "TIKTOK CAPTION:", t["tiktok_caption"], "",
                "YOUTUBE TITLE:", t["yt_title"], "", "YOUTUBE DESCRIPTION:", t["yt_description"], "",
                "YOUTUBE TAGS:", ", ".join(t["yt_tags"]), "", "FACEBOOK CAPTION:", t["fb_caption"], "", "-" * 60, ""]
    return "\n".join(out)


# =============================================================================
# THE JOB
# =============================================================================

def post_times(day, test):
    """8 / 10 / 12 New York the next morning; if we are late, all three move by the same amount."""
    times = M.roundup_times(day)
    if test:
        return times
    earliest = M.now_utc() + timedelta(minutes=25)
    if times[0] < earliest:
        shift = earliest - times[0]
        log("Late: moving the roundup times by", shift)
        times = [t + shift for t in times]
    return times


def save_result(day_s, res):
    path = M.ROUNDUP_FILE
    data = M.load_roundup_file()
    data[day_s] = res
    for k in sorted(data)[:-10]:
        data.pop(k)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def run(day_s, test=False):
    state = M.load_state()
    M.PHOTO_MEM = state.setdefault("photo_memory", {})
    info = state.get("roundup", {}).get(day_s)
    if not info or not info.get("plan"):
        raise RuntimeError(f"no approved plan for {day_s} in state.json")
    test = test or bool(info.get("test"))
    day = datetime.fromisoformat(day_s).date()
    plan = info["plan"]
    drafts = state["drafts"]
    ch = state.get("tiktok_channel") or M.TG_CHAT
    parts_out = []
    for n, part in enumerate(plan["parts"], 1):
        posts = [drafts[plan["ids"][k - 1]] for k in part["stories"]
                 if k - 1 < len(plan["ids"]) and plan["ids"][k - 1] in drafts]
        if not posts:
            continue
        cover = make_cover(day, n, part)
        slides = [(f"{1:02d}_cover.jpg", jpg(cover), "cover")]
        for k, d in enumerate(posts, 2):
            slides.append((f"{k:02d}.jpg", M.tg_download(d["tg_file_id"]), trim(d["headline"], 60)))
        video, seconds = make_part_video(day, n, part, posts, cover)
        parts_out.append({"n": n, "name": part["name"], "part": part, "posts": posts, "cover": cover,
                          "slides": slides, "video": video, "seconds": seconds})

    times = post_times(day, test)
    for p, at in zip(parts_out, times):
        p["texts"] = part_texts(day, p["n"], p["part"], p["posts"], at)
        p["at"] = at

    # uploads (not in a test)
    results = []
    for p in parts_out:
        r = {"name": p["name"], "post_at": p["at"].isoformat(), "stories": len(p["posts"]),
             "seconds": round(p["seconds"], 1)}
        cover_tall = jpg(tall(p["cover"]), 88)
        if test:
            r["fb"] = r["yt"] = {"state": "test"}
        else:
            if ROUNDUP_FACEBOOK:
                try:
                    r["fb"] = facebook_upload(p["video"], cover_tall, p["texts"], p["at"])
                except Exception as e:
                    log("Facebook roundup failed:", e)
                    r["fb"] = {"state": "error", "error": str(e)[:300]}
            else:
                r["fb"] = {"state": "off"}
            if ROUNDUP_YOUTUBE and YT_REFRESH_TOKEN:
                try:
                    r["yt"] = youtube_upload(p["video"], cover_tall, p["texts"], p["at"])
                except Exception as e:
                    log("YouTube roundup failed:", e)
                    r["yt"] = {"state": "error", "error": str(e)[:300]}
            else:
                r["yt"] = {"state": "off" if not ROUNDUP_YOUTUBE else "no secrets"}
        results.append(r)

    # Telegram: TikTok slides per part, then the backup package (videos + covers + texts)
    tt_ok = []
    for p in parts_out:
        if not ROUNDUP_TIKTOK:
            tt_ok.append("off")
            continue
        try:
            send_tiktok(ch, p["n"], p["part"], p["texts"], p["slides"], p["at"], day)
            tt_ok.append("sent")
        except Exception as e:
            log("TikTok slides failed:", e)
            tt_ok.append("error: " + str(e)[:100])
    for p in parts_out:
        M.tg("sendDocument", chat_id=ch, caption=f"🎬 Part {p['n']}/3 · {p['name']} · video ({p['seconds']:.0f} s) "
                                                  f"for YouTube / Facebook / TikTok",
             files={"document": (f"7seas_{day:%Y-%m-%d}_part{p['n']}.mp4", p["video"], "video/mp4")})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("DESCRIPTIONS-AND-TIMES.txt", descriptions_txt(day, parts_out))
        for p in parts_out:
            z.writestr(f"part{p['n']}_cover_9x16.jpg", jpg(tall(p["cover"])))
            z.writestr(f"part{p['n']}_cover_4x5.jpg", jpg(p["cover"]))
    M.tg("sendDocument", chat_id=ch, caption="📦 Backup: covers + DESCRIPTIONS-AND-TIMES.txt (titles, captions, tags, times)",
         files={"document": (f"7seas_roundup_{day:%Y-%m-%d}.zip", buf.getvalue(), "application/zip")})

    # report
    icon = {"scheduled": "✅ scheduled", "draft": "🕒 saved, the bot publishes it at the time", "off": "off",
            "test": "— (test)", "no secrets": "not set up yet"}
    rows = [("🧪 <b>TEST roundup</b> — nothing uploaded" if test else "🎬 <b>Roundup ready</b>")
            + f" · {day:%A, %b} {day.day}"]
    for p, r, tt in zip(parts_out, results, tt_ok):
        def show(x):
            return icon.get(x.get("state"), "") or ("❌ " + esc(x.get("error", x.get("state", "?")))[:150])
        rows.append(f"\n<b>Part {p['n']}/3 · {esc(p['name'])}</b> · {len(p['posts'])} stories · {p['seconds']:.0f} s · "
                    f"{when(p['at'])}\nFacebook: {show(r['fb'])}\nYouTube: {show(r['yt'])}"
                    + (f" <a href=\"{r['yt']['url']}\">link</a>" if r["yt"].get("url") else "")
                    + f"\nTikTok slides: {'✅ sent to ' + ('your content channel' if ch != M.TG_CHAT else 'this chat') if tt == 'sent' else esc(tt)}")
    if any(r["fb"].get("state") == "error" or r["yt"].get("state") == "error" for r in results):
        rows.append("\n⚠️ Something failed (after one retry). The videos + texts are in the content channel — "
                    "you can post them by hand.")
    M.tg_text("\n".join(rows))
    save_result(day_s, {"built_at": M.now_utc().isoformat(), "test": test, "parts": results})


def yt_test():
    """One-time YouTube check: upload a 3 s PRIVATE video scheduled 7 days ahead, read back what YouTube did with
    it (scheduled? locked private?), report it, then delete the test video."""
    from datetime import date
    if not (YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN):
        raise RuntimeError("the YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN secrets are missing")
    cover = tall(make_cover(date.today(), 1, {"name": "TEST", "hook": "YouTube connection test. Deleted right away."}))
    with tempfile.TemporaryDirectory() as tmp:
        img, out = os.path.join(tmp, "c.jpg"), os.path.join(tmp, "t.mp4")
        cover.save(img, "JPEG", quality=90)
        subprocess.run([M.ffmpeg_exe(), "-y", "-loglevel", "error", "-loop", "1", "-i", img, "-f", "lavfi", "-i",
                        "anullsrc=r=48000:cl=stereo", "-t", "3", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", out], check=True)
        video = open(out, "rb").read()
    at = (M.now_utc() + timedelta(days=7)).replace(minute=0, second=0, microsecond=0)
    texts = {"yt_title": "7 Seas News connection test (private, will be deleted)", "yt_description": "Test upload.",
             "yt_tags": ["test"]}
    up = youtube_upload(video, jpg(cover, 85), texts, at)
    tok = yt_token()
    j = M.HTTP.get("https://www.googleapis.com/youtube/v3/videos", timeout=30, params={"part": "status", "id": up["id"]},
                   headers={"Authorization": f"Bearer {tok}"}).json()
    st = ((j.get("items") or [{}])[0]).get("status", {})
    d = M.HTTP.delete("https://www.googleapis.com/youtube/v3/videos", params={"id": up["id"]}, timeout=30,
                      headers={"Authorization": f"Bearer {tok}"})
    deleted = d.status_code in (200, 204)
    scheduled = bool(st.get("publishAt"))
    M.tg_text("🧪 <b>YouTube connection test</b>\n"
              f"Upload: ✅ worked (login OK)\n"
              f"Scheduling: {'✅ kept — Shorts will go public at their times' if scheduled else '⚠️ YouTube removed the schedule (new apps are locked private until Google reviews them) — the bot will still upload, you publish in YouTube Studio'}\n"
              f"Privacy: {esc(st.get('privacyStatus', '?'))} · upload: {esc(st.get('uploadStatus', '?'))}\n"
              f"Test video deleted: {'✅' if deleted else '❌ please delete it in YouTube Studio'}")
    save_result("yttest", {"built_at": M.now_utc().isoformat(), "status": st, "scheduled": scheduled,
                           "deleted": deleted, "parts": []})


def cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True)
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    try:
        if a.day == "yttest":
            return yt_test()
        run(a.day[:10], a.test)
    except Exception as e:
        traceback.print_exc()
        M.tg_text(f"⚠️ Roundup videos for {a.day} failed: <code>{M.html.escape(str(e))[:500]}</code>")
        save_result(a.day[:10], {"built_at": M.now_utc().isoformat(), "error": str(e)[:300], "parts": []})
        sys.exit(1)


if __name__ == "__main__":
    cli()
