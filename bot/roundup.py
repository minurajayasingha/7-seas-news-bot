"""7 Seas News — daily roundup videos (Stage 3 + 4 of docs/AUTOMATION_PLAN.md).

Run by .github/workflows/roundup.yml after you approve the plan in Telegram (or after 3 hours by itself):
    python bot/roundup.py --day 2026-11-16 [--test]

1. reads the approved plan + the day's posts from state/state.json (read only: the normal bot owns that file)
2. per part: the TikTok slides (1080x1350 cover + each post), the 1080x1920 video and its cover
3. uploads: Facebook Reel (scheduled), YouTube Short (scheduled) — not in --test
4. content channel: per part the TikTok text + numbered slides, then ONE backup zip (texts, covers, full slides)
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
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main as M                                   # noqa: E402  (all the bot's tools: images, Telegram, Facebook)
from main import Image                             # noqa: E402
from settings import *                             # noqa: E402,F401,F403
import roundup_design as RD                        # noqa: E402  (THE design: covers, frames, swipes, sounds, timing)
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


def part_tag(part):
    """The part's fixed hashtag (#warnews / #usnews / #worldnews), also for plans made before it was stored."""
    if part.get("tag"):
        return part["tag"]
    names = list(ROUNDUP_PART_NAMES)
    return ROUNDUP_PART_HASHTAGS[names.index(part["name"])] if part.get("name") in names else "#news"


def part_texts(day, n, part, posts, post_at):
    """All words for one part: TikTok title/caption, YouTube title/description/tags, Facebook caption.
    The fixed part name (WAR & CONFLICT / US NEWS / WORLD NEWS) is in every title, its hashtag in every caption."""
    weekday, mon = f"{day:%A}", f"{day:%b} {day.day}"
    of, name = part.get("of", 3), part["name"]
    title = part.get("title") or posts[0]["headline"]
    hook = part.get("hook") or ""
    q = part.get("question") or ""
    fixed = part_tag(part)
    tags_tt = lower_tags([fixed] + part.get("hashtags", []) + ["#7seasnews", "#newstok", "#news"])[:7]
    tags_fb = lower_tags([fixed] + part.get("hashtags", [])[:1] + ["#7seasnews", "#news"])[:5]
    tags_yt = lower_tags([fixed] + part.get("hashtags", []) + ["#7seasnews", "#news", "#shorts"])[:6]

    end = f" · {weekday}'s top stories (Part {n}/{of})"
    tiktok_title = f"{name}: " + trim(title, 90 - len(end) - len(name) - 2) + end
    tiktok_caption = "\n".join(x for x in [hook, "", f"{name} · Part {n}/{of} · {weekday}, {mon}",
                                           "Follow 7 Seas News for more 🔔", "", q, "", " ".join(tags_tt)])
    tiktok_caption = re.sub(r"\n{3,}", "\n\n", tiktok_caption)
    yt_end = f" | {weekday}'s Top Stories, {mon} (Part {n}/{of}) #shorts"
    yt_title = f"{name}: " + trim(title, 100 - len(yt_end) - len(name) - 2) + yt_end
    yt_desc = "\n".join([hook, "", f"{weekday}'s top stories, {mon}, {day.year} — Part {n}/{of} · {name}", ""]
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
    fb_caption = "\n\n".join(x for x in [hook, f"{name} · {weekday}'s top stories · Part {n}/{of}", FOLLOW_LINE,
                                         " ".join(tags_fb)] if x)
    return {"tiktok_title": tiktok_title, "tiktok_caption": tiktok_caption.strip(), "yt_title": yt_title,
            "yt_description": yt_desc[:4900], "yt_tags": yt_tags, "fb_caption": fb_caption,
            "post_at": post_at.isoformat()}


# =============================================================================
# PICTURES: cover, story frames
# =============================================================================

# =============================================================================
# DRAWING — every look/size/timing number lives in roundup_design.py (docs/ROUNDUP_DESIGN.md). Nothing here.
# =============================================================================

def use_design_fonts():
    for name in ("Poppins-Bold.ttf", "Poppins-SemiBold.ttf", "Poppins-Medium.ttf"):
        M.font(name, 10)                              # downloads the bot's Poppins files if missing
    RD.set_font_dir(M.FONT_DIR)


def make_cover(day, n, part):
    """TikTok cover 1080x1350. day = the NEWS day (New York date)."""
    return RD.make_cover(day, n, part.get("of", 3), part["name"], M.roundup_safe_hook(part.get("hook") or ""),
                         M.LOGO_FILE)


def jpg(img, q=92):
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=q, optimize=True)
    return out.getvalue()


def story_base(d, day, k, total):
    """(1080x1920 frame without headline + counter, layout). layout None = the headline is already in the picture
    (the photo would not download: the published image is used as it is)."""
    label = "BREAKING NEWS" if d.get("breaking") else d.get("label", "WORLD")
    lay, bg = {}, copy.deepcopy(d.get("bg") or {"type": "brand", "photos": []})
    clean = Image.open(io.BytesIO(M.render_image(d["headline"], label, d.get("sources", []), bg,
                                                 hide_headline=True, layout=lay, date=day))).convert("RGB")
    if bg.get("photos") and not bg.get("_loaded"):
        clean = Image.open(io.BytesIO(M.tg_download(d["tg_file_id"]))).convert("RGB").resize((RD.W, RD.POST_H))
        lay = None
    return RD.draw_counter(RD.story_canvas(clean), k, total), lay


MAX_SECONDS = 88                                   # Facebook Reels: max 90 s (safety only)


def make_part_video(day, n, part, posts, cover_4x5):
    """MP4 bytes of one part (1080x1920, 30 fps, H.264 + AAC) — exactly roundup_design.py."""
    t0 = time.time()
    T, FR, NW = RD.TIMING, RD.FPS, RD.TIMING["wipe_frames"]
    bases = [story_base(d, day, k, len(posts)) for k, d in enumerate(posts, 1)]
    cover_t = RD.cover_9x16(cover_4x5)
    end = RD.end_frame(M.LOGO_FILE)
    hfonts = {}

    def hfont(size):
        if size not in hfonts:
            hfonts[size] = M.font("Poppins-Bold.ttf", size)
        return hfonts[size]

    def frame_at(i, nchars, cursor):
        base, lay = bases[i]
        if not lay:
            return base
        return RD.typing_frame(base, lay["lines"], hfont(lay["size"]), lay["size"], lay["y"] + RD.OY,
                               lay["line_h"], nchars, cursor)

    type_n = [RD.typing_frame_count(lay["lines"]) if lay else 0 for _, lay in bases]
    hold_n = int(T["hold_s"] * FR)
    fixed = int(T["cover_hold_s"] * FR) + 2 * NW * (len(posts) + 1) + int(T["end_hold_s"] * FR) + sum(type_n)
    if (fixed + hold_n * len(posts)) / FR > MAX_SECONDS:
        hold_n = max(FR, int((MAX_SECONDS * FR - fixed) / len(posts)))

    # the timeline as a list of frame makers; events for the sound
    plan, events = [], [(0.0, "boom")]

    def wipe_out(still):
        events.append((len(plan) / FR, "whoosh"))
        for k in range(1, NW + 1):
            plan.append(lambda k=k, s=still: RD.wipe(s(), k, "out"))

    def wipe_in(still):
        for k in range(1, NW + 1):
            plan.append(lambda k=k, s=still: RD.wipe(s(), k, "in"))

    plan += [lambda: cover_t] * int(T["cover_hold_s"] * FR)
    prev = lambda: cover_t
    for i, (base, lay) in enumerate(bases):
        wipe_out(prev)
        wipe_in(lambda i=i: frame_at(i, 0, True))
        if lay:
            text = "".join(lay["lines"])
            total_c, tn = len(text), type_n[i]
            for f in range(tn):
                shown = min(total_c, int((f + 1) / tn * total_c))
                before = min(total_c, int(f / tn * total_c))
                for c in range(before, shown):
                    if not text[c].isspace():
                        events.append(((len(plan) + (c - before) / max(1, shown - before)) / FR, "key"))
                plan.append(lambda i=i, s=shown: frame_at(i, s, True))
            full = total_c
        else:
            full = 0
        for f in range(hold_n):
            on = f < T["cursor_blink_until"] and (f // T["cursor_blink_frames"]) % 2 == 0
            plan.append(lambda i=i, on=on, full=full: frame_at(i, full, on))
        prev = lambda i=i, full=full: frame_at(i, full, False)
    wipe_out(prev)
    wipe_in(lambda: end)
    plan += [lambda: end] * int(T["end_hold_s"] * FR)
    seconds = len(plan) / FR

    ff = M.ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        wav, out = os.path.join(tmp, "sound.wav"), os.path.join(tmp, "part.mp4")
        RD.build_audio(events, seconds, wav)
        cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RD.W}x{RD.VID_H}",
               "-r", str(FR), "-i", "-", "-i", wav]
        mus = music_file()
        if mus:
            cmd += ["-stream_loop", "-1", "-i", mus, "-filter_complex",
                    "[2:a]volume=0.12[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]", "-map", "0:v", "-map", "[a]"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "3500k", "-bufsize", "7000k",
                "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000",
                "-t", f"{seconds:.2f}", "-movflags", "+faststart", out]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for make in plan:
                proc.stdin.write(make().convert("RGB").tobytes())
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
    return M.both_times(post_at)                   # "6:25 PM SL · 7:55 AM NY"


def send_tiktok(ch, n, part, texts, slides, post_at, day):
    """a) text with time + title + caption to copy  b) the numbered slides as photo albums
    (the full-quality slides are in the one backup zip)."""
    M.tg("sendMessage", chat_id=ch, parse_mode="HTML", disable_web_page_preview="true", text=(
        f"📲 <b>TikTok Part {n}/{part.get('of', 3)}</b> · {esc(part['name'])}\n"
        f"🕒 Post at <b>{when(post_at)}</b> · {M.ny_date_text(post_at)} (New York date for TikTok Studio)\n\n"
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


def descriptions_txt(day, parts_out):
    out = [f"7 SEAS NEWS — ROUNDUP OF {day:%A, %B} {day.day}, {day.year} (New York)", "=" * 60, ""]
    for n, p in enumerate(parts_out, 1):
        t, at = p["texts"], datetime.fromisoformat(p["texts"]["post_at"])
        out += [f"PART {n}/{p['part'].get('of', 3)} · {p['name']} · {len(p['posts'])} stories · {p['seconds']:.0f} s",
                f"Post at: {when(at)} · {M.ny_date_text(at)} (New York date)", "",
                "TIKTOK TITLE:", t["tiktok_title"], "", "TIKTOK CAPTION:", t["tiktok_caption"], "",
                "YOUTUBE TITLE:", t["yt_title"], "", "YOUTUBE DESCRIPTION:", t["yt_description"], "",
                "YOUTUBE TAGS:", ", ".join(t["yt_tags"]), "", "FACEBOOK CAPTION:", t["fb_caption"], "", "-" * 60, ""]
    return "\n".join(out)


# =============================================================================
# THE JOB
# =============================================================================

def post_times(day, test):
    """ROUNDUP_TIMES_NY (7:55 / 9:55 / 11:55 New York) the next morning; if we are late, all three move by the
    same amount."""
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
    if not test and day_s in ROUNDUP_HOLD_DAYS:
        M.tg_text(f"⏸ Roundup {day_s} is on hold (ROUNDUP_HOLD_DAYS) — nothing was uploaded.")
        return
    manual = ROUNDUP_MANUAL_TIMES.get(day_s)
    test = test or (bool(info.get("test")) and not manual)
    day = datetime.fromisoformat(day_s).date()
    plan = M.roundup_fit_hooks(copy.deepcopy(info["plan"]), info.get("heads"))
    drafts = state["drafts"]
    ch = state.get("tiktok_channel") or M.TG_CHAT
    parts_out = []
    for n, part in enumerate(plan["parts"], 1):
        posts = [drafts[plan["ids"][k - 1]] for k in part["stories"]
                 if k - 1 < len(plan["ids"]) and plan["ids"][k - 1] in drafts]
        if not posts:
            continue
        if manual and len(plan["parts"]) == 3:   # plans made before the fixed part names
            part = dict(part, name=ROUNDUP_PART_NAMES[n - 1], tag=ROUNDUP_PART_HASHTAGS[n - 1])
        part = dict(part, hook=M.roundup_safe_hook(part.get("hook") or ""))
        cover = make_cover(day, n, part)
        slides = [(f"{1:02d}_cover.jpg", jpg(cover), "cover")]
        for k, d in enumerate(posts, 2):
            slides.append((f"{k:02d}.jpg", M.tg_download(d["tg_file_id"]), trim(d["headline"], 60)))
        video, seconds = make_part_video(day, n, part, posts, cover)
        parts_out.append({"n": n, "name": part["name"], "part": part, "posts": posts, "cover": cover,
                          "slides": slides, "video": video, "seconds": seconds})

    times = post_times(day, test)
    if manual and not test:
        sl, earliest = ZoneInfo("Asia/Colombo"), M.now_utc() + timedelta(minutes=15)
        times = [max(datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=sl).astimezone(timezone.utc), earliest)
                 for t in manual]
    for p, at in zip(parts_out, times):
        p["texts"] = part_texts(day, p["n"], p["part"], p["posts"], at)
        p["at"] = at

    # uploads (not in a test)
    results = []
    for p in parts_out:
        r = {"name": p["name"], "of": len(parts_out), "post_at": p["at"].isoformat(), "stories": len(p["posts"]),
             "seconds": round(p["seconds"], 1)}
        cover_tall = jpg(RD.cover_9x16(p["cover"]), 88)
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

    # content channel: per part the TikTok text + numbered slides, then ONE backup zip
    tt_ok = []
    for p in parts_out:
        if not ROUNDUP_TIKTOK or manual:
            tt_ok.append("off")
            continue
        try:
            send_tiktok(ch, p["n"], p["part"], p["texts"], p["slides"], p["at"], day)
            tt_ok.append("sent")
        except Exception as e:
            log("TikTok slides failed:", e)
            tt_ok.append("error: " + str(e)[:100])
    for r, tt in zip(results, tt_ok):
        r["tt"] = {"state": "sent"} if tt == "sent" else ({"state": "off"} if tt == "off" else
                                                           {"state": "error", "error": tt[7:]})

    # ONE backup zip in the content channel: texts + covers + full-quality slides (no videos: they are uploaded)
    def backup_zip(with_slides):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("DESCRIPTIONS-AND-TIMES.txt", descriptions_txt(day, parts_out))
            for p in parts_out:
                z.writestr(f"part{p['n']}_cover_9x16.jpg", jpg(RD.cover_9x16(p["cover"])))
                z.writestr(f"part{p['n']}_cover_4x5.jpg", jpg(p["cover"]))
                for name, data, _ in (p["slides"] if with_slides else []):
                    z.writestr(f"part{p['n']}_slides/{name}", data)
        return buf.getvalue()
    data, full = backup_zip(True), True
    if len(data) > 48 * 1024 * 1024:               # Telegram bots can send files up to 50 MB
        data, full = backup_zip(False), False
    if not manual:                                 # a one-off manual day: you already have the slides
        M.tg("sendDocument", chat_id=ch, caption="📦 Backup: DESCRIPTIONS-AND-TIMES.txt (titles, captions, tags, "
                                                  "times), covers" + (" and full-quality TikTok slides" if full else ""),
             files={"document": (f"7seas_roundup_{day:%Y-%m-%d}.zip", data, "application/zip")})

    # a video goes to the bot chat only when you must post it by hand (an upload failed / nothing uploaded) or in a test
    for p, r in zip(parts_out, results):
        states = [r["fb"].get("state"), r["yt"].get("state")]
        uploaded = any(x in ("scheduled", "draft") for x in states)
        if test or "error" in states or not uploaded:
            why = "test" if test else "upload failed — post it by hand" if "error" in states else "not uploaded anywhere"
            M.tg("sendDocument", chat_id=M.TG_CHAT,
                 caption=f"🎬 Part {p['n']}/{p['part'].get('of', 3)} · {p['name']} · {p['seconds']:.0f} s · {when(p['at'])} ({why})",
                 files={"document": (f"7seas_{day:%Y-%m-%d}_part{p['n']}.mp4", p["video"], "video/mp4")})

    # report
    icon = {"scheduled": "✅ scheduled", "draft": "🕒 saved, the bot publishes it at the time", "off": "off",
            "test": "— (test)", "no secrets": "not set up yet"}
    rows = [("🧪 <b>TEST roundup</b> — nothing uploaded" if test else "🎬 <b>Roundup ready</b>")
            + f" · {day:%A, %b} {day.day}"]
    for p, r, tt in zip(parts_out, results, tt_ok):
        def show(x):
            return icon.get(x.get("state"), "") or ("❌ " + esc(x.get("error", x.get("state", "?")))[:150])
        rows.append(f"\n<b>Part {p['n']}/{p['part'].get('of', 3)} · {esc(p['name'])}</b> · {len(p['posts'])} stories · {p['seconds']:.0f} s · "
                    f"{when(p['at'])}\nFacebook: {show(r['fb'])}\nYouTube: {show(r['yt'])}"
                    + (f" <a href=\"{r['yt']['url']}\">link</a>" if r["yt"].get("url") else "")
                    + f"\nTikTok slides: {'✅ sent to ' + ('your content channel' if ch != M.TG_CHAT else 'this chat') if tt == 'sent' else esc(tt)}")
    if test:                       # a real roundup is reported by the normal bot in ONE daily report
        M.tg_text("\n".join(rows))
    save_result(day_s, {"built_at": M.now_utc().isoformat(), "test": test, "parts": results})


def yt_test():
    """One-time YouTube check: upload a 3 s PRIVATE video scheduled 7 days ahead, read back what YouTube did with
    it (scheduled? locked private?), report it, then delete the test video."""
    from datetime import date
    if not (YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN):
        raise RuntimeError("the YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN secrets are missing")
    cover = RD.cover_9x16(make_cover(date.today(), 1, {"name": "TEST", "hook": "YouTube test. Deleted soon."}))
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


def design_preview(day_s):
    """Dry run (nothing uploaded, nothing saved): for a day that has a plan → the 3 TikTok covers, the 3 video
    covers, one story frame mid-typing, the last frame and the full Part 1 video, all to the bot chat."""
    state = M.load_state()
    M.PHOTO_MEM = state.setdefault("photo_memory", {})
    plan = (state.get("roundup", {}).get(day_s) or {}).get("plan")
    if not plan:
        raise RuntimeError(f"no roundup plan for {day_s} in state.json")
    day = datetime.fromisoformat(day_s).date()
    plan = M.roundup_fit_hooks(copy.deepcopy(plan), (state["roundup"][day_s]).get("heads"))
    ids, drafts = plan["ids"], state["drafts"]
    parts = []
    for n, part in enumerate(plan["parts"], 1):
        if len(plan["parts"]) == 3:                # plans made before the fixed part names
            part = dict(part, name=ROUNDUP_PART_NAMES[n - 1], tag=ROUNDUP_PART_HASHTAGS[n - 1])
        part = dict(part, hook=M.roundup_safe_hook(part.get("hook") or ""))
        posts = [drafts[ids[k - 1]] for k in part["stories"] if k - 1 < len(ids) and ids[k - 1] in drafts]
        parts.append((n, part, posts, make_cover(day, n, part)))
    M.tg_text(f"🎨 <b>Roundup design preview</b> · {day:%A, %b} {day.day} (New York) · nothing uploaded\n"
              "Compare with tests/golden/. Hooks used: " + " | ".join(esc(p["hook"]) for _, p, _, _ in parts))

    def album(items):
        M.tg("sendMediaGroup", chat_id=M.TG_CHAT,
             media=[{"type": "document", "media": f"attach://f{k}", "caption": cap} for k, (_, _, cap) in enumerate(items)],
             files={f"f{k}": (name, data, "image/png") for k, (name, data, _) in enumerate(items)})

    def png(img):
        out = io.BytesIO()
        img.convert("RGB").save(out, "PNG", optimize=True)
        return out.getvalue()
    album([(f"tiktok_cover_p{n}_1080x1350.png", png(c), f"TikTok cover Part {n} (1080x1350)") for n, _, _, c in parts])
    album([(f"video_cover_p{n}_1080x1920.png", png(RD.cover_9x16(c)), f"Video cover Part {n} (1080x1920)")
           for n, _, _, c in parts])
    n, part, posts, cover = parts[0]
    base, lay = story_base(posts[0], day, 1, len(posts))
    if lay:
        half = sum(len(x) for x in lay["lines"]) // 2
        typing = RD.typing_frame(base, lay["lines"], M.font("Poppins-Bold.ttf", lay["size"]), lay["size"],
                                 lay["y"] + RD.OY, lay["line_h"], half, True)
    else:
        typing = base
    album([("story_typing_1080x1920.png", png(typing), "Story frame mid-typing (1080x1920)"),
           ("end_1080x1920.png", png(RD.end_frame(M.LOGO_FILE)), "Last frame (1080x1920)")])
    video, seconds = make_part_video(day, n, part, posts, cover)
    M.tg("sendVideo", chat_id=M.TG_CHAT, supports_streaming="true", width=RD.W, height=RD.VID_H,
         duration=int(seconds), caption=f"🎬 Part 1 video · {len(posts)} stories · {seconds:.0f} s (1080x1920)",
         files={"video": (f"7seas_{day_s}_part1.mp4", video, "video/mp4")})


def cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True)
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    try:
        use_design_fonts()
        if a.day == "yttest":
            return yt_test()
        if a.day.startswith(("check", "preview")):      # "preview" = yesterday (NY), or "preview 2026-11-16"
            day_s = a.day.split(" ", 1)[1].strip() if " " in a.day else str(M.ny_now().date() - timedelta(days=1))
            return design_preview(day_s[:10])
        run(a.day[:10], a.test)
    except Exception as e:
        traceback.print_exc()
        M.tg_text(f"⚠️ Roundup videos for {a.day} failed: <code>{M.html.escape(str(e))[:500]}</code>")
        if a.day.startswith(("check", "preview")):
            sys.exit(1)
        save_result(a.day[:10], {"built_at": M.now_utc().isoformat(), "error": str(e)[:300], "parts": []})
        sys.exit(1)


if __name__ == "__main__":
    cli()
