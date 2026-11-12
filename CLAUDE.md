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
  4. AUTO_PUBLISH (default True): each new draft is auto-queued ("🤖 Auto-posting…", ↩️ Cancel) and published by
     publish_due without a tap — BREAKING at once, others one per AUTO_MIN_GAP_MINUTES, max AUTO_MAX_PER_DAY per NY day
     (state["auto_count"], state["last_auto_at"]). Not auto: manual posts, look-alikes of recent posts, over the limit,
     no real photo when AUTO_NEEDS_PHOTO (default True:
     brand/globe drafts wait in Telegram with "✋ Not auto-posted: no real photo found"). AUTO_REELS="breaking" = BREAKING + real photo also gets a Reel.
- Memory is `state/state.json`, committed back by the workflow ("Save bot memory" step
  fetches + resets to origin/main before committing, so code pushes during a run don't break it).
- **All user settings live in `bot/settings.py`** (colors, feeds, focus words, slots, counts). Prefer editing there.

## Secrets (GitHub Actions)
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, FB_PAGE_ID, FB_PAGE_TOKEN (never-expiring Page token),
optional PIXABAY_API_KEY / PEXELS_API_KEY / FLICKR_API_KEY. Never print or commit secrets.

## Telegram UX
- Draft buttons: 🚀 Post now · 🎬 Reel (only if REELS_ENABLED) · 🕒 Queue (next New York slot) · 🔄 Other photo · ❌ Skip;
  queued posts get ↩️ Cancel.
- 🎬 Reel = publish the post as normal AND make a single-story Reel (REELS_PER_DAY per NY day, REEL_SECONDS long;
  over the limit → post only + Telegram note). Button shown only on drafts with a real photo (REELS_ONLY_GOOD_PHOTOS).
  Video: 1080×1920 30 fps H.264 + AAC via ffmpeg+Pillow; sounds are synthesized in code (reel_audio: key click per letter,
  end whoosh, BREAKING news-alert sting with typing starting at 1.1 s; REEL_TYPING_SOUND / REEL_BREAKING_SOUND / REEL_SOUND_VOLUME)
  (make_reel): post image at y=285, blurred 45%-dark photo zoom above, post bottom colour below, headline
  re-typed in Poppins Bold with red cursor (render_image(hide_headline=True, layout=…)), end card
  "FOLLOW FOR MORE". Published with Graph video_reels start → rupload.facebook.com → finish PUBLISHED
  (GRAPH_VERSION in main.py); link logged to the log channel. bot.yml installs ffmpeg only if REELS_ENABLED = True.
- Reply to a draft with a photo → new background; with text → new headline.
- Send a link (bot reads article + Gemini) or a photo with caption (line 1 = headline) → manual post. "BREAKING:" prefix.
- Log-channel messages of published posts have 🗑 Delete (asks ✅ Yes / ↩️ Keep; only the owner's taps count —
  callback `from.id` must equal TELEGRAM_CHAT_ID) → DELETE /{post_id} (+ its Reel); stats edits keep the button.
- Published/skipped/replaced posts are deleted from the bot chat; published ones are logged to a linked channel
  (linked by forwarding a channel message to the bot).
- Commands: /day /news /queue /status /stats /new /pause /resume /channel /tiktok /help.
- Post stats: every STATS_EVERY_MINUTES the bot reads reactions/comments/shares (+ reach if the token allows)
  for posts of the last STATS_DAYS and edits the matching log-channel message; /stats = last 24 h ranking.
- Posts go to the Page Story per SHARE_TO_STORY ("breaking" = only BREAKING posts, "all", "off"). The /tiktok "content channel" gets
  posts one by one only if SEND_EACH_POST_TO_CONTENT_CHANNEL = True (default False: daily pack only).

- Dates for the audience use New York time (image date, published log, TikTok file names). After NY midnight the bot
  sends a daily pack to the content channel (or bot chat) as 2 messages: titles + "End of <day>", and ONE zip
  with one folder named after the day ("2026-11-10 Tuesday") holding the day's images in order
  (DAY_PACK_SIZE "9x16" or "4x5"; split into parts above 45 MB).

## Design rules (image 1080×1350)
- Brand: black background, white text, red **#CE0000**, Poppins font, logo `assets/logo.png` top-left.
- Footer: "SOURCES: …" + date; small grey photo credit line only for CC BY licences.
- People photos only for people named in the headline (Wikipedia page image, free licence only), up to 3,
  blended side by side (no divider lines). One person + place story → place photo + person in a circle.
- Shootings/bombings/disasters ("incident") → INCIDENT_PLACE_PHOTO: place_photo() = a city view of the location
  ("<city> skyline/downtown/city center/street/square, <rest>", NATURE_WORDS avoided, country-checked); none →
  map card → brand globe. Never photos of an event (could be an older, different one).
- No photo chain (all stories): people/event/scene → place_photo (town → Gemini "nearby_city" → "<State> State Capitol")
  → MAP_CARDS map_card(): Wikipedia geocode of location, must fall in the story's country; map_background() draws
  assets/map_data.json (Natural Earth 1:50m countries + US/CA/AU states, public domain, rebuilt by rounding coords),
  country or state highlighted red, pin + city label, 📍 tag. bg type "map" counts as a real image for auto-posting
  (not for Reels). Only brand/globe drafts wait for the owner.
- Photo variety: each person gets a pool of ~12 free Commons photos (state["photo_memory"]["pools"], refreshed weekly);
  the last NO_REPEAT_PHOTOS used photos are avoided everywhere; PHOTO_SEARCH_FIX fixes bad place searches (White House).
- Scene photos rotate through TOPIC_PHOTO_IDEAS (settings) + Gemini "image_queries"; ideas used lately go last.
  "Wall Street, New York" = file name must contain "Wall Street", "New York" only helps the search. JPEG photos only.
- Never use photos from news sites (copyright; credit is not permission). Wikimedia Commons / Flickr (free licences only:
  FLICKR_LICENSES = CC BY/BY-SA 2.0+4.0, CC0, PD, US Government Work, no known restrictions) / Pexels / Pixabay /
  user's own photos only.
- Real event photos first: Gemini "event_query" → event_photo() = Flickr uploads since 1 day before the news, country-checked;
  Flickr is also tried first for scene ideas. Needs FLICKR_API_KEY (Flickr Pro only; not set → skipped).
- USE_OPENVERSE: openverse_photo() (api.openverse.org, no key, ~15 s, often 504 → one retry; max 2 calls per story,
  stops after 3 failures per run). Licences by/by-sa/cc0/pdm, JPEG ≥1000 px, words before the comma in title/tags,
  NOT_A_PLACE_PHOTO skips people/event/vehicle photos (no date filter). wrong_capitol(): no state capitols for Congress.
- STRICT_PHOTO_MATCH: a place photo must name the story's country (location first, else headline; US POLITICS/ELECTIONS
  = US) in its title/description/categories (Pixabay tags, Pexels alt) and no other country (border photos allowed);
  no safe photo → branded globe. Country words: COUNTRY_WORDS in main.py.
- Caption: headline, summary, (breaking: "What we know so far"), neutral question hook,
  "🔗 Source in the comments 👇" (LINK_IN_FIRST_COMMENT; False = old "📖 Read more" link in the caption),
  FOLLOW_LINE (never twice), hashtags. With LINK_IN_FIRST_COMMENT the bot waits 5 s after publishing and comments
  "📖 Read the full story: <url>" (+ "📌 Key facts" from key_points, COMMENT_KEY_FACTS, not for BREAKING) as the Page (POST /{post_id}/comments, needs pages_manage_engagement); a failed
  comment is reported to the log channel (+ token steps once) and never retries/fails the post.

## Editorial rules (Gemini prompt in main.py)
Neutral, no opinions, only facts from the reports. Headlines = plain facts (who did what, where).
BANNED_HEADLINE_WORDS (settings): if the headline/summary has one, Gemini rewrites once (gemini_write_neutral);
still there → story skipped.

## Working on this repo
- Owner edits in VS Code and pushes; the bot also commits state every run → always pull/sync first.
- Test changes locally with mocks (no network to news sites needed); keep `python -c "import ast"` clean.
- Owner prefers simple step-by-step English explanations.
