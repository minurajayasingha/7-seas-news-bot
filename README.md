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
