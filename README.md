# 7 Seas News Bot

Automatic real-news posts for the **7 Seas News** Facebook Page.
Runs free on GitHub Actions. You approve every post with one tap in Telegram.

## How it works

Every 15 minutes GitHub runs the bot:

1. **Reads your Telegram taps** – 🚀 Post now / 🕒 Queue / ❌ Skip
2. **Posts approved items to Facebook**
   - *Post now* → goes live within ~15–30 minutes
   - *Queue* → goes live at the next US time slot (7:00, 9:30, 12:00, 15:00, 18:00, 20:30 New York time)
3. **Every 2 hours** it collects news from BBC, NPR, Al Jazeera, The Guardian, Politico, CBS, ABC, DW, France 24 and The Hill.
   It only uses stories reported by **2 or more different outlets**, skips South Asia and non-news,
   lets Gemini write a neutral headline + summary, makes the image and sends it to your Telegram.

**Images** (automatic, in this order):
1. If the story is about 1–2 named people → their free-licensed photo from Wikimedia Commons (side by side for 2)
2. Otherwise → a matching free photo from Wikimedia Commons (no key needed), or Pixabay if you add `PIXABAY_API_KEY`
3. Otherwise → the black 7 Seas globe design

**Change a draft before approving:** reply to it in Telegram with
- a **photo** → the bot rebuilds the post with your image
- **text** → the bot uses your text as the new headline

It sends the new version back with fresh buttons (takes up to ~15 min).

## Setup (one time)

### 1. Create the repository
1. GitHub → **New repository** → name `7-seas-news-bot` → **Public** → Create.
2. Click **uploading an existing file** and drag in: the `bot`, `state` and `assets` folders, `requirements.txt` and `README.md`.
3. The `.github` folder is hidden on Mac, so create the workflow by hand:
   **Add file → Create new file** → name it exactly `.github/workflows/bot.yml` → paste everything from `workflow-bot.yml` → **Commit**.

### 2. Add your secrets
Repository → **Settings → Secrets and variables → Actions → New repository secret**. Add these 5:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token from @BotFather |
| `TELEGRAM_CHAT_ID` | your Id from @userinfobot |
| `GEMINI_API_KEY` | key from aistudio.google.com |
| `FB_PAGE_ID` | Page `id` from `me/accounts` |
| `FB_PAGE_TOKEN` | the Page token that "Expires: Never" |

Optional: `PIXABAY_API_KEY` (free at pixabay.com/api/docs) → more stock photo choices.

### 3. Allow the bot to save its memory
**Settings → Actions → General → Workflow permissions** → choose **Read and write permissions** → Save.

### 4. First test
**Actions** tab → enable workflows if asked → **7 Seas News Bot** → **Run workflow**.
In 1–2 minutes you should get posts in Telegram. Tap a button; it takes effect on the next run (≤15 min).

## Telegram commands
- `/status` – what's waiting and the next time slot
- `/help` – button guide
- Reply to a draft with a photo or text – change its image or headline

## Logo
Your logo is in `assets/logo.png`. To change it, upload a new transparent PNG with the same name.

## Changing settings
Everything is in the **CONFIG** section at the top of `bot/main.py`: sources, time slots,
how many drafts per run, excluded words.

## If something breaks
- The bot sends errors to your Telegram.
- **"Invalid token" from Facebook** → you changed your Facebook password or removed the app. Make a new Page token and update `FB_PAGE_TOKEN`.
- **Gemini 429** → free daily limit reached; it continues next run.
- Check **Actions** tab → latest run → logs.
