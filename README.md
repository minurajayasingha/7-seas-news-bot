# 7 Seas News Bot

Automatic real-news posts for the **7 Seas News** Facebook Page.
Runs free on GitHub Actions. You approve every post with one tap in Telegram.

## How it works

Every 15 minutes GitHub runs the bot:

1. **Reads your Telegram taps** – 🚀 Post now / 🕒 Queue / ❌ Skip
2. **Posts approved items to Facebook**
   - *Post now* → goes live on the next run (up to ~15–30 min)
   - *Queue* → goes live at the next US time slot (7:00, 9:30, 12:00, 15:00, 18:00, 20:30 New York time)
3. **Every 2 hours** it collects news from BBC, NPR, Al Jazeera, The Guardian, Politico, CBS, ABC, DW,
   France 24 and The Hill. It only uses stories reported by **2 or more different outlets**, skips
   South Asia and non-news, lets Gemini write a neutral headline + summary, makes the image and sends
   it to your Telegram.

**Images** (automatic, in this order):
1. Story about 1–3 people **named in the headline** → their free-licensed photos, blended side by side
   (place story with one main person → place photo + the person in a circle)
   Shootings, bombings, disasters → news design with a 📍 location tag (no random photos)
2. Otherwise → a matching free photo (Wikimedia Commons search, or Pixabay if you add `PIXABAY_API_KEY`)
3. Otherwise → the black 7 Seas globe design

**Change a draft before approving:** reply to it in Telegram with
- a **photo** → the bot rebuilds the post with your image
- **text** → the bot uses your text as the new headline

## Make your own post (in Telegram)
- Send a **news link** → the bot reads the article and writes the post (add a line above the link to use your own headline).
- Send a **photo with a caption** → first line = headline, next lines = text.
- Start with **BREAKING:** to make it breaking news.
It comes back with the normal buttons to approve.

## Keeping the chat clean
- When a post is **published**, **skipped**, **replaced** or **expired**, it is deleted from the bot chat.
  So the bot chat only shows posts still waiting for you.
- Every **published** post is copied to your **"published posts" channel** with the time and a Facebook link,
  so you can always see what went out and avoid repeats.

## Setup (one time)

### 1. Put the code on GitHub
In VS Code: open this folder → Source Control → **Publish to GitHub** → **public** repository.

### 2. Secrets
Repository → **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token from @BotFather |
| `TELEGRAM_CHAT_ID` | your Id from @userinfobot |
| `GEMINI_API_KEY` | key from aistudio.google.com |
| `FB_PAGE_ID` | Page `id` from `me/accounts` |
| `FB_PAGE_TOKEN` | the Page token that "Expires: Never" |
| `PIXABAY_API_KEY` | optional — more stock photo choices |

### 3. Permissions
**Settings → Actions → General → Workflow permissions** → **Read and write permissions** → Save.

### 4. Published-posts channel
1. Telegram → New Channel → name it e.g. *7 Seas – Published* (private is fine)
2. Channel → Administrators → Add admin → search your bot → allow **Post messages** (and **Delete messages**)
3. Post anything in the channel, then **forward that message to your bot**
4. On the next run the bot replies "Channel linked ✅"

### 5. First run
**Actions** → **7 Seas News Bot** → **Run workflow**.

## Telegram commands
- `/queue` – everything queued, with the exact posting time
- `/status` – summary
- `/new` – how to make your own post
- `/pause` · `/resume` – stop/start automatic news
- `/channel` – how to link the published-posts channel
- `/help` – button guide

## Logo
`assets/logo.png`. To change it, upload a new transparent PNG with the same name.

## Settings (easy maintenance)
Everything you might want to change is in **`bot/settings.py`**: colors, how many posts, posting times,
focus topics (US / war words), excluded topics and news sources. You never need to touch `main.py`.

## If something breaks
- Errors are sent to your Telegram.
- **"Invalid token" from Facebook** → new Page token → update `FB_PAGE_TOKEN`.
- Check the **Actions** tab → latest run → logs.
- In VS Code, always **Sync Changes before** you edit, because the bot saves its memory to GitHub every run.

## Daily roundup videos (made by the bot)

Every day after **midnight New York** the bot plans 3 roundup videos of the day's posts
with FIXED names, always in this order: **WAR & CONFLICT → US NEWS → WORLD NEWS** (`ROUNDUP_PART_NAMES`; the AI only
picks the stories, never the names; on a day with fewer than 4 conflict stories there are only 2 parts: US NEWS +
WORLD NEWS) and sends you the **plan** in Telegram:

- **✅ Approve** → it makes the videos (about 10–20 min) and schedules them
- **✏️ Change** → reply to the plan message with what to change, e.g. *"move the Gaza story to Part 1"*
- **⏭ Skip today** → no videos that day
- **No answer within 3 hours** → the bot approves by itself (`ROUNDUP_AUTO_APPROVE_HOURS` in settings)

Posting times: **7:55 / 9:55 / 11:55 New York** (`ROUNDUP_TIMES_NY`). Sri Lanka time is worked out by itself and
follows US summer/winter time: 6:25 / 8:25 / 10:25 PM SL in NY winter, 5:25 / 7:25 / 9:25 PM SL in NY summer.
Every message shows both, e.g. "6:25 PM SL · 7:55 AM NY", plus the New York date to pick in TikTok Studio.
`/roundup` shows what happened; `/roundup test` makes a test of yesterday (Telegram only, nothing uploaded).

What happens after approval (all uploads in `bot/uploads.py`, one section per platform):

| Platform | Setting | What the bot does | What you do |
|---|---|---|---|
| **Facebook** | `ROUNDUP_FACEBOOK` | Reel, scheduled at its time (refused → saved as a draft, the bot publishes it at the time) | nothing |
| **YouTube** | `ROUNDUP_YOUTUBE` | Short, scheduled at its time (+ the thumbnail once YouTube has processed it) | nothing |
| **TikTok** | `ROUNDUP_TIKTOK` | `"photos"`: the slides as a **draft in your TikTok inbox**, title + caption filled in (`"video"` = the video; `"manual"` = no draft; `"off"`) | at the reminder: TikTok → 🔔 Inbox → **System notifications** → the draft → add a sound → **Post** |

- **Bot chat** – ⏰ "Time to post TikTok Part n/3" at each posting time (✅ Posted button) and ONE daily report:
  yesterday's posts, top 3 and the roundup status per platform (Facebook · YouTube · TikTok). A video comes here
  only if its uploads failed (post it by hand).
- **Content channel** (`/content`) – every day **ONE zip** with everything. A part's slides + title/caption come as
  messages too **only** when you must post it on TikTok by hand (its draft failed, `"manual"`, or a test).
- **Published-posts channel** – at each posting time one line per part with its Facebook, YouTube and TikTok status.

The zip (same layout as the `/day` pack; every file is named `7seas_<New York day>_…`):
```
7seas_2026-11-20_Friday_roundup.zip
  2026-11-20 Friday - Roundup/
    TEXTS-AND-TIMES.txt                    every title, caption, description and time, all platforms
    Part 1 - WAR and CONFLICT/
      CAPTION.txt                          TikTok title + caption + time
      7seas_2026-11-20_part1_01_cover.jpg  the slides in order (cover first)
      7seas_2026-11-20_part1_02.jpg …
      7seas_2026-11-20_part1_cover_9x16.jpg  the video cover (thumbnail)
```

### Posting on TikTok by hand (only when the draft failed)
- **Android:** open the album → tap the first photo → ⋮ (top right) → **Save to gallery**.
  Do it for each photo, or long-press one photo in the chat → select the others → ⋮ → **Save to gallery**.
- **iPhone:** long-press one photo in the chat → **Select** → tap all photos of the album → **Save** (share icon → Save N images).
- In TikTok: **＋** → **Upload** → **Photos** → tap the slides in order **1, 2, 3…** (the number is in each photo's caption)
  → add a trending sound → paste the title + caption. Turn on TikTok's "AI-generated content" label **only** if a slide
  uses an AI image (the bot never makes AI images).

### TikTok setup (one time, about 30 minutes)
TikTok has no schedule for API uploads, so each night the bot puts each part's slides in your TikTok **inbox** as a
draft (title + caption filled in); at the reminder you add a sound and Post. Done for 7 Seas News on 2026-11-21
(Sandbox app "7 Seas Bot", target user 7seas.news) — the steps are here in case it must be done again. TikTok only takes photos from a web
address you have verified: the bot puts the slides on the branch `tt-photos` of this repo, and TikTok reads them from
`https://raw.githubusercontent.com/minurajayasingha/7-seas-news-bot/tt-photos/`.

**A. Create the app** (developers.tiktok.com → log in with any TikTok account → **Manage apps → Connect an app**)
1. App name **7 Seas News**, icon 1024×1024 (the logo), category News, description: "Publishing tool of the 7 Seas
   News page: sends our daily news roundup slides to our TikTok inbox as drafts, which we review and post ourselves."
2. Platforms: **Web** (website `https://minurajayasingha.github.io/7-seas-news-bot/`).
3. Terms of Service URL `…/7-seas-news-bot/terms.html`, Privacy Policy URL `…/7-seas-news-bot/privacy.html`.
4. Add products **Login Kit** (**Web** → Redirect URI `https://minurajayasingha.github.io/7-seas-news-bot/tiktok-callback/`)
   and **Content Posting API** (Direct Post off).
   Scopes: `user.info.basic`, `video.upload` only (remove anything else).
5. **Sandbox** (top of the app page) → create one → **Target users** → add the 7 Seas News TikTok account. Sandbox
   works without TikTok's review; Sandbox has its own Client key/secret.

**B. Verify the addresses** (app → **URL properties → Verify properties**)
6. **Website** prefix `https://minurajayasingha.github.io/7-seas-news-bot/` → download the signature file → put it in
   `docs/` → commit + sync → wait 2 min → Verify.
7. **Photos** (Content Posting API → Verify domains → URL prefix)
   `https://raw.githubusercontent.com/minurajayasingha/7-seas-news-bot/tt-photos/` → download the signature file →
   put it in `tiktok_verify/` → add `"ttverify:1"` to `RUN_ONCE` in settings → commit + sync → the bot chat says
   "TikTok verify file ✅ online" (~15 min) → Verify **in the same window** (every new window = a new file).

**C. Connect the bot**
8. Put the Sandbox keys in `tools/.tiktok_keys` (two lines `key=…` and `secret=…`; never committed) →
   `python3 tools/tiktok_token.py --web` → log in with the **7 Seas News TikTok account** → Allow → the 7 Seas page
   shows an address → `python3 tools/tiktok_token.py --web --code "<that address>"` → it saves the login encrypted in
   `state/tiktok_token.json` → commit + sync.
9. GitHub → repo → **Settings → Secrets and variables → Actions** → add `TT_CLIENT_KEY`, `TT_CLIENT_SECRET`.
10. Test: add `"tttest:1"` to `RUN_ONCE` → commit + sync. Two TEST slides should appear in the TikTok **phone app**
    → Inbox → System notifications (~15 min; delete them) and the bot chat says "TikTok connection test ✅".

Good to know:
- TikTok changes the refresh token every time the bot logs in. The newest one is kept **encrypted** in
  `state/tiktok_token.json` (key = your client secret), so you never need to update the secret again — unless the bot
  says the login failed or ends soon: then repeat steps 8–9.
- Max **5 waiting inbox drafts in 24 h**: post or delete each day's drafts. The TikTok app must be version 31.8+.
- `ROUNDUP_TIKTOK = "video"` sends the video instead; `"manual"` = no draft, slides + texts in the content channel;
  `"off"` = no TikTok at all.
- Any TikTok call from your own computer changes the login too → commit `state/tiktok_token.json` afterwards.

### YouTube setup (one time, about 15 minutes)
1. Go to **console.cloud.google.com** → create a project (e.g. "7 Seas Bot").
2. **APIs & Services → Library** → search **YouTube Data API v3** → **Enable**.
3. **APIs & Services → OAuth consent screen** → External → fill in the app name + your email → add yourself as a
   test user → then **Publish app** so the status is **"In production"**
   (in "Testing" the login stops working after 7 days).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID → Desktop app** → copy the
   **Client ID** and **Client secret**.
5. On your computer, in this repo folder: `python3 tools/youtube_token.py` → paste the two values → log in with the
   Google account of the **YouTube channel** → allow → it prints the **refresh token**. (Google may say the app is
   "unverified": click *Advanced → Go to 7 Seas Bot*. It's your own app.)
6. GitHub → repo → **Settings → Secrets and variables → Actions** → add `YT_CLIENT_ID`, `YT_CLIENT_SECRET`,
   `YT_REFRESH_TOKEN`.
7. In `bot/settings.py` set `ROUNDUP_YOUTUBE = True` → commit → sync.
8. After the first day, open YouTube Studio → Content: the 3 Shorts should say **Scheduled**. If Google keeps them
   **locked as private** ("unverified API project"), fill in YouTube's API audit form for the project
   (search "YouTube API Services Audit and Quota Extension Form"); until then they can be published by hand in Studio.
   Custom thumbnails need a **verified channel** (YouTube Studio → Settings → Channel → Feature eligibility).
