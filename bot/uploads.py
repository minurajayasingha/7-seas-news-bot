"""7 Seas News — uploads of the daily roundup parts. One section per platform, all with the same shape:

    <platform>_ready()       → "" when it can upload, else why not: "off" (settings) or "no secrets"
    <platform>_upload(p)     → result dict {"state": …} (raises on failure; roundup.py turns that into "error")

p = one part from roundup.run(): {"n", "name", "part", "texts", "at", "video", "cover_tall", "slides", …}.
Result states are the same words for every platform (main.PLATFORM_TEXT shows them in Telegram):
    scheduled · draft · inbox · published · off · no secrets · test · error
Results are saved per part in state/roundup.json as "fb", "yt", "tt".
"""
import io
import json
import os
import random
import re
import subprocess
import tempfile
import time
from datetime import timedelta
import base64
import hashlib
import hmac

import main as M                                   # the bot's tools: HTTP, Facebook Reel helpers, Telegram
from main import Image
from settings import *                             # noqa: F401,F403

YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "").strip()
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN", "").strip()
TT_CLIENT_KEY = os.environ.get("TT_CLIENT_KEY", "").strip()
TT_CLIENT_SECRET = os.environ.get("TT_CLIENT_SECRET", "").strip()
TT_REFRESH_TOKEN = os.environ.get("TT_REFRESH_TOKEN", "").strip()
TT_TOKEN_FILE = os.path.join(M.ROOT, "state", "tiktok_token.json")   # the newest TikTok login, ENCRYPTED (public repo)
log = M.log
JOB_START = time.time()
JOB_SAFE_MINUTES = 38                              # roundup.yml stops the job at 45 min: never wait past this


def _jpg(img, q=90):
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=q, optimize=True)
    return out.getvalue()

# =============================================================================
# SHARED
# =============================================================================

def retry_once(what, fn):
    try:
        return fn()
    except Exception as e:
        log(f"{what} failed, trying once more:", e)
        time.sleep(20)
        return fn()


# =============================================================================
# FACEBOOK — Reel, scheduled at the part's time (refused → draft, main.py publishes it at the time)
# =============================================================================

def facebook_ready():
    return "" if ROUNDUP_FACEBOOK else "off"


def facebook_upload(video, cover_jpg, texts, post_at):
    """Reel scheduled for post_at. If Facebook refuses to schedule Reels: saved as a draft, and the normal bot
    publishes it at the time."""
    vid = retry_once("Facebook upload", lambda: M.fb_reel_upload(video))
    thumb = M.fb_reel_cover(vid, cover_jpg)          # before scheduling: Facebook takes it best then
    try:
        retry_once("Facebook schedule", lambda: M.fb_reel_finish(vid, texts["fb_caption"], "SCHEDULED", post_at))
        st = "scheduled"
    except Exception as e:
        log("Facebook won't schedule the Reel, saving it as a draft:", e)
        M.fb_reel_finish(vid, texts["fb_caption"], "DRAFT")
        st = "draft"
    if thumb != "set":
        thumb = M.fb_reel_cover(vid, cover_jpg)
    return {"id": vid, "state": st, "caption": texts["fb_caption"], "thumb": thumb}


# =============================================================================
# YOUTUBE — Short, private + publishAt (= scheduled); thumbnails once processing is done
# =============================================================================

def youtube_ready():
    return "off" if not ROUNDUP_YOUTUBE else "" if YT_REFRESH_TOKEN else "no secrets"


def yt_token():
    r = M.HTTP.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": YT_CLIENT_ID, "client_secret": YT_CLIENT_SECRET, "refresh_token": YT_REFRESH_TOKEN,
        "grant_type": "refresh_token"})
    j = r.json()
    if "access_token" not in j:
        raise RuntimeError("YouTube login: " + str(j.get("error_description") or j.get("error") or j)[:200])
    return j["access_token"]


def youtube_upload(video, texts, post_at):
    """YouTube Data API v3: resumable upload as private + publishAt (= scheduled).
    The thumbnail comes later (youtube_thumbnails): YouTube ignores it on a Short that is still processing."""
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
    return {"id": vid, "state": "scheduled" if status.get("publishAt") else status.get("privacyStatus", "uploaded"),
            "url": f"https://youtube.com/shorts/{vid}", "thumb": "not set yet"}


def youtube_set_thumbnail(tok, vid, thumb_jpg):
    """Send one thumbnail (one retry). Returns "set" or the reason it failed (never raises)."""
    thumb = "not sent"
    for attempt in range(2):
        if attempt:
            time.sleep(20)
        try:
            t = M.HTTP.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                            data=thumb_jpg, timeout=60,
                            headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"})
            if t.status_code < 300:
                return "set"
            try:
                thumb = str(t.json()["error"]["message"])[:200]
            except Exception:
                thumb = f"HTTP {t.status_code}: {t.text[:150]}"
        except Exception as e:
            thumb = str(e)[:200]
    return thumb


def youtube_thumbnails(waiting):
    """waiting = [(the part's result["yt"], cover jpg)]. Waits until YouTube has finished processing each Short, then
    sets its thumbnail. Anything not set keeps a reason in yt["thumb"], so the bot chat gets the by-hand reminder."""
    todo = {yt["id"]: (yt, cover) for yt, cover in waiting if yt.get("id")}
    wait = ROUNDUP_YT_THUMB_WAIT_MINUTES * 60
    deadline = min(time.time() + wait, JOB_START + JOB_SAFE_MINUTES * 60)
    tok = None
    while todo:
        found = {}
        try:
            tok = tok or yt_token()
            r = M.HTTP.get("https://www.googleapis.com/youtube/v3/videos", timeout=30,
                           params={"part": "processingDetails", "id": ",".join(todo)},
                           headers={"Authorization": f"Bearer {tok}"})
            found = {i["id"]: (i.get("processingDetails") or {}).get("processingStatus")
                     for i in r.json().get("items", [])}
        except Exception as e:
            log("YouTube processing check failed:", e)
        for vid, status in found.items():
            if vid not in todo:
                continue
            if status == "succeeded":
                yt, cover = todo.pop(vid)
                yt["thumb"] = youtube_set_thumbnail(tok, vid, cover)
                log("YouTube thumbnail:", vid, yt["thumb"])
            elif status in ("failed", "terminated"):
                todo.pop(vid)[0]["thumb"] = f"YouTube could not process this video ({status})"
        if todo and time.time() >= deadline:
            for yt, _ in todo.values():
                yt["thumb"] = "YouTube was still processing this video when the bot stopped waiting"
            log("YouTube thumbnails: gave up waiting for", ", ".join(todo))
            return
        if todo:
            time.sleep(20)


# =============================================================================
# TIKTOK — a draft in your TikTok app's inbox (Content Posting API "upload"): the slides with title +
# caption ("photos") or the video ("video"). TikTok has no schedule: you post it at the reminder.
# =============================================================================
# TikTok gives a NEW refresh token every time the bot logs in (the old one stops working). The newest one is saved
# in state/tiktok_token.json, encrypted with a key made from TT_CLIENT_SECRET (only in GitHub secrets), so the
# public repo never shows it. TT_REFRESH_TOKEN (the secret) is only the starting point / fallback.
TT_API = "https://open.tiktokapis.com/v2"
_TT = {}           # this run's access token (refresh only ONCE per run: every refresh changes the refresh token)


def _tt_keys():
    root = hashlib.sha256(b"7seas-tiktok-token|" + TT_CLIENT_SECRET.encode()).digest()
    return hmac.new(root, b"enc", hashlib.sha256).digest(), hmac.new(root, b"mac", hashlib.sha256).digest()


def _tt_stream(key, nonce, n):
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def tt_encrypt(text):
    k_enc, k_mac = _tt_keys()
    nonce, raw = os.urandom(16), text.encode()
    ct = bytes(a ^ b for a, b in zip(raw, _tt_stream(k_enc, nonce, len(raw))))
    tag = hmac.new(k_mac, nonce + ct, hashlib.sha256).digest()[:16]
    return base64.b64encode(nonce + ct + tag).decode()


def tt_decrypt(blob):
    k_enc, k_mac = _tt_keys()
    b = base64.b64decode(blob)
    nonce, ct, tag = b[:16], b[16:-16], b[-16:]
    if not hmac.compare_digest(tag, hmac.new(k_mac, nonce + ct, hashlib.sha256).digest()[:16]):
        raise ValueError("saved TikTok token does not match TT_CLIENT_SECRET")
    return bytes(a ^ b for a, b in zip(ct, _tt_stream(k_enc, nonce, len(ct)))).decode()


def tt_saved_token():
    try:
        with open(TT_TOKEN_FILE, encoding="utf-8") as f:
            j = json.load(f)
        return tt_decrypt(j["data"]), j
    except FileNotFoundError:
        return "", {}
    except Exception as e:
        log("Saved TikTok token unreadable:", e)
        return "", {}


def tt_save_token(refresh, expires_in):
    exp = (M.now_utc() + timedelta(seconds=int(expires_in or 0))).isoformat() if expires_in else ""
    with open(TT_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump({"data": tt_encrypt(refresh), "saved_at": M.now_utc().isoformat(), "refresh_expires_at": exp}, f,
                  indent=1)


def tt_configured():
    return bool(TT_CLIENT_KEY and TT_CLIENT_SECRET and (TT_REFRESH_TOKEN or os.path.exists(TT_TOKEN_FILE)))


def tt_token():
    """Access token for this run. Tries the saved (newest) refresh token, then the TT_REFRESH_TOKEN secret;
    the new refresh token TikTok returns is saved at once (roundup.yml commits it)."""
    if _TT.get("access"):
        return _TT["access"]
    saved, _ = tt_saved_token()
    errors = []
    for refresh in dict.fromkeys(x for x in (saved, TT_REFRESH_TOKEN) if x):
        r = M.HTTP.post(f"{TT_API}/oauth/token/", timeout=30, data={
            "client_key": TT_CLIENT_KEY, "client_secret": TT_CLIENT_SECRET,
            "grant_type": "refresh_token", "refresh_token": refresh})
        try:
            j = r.json()
        except Exception:
            j = {"error": f"HTTP {r.status_code}"}
        if j.get("access_token"):
            tt_save_token(j.get("refresh_token") or refresh, j.get("refresh_expires_in"))
            _TT["access"] = j["access_token"]
            days = int(j.get("refresh_expires_in") or 10 ** 9) // 86400
            if days < 14:
                M.tg_text(f"⚠️ The TikTok login ends in {days} days. Run <code>python3 tools/tiktok_token.py</code> "
                          "once more and put the new token in the TT_REFRESH_TOKEN secret.")
            return j["access_token"]
        errors.append(str(j.get("error_description") or j.get("error") or j)[:150])
    raise RuntimeError("TikTok login failed (" + "; ".join(errors or ["no refresh token"])
                       + ") → run tools/tiktok_token.py again and update the TT_REFRESH_TOKEN secret")


TT_FRIENDLY = {
    "spam_risk_too_many_pending_share": "your TikTok inbox has too many waiting drafts (max 5 in 24 h) — "
                                        "post or delete the old ones",
    "access_token_invalid": "TikTok login expired — run tools/tiktok_token.py again",
    "scope_not_authorized": "the TikTok app is missing the video.upload permission — run tools/tiktok_token.py again",
    "spam_risk_user_banned_from_posting": "TikTok blocked posting for this account",
    "rate_limit_exceeded": "TikTok says too many uploads right now",
}


def tt_api(path, body=None):
    r = M.HTTP.post(f"{TT_API}{path}", json=body or {}, timeout=60,
                    headers={"Authorization": f"Bearer {tt_token()}", "Content-Type": "application/json; charset=UTF-8"})
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"TikTok {path} HTTP {r.status_code}: {r.text[:200]}")
    err = j.get("error") or {}
    if err.get("code", "ok") != "ok":
        code = err.get("code")
        raise RuntimeError(TT_FRIENDLY.get(code) or f"TikTok {code}: {err.get('message', '')[:200]}")
    return j.get("data") or {}


def tt_chunks(size):
    """TikTok's rules: each chunk 5–64 MB (the last may be bigger, up to 128 MB); a file ≤ 64 MB may go in one piece."""
    if size <= 64 * 1024 * 1024:
        return size, 1
    chunk = 10 * 1024 * 1024
    return chunk, size // chunk


def tiktok_inbox_upload(video):
    """Video → the TikTok app's inbox (you get a notification, tap it, add title/caption/sound, Post).
    Returns {"state": "inbox", "publish_id": …}. TikTok has no schedule here: you post it at the reminder."""
    size = len(video)
    chunk, count = tt_chunks(size)

    def go():
        d = tt_api("/post/publish/inbox/video/init/", {"source_info": {
            "source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}})
        url, pid = d.get("upload_url"), d.get("publish_id")
        if not url or not pid:
            raise RuntimeError(f"TikTok gave no upload link: {d}")
        for i in range(count):
            a = i * chunk
            b = size - 1 if i == count - 1 else a + chunk - 1
            u = M.HTTP.put(url, data=video[a:b + 1], timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(b - a + 1),
                "Content-Range": f"bytes {a}-{b}/{size}"})
            if u.status_code not in (200, 201, 206):
                raise RuntimeError(f"TikTok upload {u.status_code}: {u.text[:200]}")
        return pid
    pid = retry_once("TikTok upload", go)
    status = "PROCESSING_UPLOAD"
    for _ in range(18):                              # up to ~3 min until it is in the inbox
        time.sleep(10)
        try:
            d = tt_api("/post/publish/status/fetch/", {"publish_id": pid})
        except Exception as e:
            log("TikTok status check:", e)
            continue
        status = d.get("status") or status
        if status == "FAILED":
            raise RuntimeError("TikTok refused the video: " + str(d.get("fail_reason") or "no reason given"))
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            break
    return {"state": "inbox", "kind": "video", "publish_id": pid, "tt_status": status}


# --- photo slides: TikTok only PULLS photos from a verified web address --------------------------------------------
# The slides are put on the branch TT_PHOTO_BRANCH (ONE commit, force-pushed, so the repo history doesn't grow) and
# TikTok reads them from raw.githubusercontent.com. The signature file(s) TikTok gives you for "Verify URL prefix" go in
# the folder tiktok_verify/ on main: they are copied to the branch root every time.
TT_VERIFY_DIR = os.path.join(M.ROOT, "tiktok_verify")
TT_SMALL = (864, 1080)            # used only if TikTok says the 1080x1350 slides are too big ("max 1080p")


def tt_repo():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        url = subprocess.run(["git", "-C", M.ROOT, "remote", "get-url", "origin"], capture_output=True,
                             text=True).stdout.strip()
        repo = re.sub(r"^.*github\.com[:/]|\.git$", "", url)
    return repo


def tt_photo_prefix():
    p = TT_PHOTO_URL_PREFIX or f"https://raw.githubusercontent.com/{tt_repo()}/{TT_PHOTO_BRANCH}/"
    return p if p.endswith("/") else p + "/"


def tt_push_photos(files):
    """files = {path: bytes}. Replaces the whole branch TT_PHOTO_BRANCH with these files + tiktok_verify/*
    (uses the checkout's own login, so it works inside GitHub Actions)."""
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as idx:
        if os.path.isdir(TT_VERIFY_DIR):
            for name in os.listdir(TT_VERIFY_DIR):
                src = os.path.join(TT_VERIFY_DIR, name)
                if os.path.isfile(src) and not name.startswith(".") and name.lower() != "readme.md":
                    with open(src, "rb") as a, open(os.path.join(tmp, name), "wb") as b:
                        b.write(a.read())
        for path, data in files.items():
            full = os.path.join(tmp, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(data)
        if not os.listdir(tmp):
            raise RuntimeError("nothing to put online (tiktok_verify/ is empty)")
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(idx, "index"), GIT_AUTHOR_NAME="7seas-bot",
                   GIT_COMMITTER_NAME="7seas-bot", GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
                   GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com")

        def git(*a):
            r = subprocess.run(["git", "--git-dir", os.path.join(M.ROOT, ".git"), "--work-tree", tmp, *a], cwd=tmp,
                               env=env, capture_output=True, text=True)
            if r.returncode:
                raise RuntimeError(f"git {a[0]}: {(r.stderr or r.stdout).strip()[:300]}")
            return r.stdout.strip()
        git("add", "-A", "--", ".")
        tree = git("write-tree")
        commit = git("commit-tree", tree, "-m", "TikTok slides (replaced every night)")
        git("push", "-f", "origin", f"{commit}:refs/heads/{TT_PHOTO_BRANCH}")
    return tt_photo_prefix()


def tt_wait_online(url, minutes=4):
    """raw.githubusercontent.com can take a moment after the push."""
    end = time.time() + minutes * 60
    while True:
        try:
            r = M.HTTP.get(url, timeout=30, allow_redirects=False)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        if time.time() > end:
            return False
        time.sleep(10)


def tt_slide_files(day_s, parts):
    """parts = [(n, slides)]. Returns ({path: bytes}, {n: (big_paths, small_paths)}). The folder has a random part,
    so the addresses can't be guessed before the night's push."""
    folder = f"{day_s}-{random.randrange(16 ** 8):08x}"
    files, paths = {}, {}
    for n, slides in parts:
        big, small = [], []
        for k, (_, data, _) in enumerate(slides, 1):
            img = Image.open(io.BytesIO(data)).convert("RGB")
            if img.width > 1080:
                img = img.resize((1080, round(img.height * 1080 / img.width)))
            b, s_ = f"{folder}/p{n}/{k:02d}.jpg", f"{folder}/p{n}/small/{k:02d}.jpg"
            files[b] = _jpg(img)
            sm = img.copy()
            sm.thumbnail(TT_SMALL)
            files[s_] = _jpg(sm)
            big.append(b)
            small.append(s_)
        paths[n] = (big[:35], small[:35])            # TikTok: max 35 photos
    return files, paths


def tiktok_inbox_photos(prefix, big, small, texts):
    """Slides → TikTok inbox as a PHOTO draft with title + caption (you add a sound and Post).
    If TikTok refuses the size, the 864x1080 copies are sent instead."""
    def send(paths):
        d = tt_api("/post/publish/content/init/", {
            "media_type": "PHOTO", "post_mode": "MEDIA_UPLOAD",
            "post_info": {"title": texts["tiktok_title"][:90], "description": texts["tiktok_caption"][:4000]},
            "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0,
                            "photo_images": [prefix + p for p in paths]}})
        pid = d.get("publish_id")
        if not pid:
            raise RuntimeError(f"TikTok gave no publish_id: {d}")
        status, reason = "PROCESSING_DOWNLOAD", ""
        for _ in range(24):                          # up to ~4 min
            time.sleep(10)
            try:
                s = tt_api("/post/publish/status/fetch/", {"publish_id": pid})
            except Exception as e:
                log("TikTok status check:", e)
                continue
            status, reason = s.get("status") or status, str(s.get("fail_reason") or "")
            if status in ("FAILED", "SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
                break
        return pid, status, reason
    pid, status, reason = send(big)
    size = "1080x1350"
    if status == "FAILED" and "size" in reason:
        log("TikTok: slides too big, sending the 864x1080 copies")
        pid, status, reason = send(small)
        size = "864x1080"
    if status == "FAILED":
        hint = (" — the TikTok app must have the URL prefix " + prefix + " verified"
                if "pull" in reason or "url" in reason else "")
        raise RuntimeError("TikTok refused the slides: " + (reason or "no reason given") + hint)
    return {"state": "inbox", "kind": "photos", "publish_id": pid, "tt_status": status, "size": size,
            "photos": len(big)}


def tiktok_ready():
    mode = M.tiktok_mode()
    if mode in ("off", "manual"):
        return mode
    return "" if tt_configured() else "no secrets"


def tiktok_prepare(day_s, parts_out):
    """photos: ALL parts' slides online in ONE push before the uploads (p["tt_photos"] = (prefix, big, small));
    a failure is kept in p["tt_error"] and reported per part by tiktok_upload."""
    if M.tiktok_mode() != "photos" or tiktok_ready() or not parts_out:
        return
    try:
        files, paths = tt_slide_files(day_s, [(p["n"], p["slides"]) for p in parts_out])
        prefix = tt_push_photos(files)
        if not tt_wait_online(prefix + paths[parts_out[0]["n"]][0][0]):
            raise RuntimeError("the slides did not come online at " + prefix)
        for p in parts_out:
            p["tt_photos"] = (prefix,) + paths[p["n"]]
    except Exception as e:
        log("TikTok slides could not be put online:", e)
        for p in parts_out:
            p["tt_error"] = "putting the slides online: " + str(e)[:250]


def tiktok_upload(p):
    if M.tiktok_mode() == "video":
        return tiktok_inbox_upload(p["video"])
    if p.get("tt_error"):
        raise RuntimeError(p["tt_error"])
    return tiktok_inbox_photos(*p["tt_photos"], p["texts"])


# =============================================================================
# ALL PLATFORMS — the order the parts are uploaded in, and the key their result is saved under
# =============================================================================

def _facebook(p):
    return facebook_upload(p["video"], p["cover_tall"], p["texts"], p["at"])


def _youtube(p):
    return youtube_upload(p["video"], p["texts"], p["at"])


PLATFORMS = [("fb", "Facebook", facebook_ready, _facebook),
             ("yt", "YouTube", youtube_ready, _youtube),
             ("tt", "TikTok", tiktok_ready, tiktok_upload)]
