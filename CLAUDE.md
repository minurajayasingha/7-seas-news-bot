# 7 Seas News Bot — project notes for Claude

Automated real-news Facebook page bot for **7 Seas News** (English, politics; US focus first —
Trump, elections, Congress, plus wars/attacks — then worldwide). Owner: Minura.
Never South Asia news. Real, verified news only: a story needs 2+ different outlets.

## How it runs
- GitHub Actions, `.github/workflows/bot.yml`. GitHub's own schedule is unreliable (runs hours late), so
  cron-job.org triggers workflow_dispatch every 15 min with force_draft=false; manual "Run workflow" forces a news search.
- After its work each run stays online LISTEN_MINUTES (12) long-polling Telegram, so taps/replies/Post now are
  handled within seconds; job timeout 20 min. /news searches news immediately.
- News reading: all feeds fetched in parallel with a 45 s hard limit; story matching uses simple word roots (stem()).
- `bot/main.py` does everything in one run:
  1. reads Telegram button taps/replies (getUpdates, no webhook)
  2. publishes approved posts to the Facebook Page (Graph API `/{page_id}/photos`)
  3. every `DRAFT_EVERY_MINUTES`: RSS → cluster stories → Gemini writes post (JSON) → image → Telegram draft
- Memory is `state/state.json`, committed back by the workflow ("Save bot memory" step
  fetches + resets to origin/main before committing, so code pushes during a run don't break it).
- **All user settings live in `bot/settings.py`** (colors, feeds, focus words, slots, counts). Prefer editing there.

## Secrets (GitHub Actions)
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, FB_PAGE_ID, FB_PAGE_TOKEN (never-expiring Page token),
optional PIXABAY_API_KEY / PEXELS_API_KEY. Never print or commit secrets.

## Telegram UX
- Draft buttons: 🚀 Post now · 🕒 Queue (next New York slot) · 🔄 Other photo · ❌ Skip; queued posts get ↩️ Cancel.
- Reply to a draft with a photo → new background; with text → new headline.
- Send a link (bot reads article + Gemini) or a photo with caption (line 1 = headline) → manual post. "BREAKING:" prefix.
- Published/skipped/replaced posts are deleted from the bot chat; published ones are logged to a linked channel
  (linked by forwarding a channel message to the bot).
- Commands: /day /news /queue /status /stats /new /pause /resume /channel /tiktok /help.
- Post stats: every STATS_EVERY_MINUTES the bot reads reactions/comments/shares (+ reach if the token allows)
  for posts of the last STATS_DAYS and edits the matching log-channel message; /stats = last 24 h ranking.
- Every published post is also shared to the Page Story (SHARE_TO_STORY) and, if linked via /tiktok,
  sent to a TikTok channel as a 1080×1920 file + caption (no link) for easy download.

- Dates for the audience use New York time (image date, published log, TikTok file names). After NY midnight the bot
  sends a daily pack (headlines, 9:16 files in order, TikTok caption, "End of <day>") to the TikTok channel (or bot chat).

## Design rules (image 1080×1350)
- Brand: black background, white text, red **#CE0000**, Poppins font, logo `assets/logo.png` top-left.
- Footer: "SOURCES: …" + date; small grey photo credit line only for CC BY licences.
- People photos only for people named in the headline (Wikipedia page image, free licence only), up to 3,
  blended side by side (no divider lines). One person + place story → place photo + person in a circle.
- Shootings/bombings/disasters ("incident") → brand globe + red pin + 📍 location tag, no random photos.
- Photo variety: each person gets a pool of ~12 free Commons photos (state["photo_memory"]["pools"], refreshed weekly);
  the last NO_REPEAT_PHOTOS used photos are avoided everywhere; PHOTO_SEARCH_FIX fixes bad place searches (White House).
- Never use photos from news sites (copyright). Wikimedia Commons / Pixabay / user's own photos only.
- Caption: headline, summary, (breaking: "What we know so far"), neutral question hook, 📖 Read more link, hashtags.

## Editorial rules (Gemini prompt in main.py)
Neutral, no opinions, only facts from the reports, catchy but never misleading.

## Working on this repo
- Owner edits in VS Code and pushes; the bot also commits state every run → always pull/sync first.
- Test changes locally with mocks (no network to news sites needed); keep `python -c "import ast"` clean.
- Owner prefers simple step-by-step English explanations.
