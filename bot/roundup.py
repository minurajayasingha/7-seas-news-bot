"""7 Seas News — daily roundup videos (Stage 3 + 4 of docs/AUTOMATION_PLAN.md).

Run by .github/workflows/roundup.yml after you approve the plan in Telegram (or after 3 hours by itself):
    python bot/roundup.py --day 2026-11-16 [--test]

1. reads the approved plan + the day's posts from state/state.json (read only: the normal bot owns that file)
2. per part: the TikTok slides (1080x1350 cover + each post), the 1080x1920 video and its cover
3. uploads (bot/uploads.py, not in --test): Facebook Reel + YouTube Short (scheduled), TikTok draft in your inbox
4. content channel: ONE zip with everything (+ a part's slides/texts only when it must go on TikTok by hand)
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
import uploads as U                                # noqa: E402  (Facebook · YouTube · TikTok uploads)
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
                    events.append(((len(plan) + (c - before) / max(1, shown - before)) / FR,
                                   "space" if text[c].isspace() else "key"))
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
        M.roundup_audio(events, seconds, wav)           # the bot's own Reel sounds
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
# TELEGRAM: TikTok slides + backup package
# =============================================================================

def esc(t):
    return M.html.escape(str(t))


def when(post_at):
    return M.both_times(post_at)                   # "6:25 PM SL · 7:55 AM NY"


def send_tiktok(ch, n, part, texts, slides, post_at, why=""):
    """For posting a part on TikTok BY HAND (no inbox draft): text with time + title + caption to copy, then the
    numbered slides as photo albums (the full-quality slides are in the one zip)."""
    M.tg("sendMessage", chat_id=ch, parse_mode="HTML", disable_web_page_preview="true", text=(
        f"📲 <b>TikTok Part {n}/{part.get('of', 3)}</b> · {esc(part['name'])}"
        + (f"\n{'' if why.startswith('🧪') else '⚠️ '}{esc(why)}" if why else "") + "\n"
        f"🕒 Post at <b>{when(post_at)}</b> · {M.ny_date_text(post_at)} (New York date for TikTok Studio)\n\n"
        f"<b>Title</b> (tap to copy):\n<code>{esc(texts['tiktok_title'])}</code>\n\n"
        f"<b>Caption</b> (tap to copy):\n<code>{esc(texts['tiktok_caption'])}</code>\n\n"
        "📱 Open the album below → ⋮ → <b>Save to gallery</b> → TikTok ＋ → Photos → tap 1, 2, 3… in order."))
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


def backup_zip(day, parts_out):
    """ONE zip with everything, same layout as the /day pack:
        7seas_2026-11-20_Friday_roundup.zip
          2026-11-20 Friday - Roundup/
            TEXTS-AND-TIMES.txt                      every title/caption/description + times, all platforms
            Part 1 - WAR & CONFLICT/
              CAPTION.txt                            TikTok title + caption + time
              7seas_2026-11-20_part1_01_cover.jpg    the slides in order (cover first)
              7seas_2026-11-20_part1_02.jpg …
              7seas_2026-11-20_part1_cover_9x16.jpg  the video cover (thumbnail)
    Too big for Telegram (> 48 MB) → only covers + texts. Returns (file name, bytes, full?)."""
    root = f"{day:%Y-%m-%d} {day:%A} - Roundup"

    def build(with_slides):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{root}/TEXTS-AND-TIMES.txt", descriptions_txt(day, parts_out))
            for p in parts_out:
                folder = f"{root}/Part {p['n']} - {p['name']}".replace("&", "and")
                t = p["texts"]
                z.writestr(f"{folder}/CAPTION.txt", "\n".join([
                    f"TIKTOK PART {p['n']}/{p['part'].get('of', 3)} · {p['name']}",
                    f"Post at: {when(p['at'])} · {M.ny_date_text(p['at'])} (New York date)", "",
                    "TITLE:", t["tiktok_title"], "", "CAPTION:", t["tiktok_caption"], ""]))
                z.writestr(f"{folder}/{M.file_name(day, 'part' + str(p['n']), 'cover_9x16')}", p["cover_tall"])
                for name, data, _ in (p["slides"] if with_slides else p["slides"][:1]):
                    z.writestr(f"{folder}/{name}", data)
        return buf.getvalue()
    data, full = build(True), True
    if len(data) > 48 * 1024 * 1024:               # Telegram bots can send files up to 50 MB
        data, full = build(False), False
    return f"7seas_{day:%Y-%m-%d}_{day:%A}_roundup.zip", data, full


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
        slides = [(M.file_name(day, f"part{n}", "01_cover"), jpg(cover), "cover")]
        for k, d in enumerate(posts, 2):
            slides.append((M.file_name(day, f"part{n}", f"{k:02d}"), M.tg_download(d["tg_file_id"]),
                           trim(d["headline"], 60)))
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

    # 1) uploads — every platform the same way (bot/uploads.py); nothing is uploaded in a test
    for p in parts_out:
        p["cover_tall"] = jpg(RD.cover_9x16(p["cover"]), 88)
    if not test:
        U.tiktok_prepare(day_s, parts_out)            # photos: all slides online in ONE push first
    results = []
    for p in parts_out:
        r = {"name": p["name"], "of": len(parts_out), "post_at": p["at"].isoformat(), "stories": len(p["posts"]),
             "seconds": round(p["seconds"], 1)}
        for key, platform, ready, upload in U.PLATFORMS:
            why = "test" if test else ready()
            if why:
                r[key] = {"state": why}
                continue
            try:
                r[key] = upload(p)
            except Exception as e:
                log(f"{platform} roundup failed:", e)
                r[key] = {"state": "error", "error": str(e)[:300]}
        results.append(r)

    # 2) content channel: a part's slides + texts ONLY when you must post it on TikTok by hand
    #    (no inbox draft, or a test); then always ONE zip with everything
    for p, r in zip(parts_out, results):
        tt = r["tt"]
        if tt["state"] in ("inbox", "off"):
            continue
        why = {"test": "🧪 TEST — nothing was uploaded", "manual": "", "no secrets": "TikTok is not set up (TT_… secrets)"}.get(
            tt["state"], "TikTok draft failed: " + str(tt.get("error", tt["state"]))[:200])
        try:
            send_tiktok(ch, p["n"], p["part"], p["texts"], p["slides"], p["at"], why)
            tt["slides"] = "sent"
        except Exception as e:
            log("TikTok slides to Telegram failed:", e)
            tt["slides"] = "error: " + str(e)[:100]
    zip_name, zip_data, full = backup_zip(day, parts_out)
    M.tg("sendDocument", chat_id=ch, parse_mode="HTML",
         caption=(f"📦 <b>Roundup · {day:%A, %b} {day.day}</b> · everything in one zip: a folder per part "
                  "(slides in order, 9:16 cover, CAPTION.txt) + TEXTS-AND-TIMES.txt"
                  + ("" if full else "\n⚠️ Too big for Telegram: only covers + texts (no slides)")),
         files={"document": (zip_name, zip_data, "application/zip")})

    # 3) YouTube thumbnails last: the Shorts need time to process, and everything above is already safely sent
    yt_waiting = [(r["yt"], p["cover_tall"]) for p, r in zip(parts_out, results) if r["yt"].get("id")]
    if yt_waiting:
        U.youtube_thumbnails(yt_waiting)

    # 4) thumbnails the bot could not set → ONE note per part in the bot chat: the cover + where to set it
    if not test:
        for p, r in zip(parts_out, results):
            todo = []
            yt, fb = r.get("yt") or {}, r.get("fb") or {}
            if yt.get("id") and yt.get("thumb", "set") != "set":
                hint = (" → verify the channel once at youtube.com/verify (custom thumbnails need it)"
                        if "permission" in yt["thumb"].lower() or "forbidden" in yt["thumb"].lower() else "")
                todo.append(f'▶️ <a href="https://studio.youtube.com/video/{yt["id"]}/edit">YouTube Studio</a> → '
                            f"Thumbnail → Upload file\n<i>Why: {esc(yt['thumb'])}{hint}</i>")
            if fb.get("id") and fb.get("thumb", "set") != "set":
                todo.append(f'📘 <a href="https://business.facebook.com/latest/content_calendar">Meta Business Suite</a>'
                            f" → Planner → this Reel → Edit → Cover → Upload\n<i>Why: {esc(fb['thumb'])}</i>")
            if todo:
                M.tg("sendDocument", chat_id=M.TG_CHAT, parse_mode="HTML",
                     caption=(f"🖼 <b>Set the thumbnail by hand</b> · Part {p['n']}/{p['part'].get('of', 3)} · "
                              f"{esc(p['name'])} · goes live {when(p['at'])}\n\n" + "\n\n".join(todo))[:1024],
                     files={"document": (M.file_name(day, f"part{p['n']}", "cover_9x16"), p["cover_tall"],
                                         "image/jpeg")})

    # 5) a video goes to the bot chat only when you must post it by hand (Facebook + YouTube both failed/off) or in a test
    for p, r in zip(parts_out, results):
        states = [r["fb"].get("state"), r["yt"].get("state")]
        uploaded = any(x in ("scheduled", "draft") for x in states)
        if test or "error" in states or not uploaded:
            why = "test" if test else "upload failed — post it by hand" if "error" in states else "not uploaded anywhere"
            M.tg("sendDocument", chat_id=M.TG_CHAT,
                 caption=f"🎬 Part {p['n']}/{p['part'].get('of', 3)} · {p['name']} · {p['seconds']:.0f} s · {when(p['at'])} ({why})",
                 files={"document": (M.file_name(day, f"part{p['n']}", ext="mp4"), p["video"], "video/mp4")})

    # 6) report: only in a test (a real roundup is in the normal bot's ONE daily report, same words)
    if test:
        rows = [f"🧪 <b>TEST roundup</b> — nothing uploaded · {day:%A, %b} {day.day}"]
        for p, r in zip(parts_out, results):
            rows.append(f"\n<b>Part {p['n']}/{p['part'].get('of', 3)} · {esc(p['name'])}</b> · {len(p['posts'])} stories · "
                        f"{p['seconds']:.0f} s · {when(p['at'])}\n"
                        + "\n".join(f"{platform}: {M.platform_text(r[key])}" for key, platform, _, _ in U.PLATFORMS))
        M.tg_text("\n".join(rows))
    save_result(day_s, {"built_at": M.now_utc().isoformat(), "test": test, "parts": results})


def test_video(label):
    """A 3-second video of a TEST cover (for the connection tests)."""
    from datetime import date
    cover = RD.cover_9x16(make_cover(date.today(), 1, {"name": "TEST", "hook": label}))
    with tempfile.TemporaryDirectory() as tmp:
        img, out = os.path.join(tmp, "c.jpg"), os.path.join(tmp, "t.mp4")
        cover.save(img, "JPEG", quality=90)
        subprocess.run([M.ffmpeg_exe(), "-y", "-loglevel", "error", "-loop", "1", "-i", img, "-f", "lavfi", "-i",
                        "anullsrc=r=48000:cl=stereo", "-t", "3", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", out], check=True)
        return open(out, "rb").read()


def tt_verify():
    """Put the signature file(s) from tiktok_verify/ online, so you can click "Verify" in the TikTok app."""
    names = [x for x in os.listdir(U.TT_VERIFY_DIR) if not x.startswith(".") and x.lower() != "readme.md"] \
        if os.path.isdir(U.TT_VERIFY_DIR) else []
    if not names:
        raise RuntimeError("put the signature file from TikTok in the folder tiktok_verify/ first (then commit)")
    prefix = U.tt_push_photos({})
    ok = U.tt_wait_online(prefix + names[0])
    M.tg_text("🔐 <b>TikTok verify file</b> " + ("✅ online" if ok else "⚠️ not online yet (try Verify in a few min)")
              + f"\nIn the TikTok app → URL properties → Verify, use this URL prefix:\n<code>{esc(prefix)}</code>\n"
              f"File: {esc(prefix + names[0])}")


def tt_test():
    """One-time TikTok check: log in, send TEST slides (photos mode) or a 3 s video to the TikTok inbox, report."""
    from datetime import date
    if not U.tt_configured():
        raise RuntimeError("the TT_CLIENT_KEY / TT_CLIENT_SECRET / TT_REFRESH_TOKEN secrets are missing")
    if M.tiktok_mode() != "video":
        slides = [(f"{k}.jpg", jpg(make_cover(date.today(), k, {"name": "TEST", "hook": f"TikTok test {k}/2. Delete it."})), "t")
                  for k in (1, 2)]
        files, paths = U.tt_slide_files("test", [(1, slides)])
        prefix = U.tt_push_photos(files)
        if not U.tt_wait_online(prefix + paths[1][0][0]):
            raise RuntimeError("the test slides did not come online at " + prefix)
        up = U.tiktok_inbox_photos(prefix, *paths[1], {"tiktok_title": "7 Seas News test", "tiktok_caption": "Test. Delete me."})
    else:
        up = U.tiktok_inbox_upload(test_video("TikTok test. Delete it."))
    _, saved = U.tt_saved_token()
    exp = (saved.get("refresh_expires_at") or "")[:10]
    M.tg_text("🧪 <b>TikTok connection test</b>\nLogin: ✅ worked (new token saved, encrypted)\n"
              f"Upload to inbox: ✅ {esc(up.get('kind', ''))} · {esc(up.get('tt_status', ''))}"
              + (f" · {esc(up.get('size', ''))}" if up.get("size") else "") + "\n"
              "📱 Open TikTok → 🔔 Inbox: a TEST draft should be waiting. Just delete it (don't post it)."
              + (f"\nLogin valid until about {exp} (renewed each day the bot uses it)." if exp else ""))


def yt_test():
    """One-time YouTube check: upload a 3 s PRIVATE video scheduled 7 days ahead, read back what YouTube did with
    it (scheduled? locked private?), report it, then delete the test video."""
    from datetime import date
    if not (U.YT_CLIENT_ID and U.YT_CLIENT_SECRET and U.YT_REFRESH_TOKEN):
        raise RuntimeError("the U.YT_CLIENT_ID / U.YT_CLIENT_SECRET / U.YT_REFRESH_TOKEN secrets are missing")
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
    up = U.youtube_upload(video, texts, at)
    tok = U.yt_token()
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
        if a.day == "tttest":
            return tt_test()
        if a.day == "ttverify":
            return tt_verify()
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
