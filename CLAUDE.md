# 7 Seas News Bot — project notes for Claude

Automated real-news Facebook page bot for **7 Seas News** (English, politics; US focus first —
Trump, elections, Congress, plus wars/attacks — then worldwide). Owner: Minura.
Never South Asia news. Real, verified news only: a story needs 2+ different outlets.

## How it runs
- GitHub Actions, `.github/workflows/bot.yml`. GitHub's own schedule is unreliable (runs hours late), so
  cron-job.org triggers workflow_dispatch every 15 min with force_draft=false; manual "Run workflow" forces a news search.
- After its work each run stays online LISTEN_MINUTES (12) long-polling Telegram, so taps/replies/Post now are
  handled within seconds; job timeout 20 min. /news searches news immediately.
- News choice (Stage 1 of docs/AUTOMATION_PLAN.md): PROMPT returns "importance" 1–10; not_important_reason() skips
  < MIN_IMPORTANCE, or FILLER_TITLE_WORDS (AI headline or most outlet titles) unless ≥ FILLER_MIN_IMPORTANCE; BREAKING
  always passes; d["importance"] saved. same_story_check() (FOLLOWUP_CHECK) runs BEFORE writing: only when a post of the
  last FOLLOWUP_HOURS shares 2+ word roots, Gemini (gemini_json helper) answers same_story/new_development; same without
  a big development → skipped. Skipped stories go into recent_topics with id "skipped" (block SKIPPED_TOPIC_HOURS only).
  quiet_day(): < MIN_STORIES_PER_DAY posts by QUIET_DAY_HOUR_NY → non-focus news needs QUIET_DAY_MIN_SOURCES outlets.
- Network: HTTP session retries connection errors (all methods) and read errors/429/5xx (GET/DELETE only, so a Facebook
  POST is never resent by urllib3); tg() retries 3× and returns {"ok": False} instead of raising. publish_due: a failed
  Telegram image download (tg_download) is retried quietly (note only at 8/40 fails); a Facebook connection error is
  retried quietly 5×. Network errors in main() alert only after 3 runs in a row (state["net_errors"]).
  draft_one() = one story; a failing story never stops the others.
- News reading: all feeds fetched in parallel with a 45 s hard limit; story matching uses simple word roots (stem()).
- `bot/main.py` does everything in one run:
  1. reads Telegram button taps/replies (getUpdates, no webhook)
  2. publishes approved posts to the Facebook Page (Graph API `/{page_id}/photos`)
  3. every `DRAFT_EVERY_MINUTES`: RSS → cluster stories → Gemini writes post (JSON) → image → Telegram draft
  4. AUTO_PUBLISH (default True): each new draft is auto-queued ("🤖 Auto-posting…", ↩️ Cancel) and published by
     publish_due without a tap — BREAKING at once, others one per AUTO_MIN_GAP_MINUTES, max AUTO_MAX_PER_DAY per NY day
     (state["auto_count"], state["last_auto_at"]). Not auto: manual posts, look-alikes only if SKIP_LOOKALIKES (default False:
     look-alikes are posted and the log-channel message says "⚠️ Looks like an earlier post" → 🗑 Delete), over the limit,
     more than AUTO_MAX_WAITING auto posts waiting, no real photo when AUTO_NEEDS_PHOTO (default True:
     brand/globe drafts wait in Telegram with "✋ Not auto-posted: no real photo found"); FB_SOFT_CAP (30) → after that only
     BREAKING / importance 8+ news. AUTO_REELS="breaking" (default) = only
     BREAKING posts get a Reel (branded cover OK), max REELS_PER_DAY (3, the 🎬 button included); "more" = also real-photo
     posts (last 2 kept for breaking) — auto_reel_wanted(). BREAKING_WITHOUT_PHOTO: breaking news auto-posts
     with the branded cover.
- Memory is `state/state.json`, committed back by the workflow ("Save bot memory" step
  fetches + resets to origin/main before committing, so code pushes during a run don't break it).
- **All user settings live in `bot/settings.py`** (colors, feeds, focus words, slots, counts). Prefer editing there.

## Daily roundup videos (Stages 3–4, docs/AUTOMATION_PLAN.md)
- main.py (owns Telegram + state.json): roundup_due() each run → after NY midnight (day ≥ ROUNDUP_START_DAY, NY hour < 11)
  roundup_start(): Gemini plan (ROUNDUP_PROMPT → roundup_clean_plan; AI down → roundup_fallback_plan by label) in
  state["roundup"][day] {status asked/building/built/failed/skipped, plan{parts[name,tag,of,stories(1-based into ids),
  hook,title,question,hashtags,tags],ids,dropped}, heads, msg_id, asked_at, test}.
  Part names are FIXED (ROUNDUP_PART_NAMES = WAR & CONFLICT, US NEWS, WORLD NEWS, always this order; hashtags
  ROUNDUP_PART_HASHTAGS #warnews #usnews #worldnews): Gemini returns "part": 1-3 and only picks stories/hooks/texts;
  roundup_clean_plan() sets name/tag by part number (Gemini's names ignored). Part 1 < ROUNDUP_MIN_CONFLICT_STORIES (4)
  → 2 parts (US NEWS + WORLD NEWS; conflict stories go to US NEWS if countries_in(headline) has the US, else WORLD
  NEWS), part["of"] = 2 → "Part n/2" everywhere, times = first 2 of ROUNDUP_TIMES_NY. Names are in every TikTok/YouTube
  title ("US NEWS: … (Part 1/3)") and cover label; the part hashtag is first in every caption (roundup.part_tag()). Buttons rok/rchg/rskip:<day>; a text reply to the
  plan message = change (Gemini edits, plan resent, 3 h restart); ROUNDUP_AUTO_APPROVE_HOURS → roundup_approve("auto").
  Approve writes /tmp/7seas_roundup_dispatch.json; bot.yml's last step (after Save bot memory, permissions actions: write)
  dispatches roundup.yml with GITHUB_TOKEN. No result in state/roundup.json after 80 min → asked again once, then failed.
  At each part's post_at: TikTok reminder with ✅ Posted (rdone:day:n) in the bot chat, Facebook "draft" parts are
  published (fb_reel_finish PUBLISHED), and roundup_part_line() goes to the published channel. Then daily_report_due(). /roundup = status, /roundup test = test of yesterday.
- bot/roundup.py (roundup.yml, 45 min, ffmpeg; reads state.json, writes state/roundup.json + state/tiktok_token.json): per part make_cover()
  (1080x1350, branded globe), slides = cover + published images (tg_download), make_part_video() 1080x1920: cover 1.3 s +
  boom, red swipe with white edge + whoosh, per story story_frame() (render_image hide_headline, date=day; top = blurred r34
  45 % dark zoom of rows 170–900 feathered 120 px; counter pill) typed headline + clicks, hold 2.2 s (shortened so ≤ 88 s),
  end card; progress line y 0–8. post_times(): ROUNDUP_TIMES_NY 7:55/9:55/11:55 NY next morning, shifted together if
  late (not in test).
  Uploads (not test; bot/uploads.py): facebook_upload (fb_reel_upload → fb_reel_cover BEFORE finish (+1 retry after) → finish SCHEDULED,
  refused → DRAFT); fb/yt results carry "thumb" ("set" or reason); not set → bot chat gets the 9:16 cover + Studio/
  Business Suite link + reason per part (manual thumbnail reminder); youtube_upload (resumable,
  private + publishAt, category 25, thumbnail best effort; ROUNDUP_YOUTUBE + YT_* secrets). Each retried once.
  Telegram to the content channel: ONE zip (backup_zip(): "<day> <Weekday> - Roundup/" with TEXTS-AND-TIMES.txt + a
  folder per part: CAPTION.txt, slides 7seas_<day>_partN_01_cover.jpg…, 7seas_<day>_partN_cover_9x16.jpg). A part's
  text + albums (send_tiktok) ONLY when it must be posted on TikTok by hand (tt not "inbox": error/manual/test).
  mp4s → bot chat only on upload failure or test; report → bot chat only in tests (main sends the daily report).
- Roundup design: see `docs/ROUNDUP_DESIGN.md` + `bot/roundup_design.py` (the ONLY place for roundup look/size/timing
  numbers: covers, cover_9x16, story_canvas, draw_counter, typing_frame, wipe, end_frame, TIMING; sounds = the bot's own Reel
  sounds via main.roundup_audio (boom, Reel key click per letter, Reel whoosh per swipe); never
  copy its numbers elsewhere, never "improve" them). roundup.py only calls it; story typing uses render_image's own
  layout (+OY 285). Golden test must pass: `python tests/test_roundup_design.py` (pixel-exact vs tests/golden/, needs
  Pillow with raqm — Mac: brew install fribidi + DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib); roundup.yml runs it
  before making anything. Hook rule: 2 sentences, each fits one line (split_hook, ~32 chars); roundup_fit_hooks()
  asks Gemini once for shorter hooks, then roundup_safe_hook() (first sentence, else second, never wrapped/shrunk).
  Cover date + weekday from the NEWS day via strftime. TikTok slides = cover + the bot's normal post images.
  Design preview (dry run): RUN_ONCE "roundup_preview:YYYY-MM-DD" or roundup.yml day "preview YYYY-MM-DD" →
  design_preview(): 3 TikTok covers, 3 video covers, a mid-typing frame, last frame, Part 1 video to the bot chat.
- tools/youtube_token.py = one-time local OAuth helper (loopback) → refresh token. README has the owner steps.
- bot/uploads.py = ALL roundup uploads, one section per platform with the same shape: <platform>_ready() ("" or
  "off"/"no secrets"/"manual") + upload → result dict; PLATFORMS = [(fb, Facebook), (yt, YouTube), (tt, TikTok)];
  roundup.run() loops over it (test → {"state": "test"}, exception → {"state": "error"}). Result states, same words
  everywhere (main.PLATFORM_TEXT): scheduled · draft · inbox · published · off · manual · no secrets · test · error.
- TikTok: ROUNDUP_TIKTOK = "photos" (default) / "video" / "manual" / "off" (main.tiktok_mode(); True/False still work).
  photos: tiktok_prepare() → tt_slide_files() (1080-wide + 864x1080 "small" copies, random folder) → tt_push_photos()
  force-pushes ONE commit (temp index, commit-tree) to branch TT_PHOTO_BRANCH "tt-photos" with the slides +
  tiktok_verify/* (TikTok signature files, VERIFIED prefix https://raw.githubusercontent.com/<repo>/tt-photos/) →
  tiktok_upload → /post/publish/content/init/ PHOTO MEDIA_UPLOAD PULL_FROM_URL with title (≤90) + caption; size
  refused → small copies. video: tiktok_inbox_upload() FILE_UPLOAD (≤64 MB one chunk, else 10 MB chunks) → PUT
  Content-Range → status/fetch until SEND_TO_USER_INBOX. results[n]["tt"] = {"state": "inbox", kind, publish_id} or
  error (+ "slides": "sent" when posted to the content channel for hand posting). main.tiktok_how(tt) = what to do
  (reminder). The draft is in the phone app → Inbox → System notifications. tt_token(): refresh token ROTATES → saved
  encrypted (HMAC-SHA256 stream + MAC, key from TT_CLIENT_SECRET; repo is PUBLIC, never plain) in
  state/tiktok_token.json (.gitignore exception; committed by roundup.yml's save step); TT_REFRESH_TOKEN secret =
  optional fallback; ONE refresh per run (_TT cache); any local live call rotates it → commit the file.
  tools/tiktok_token.py: keys from tools/.tiktok_keys (gitignored); --web = Login Kit WEB redirect
  https://minurajayasingha.github.io/7-seas-news-bot/tiktok-callback/ (docs/tiktok-callback/ shows the code; 2 steps:
  --web, then --web --code "<address>"); desktop/localhost mode failed with TikTok ("client_key" error). Sandbox app
  "7 Seas Bot" (target user 7seas.news), scopes user.info.basic + video.upload. RUN_ONCE "ttverify:<id>" = tt_verify(),
  "tttest:<id>" = tt_test(). Secrets TT_CLIENT_KEY / TT_CLIENT_SECRET.
- File names: main.file_name(day, *bits, ext) → 7seas_<NY day>_<bits>.<ext> for every file (slides, mp4, covers,
  /day images); zips: 7seas_<day>_<Weekday>[_roundup].zip with ONE root folder "<day> <Weekday>[ - Roundup]".

## Secrets (GitHub Actions)
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, FB_PAGE_ID, FB_PAGE_TOKEN (never-expiring Page token),
optional PIXABAY_API_KEY / PEXELS_API_KEY / FLICKR_API_KEY, YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN (roundup YouTube),
TT_CLIENT_KEY / TT_CLIENT_SECRET (roundup TikTok inbox; TT_REFRESH_TOKEN optional). Never print or commit secrets.

## Telegram UX
- Spacing: MIN_MINUTES_BETWEEN_POSTS (0 = owner wants news out at once; AUTO_MIN_GAP_MINUTES 0, DRAFTS_PER_RUN 5, AUTO_MAX_PER_DAY 80) between ALL Facebook posts (state["last_post_at"]). 🚀 Post now / 🎬 Reel /
  auto get d["post_at"] = next_free_time() and the button shows "🕒 Posts at … SL · … NY"; 🕒 Queue slot posts wait
  in publish_due (one notice). BREAKING_SKIPS_GAP: breaking posts go at once, then replan_waiting() pushes the others.
  Waiting posts show ⚡ Post now anyway (callback rush:) → d["rush"] = skips the gap, others are re-planned.
- Draft buttons: 🚀 Post now · 🎬 Reel (only if REELS_ENABLED) · 🕒 Queue (next New York slot) · 🔄 Other photo · ❌ Skip;
  queued posts get ↩️ Cancel.
- 🎬 Reel = publish the post as normal AND make a single-story Reel (REELS_PER_DAY per NY day, REEL_SECONDS long;
  over the limit → post only + Telegram note). Button shown only on drafts with a real photo (REELS_ONLY_GOOD_PHOTOS).
  Video: 1080×1920 30 fps H.264 + AAC via ffmpeg+Pillow; sounds are synthesized in code (reel_audio: key click per letter,
  end whoosh, BREAKING news-alert sting with typing starting at 1.1 s; REEL_TYPING_SOUND / REEL_BREAKING_SOUND / REEL_SOUND_VOLUME)
  (make_reel): post image at y=285, blurred 45%-dark photo zoom above, post bottom colour below, headline
  re-typed in Poppins Bold with red cursor (render_image(hide_headline=True, layout=…)), end card
  "FOLLOW FOR MORE". Cover: first COVER_FRAMES frames show the full headline + REEL_COVER jpg sent to
  POST /{video_id}/thumbnails (is_preferred; failure only logged). Published with Graph video_reels start → rupload.facebook.com → finish PUBLISHED
  (GRAPH_VERSION in main.py); link logged to the log channel.
  After publishing, reel_status() polls GET /{video_id}?fields=status,permalink_url,published (≤150 s) and the log
  says live / still processing / rejected (with Facebook's reason). /reels re-checks the last 5 Reels. bot.yml installs ffmpeg only if REELS_ENABLED = True.
- Reply to a draft with a photo → new background; with text → new headline.
- Send a link (bot reads article + Gemini) or a photo with caption (line 1 = headline) → manual post. "BREAKING:" prefix.
- Log-channel messages of published posts have 🗑 Delete (asks ✅ Yes / ↩️ Keep; only the owner's taps count —
  callback `from.id` must equal TELEGRAM_CHAT_ID) → DELETE /{post_id} (+ its Reel); stats edits keep the button.
- Published/skipped/replaced posts are deleted from the bot chat; published ones are logged to a linked channel
  (linked by forwarding a channel message to the bot).
- Commands: /day /news /queue /status /stats (/stats week = posts per day vs results per post) /new /pause /resume /channel /content (/tiktok) /help.
- Post stats: every STATS_EVERY_MINUTES the bot reads reactions/comments/shares (+ reach if the token allows)
  for posts of the last STATS_DAYS and edits the matching log-channel message; /stats = last 24 h ranking.
- Posts go to the Page Story per SHARE_TO_STORY ("breaking" = only BREAKING posts, "all", "off"). The content channel (/content, old name /tiktok; state key tiktok_channel) gets
  posts one by one only if SEND_EACH_POST_TO_CONTENT_CHANNEL = True (default False).

- Dates for the audience use New York time (image date, published log, TikTok file names). NO automatic daily pack:
  /day (today so far) and /day yesterday send_day_pack() to the bot chat: titles + ONE zip with one folder named
  after the day ("2026-11-10 Tuesday") holding the day's images in order (DAY_PACK_SIZE "9x16" or "4x5"; >45 MB split).

## Clean Telegram (docs/AUTOMATION_PLAN.md "Clean-up decisions")
- Bot chat = only things to act on: roundup plan (approve/skip only swap its buttons for a label via
  roundup_plan_label, no new message), drafts that won't auto-post (no good photo, look-alike, limits), errors, TikTok
  "Time to post" reminders, replies to commands. Drafts that will auto-post (will_auto_post / auto_block_reason) are sent
  with disable_notification and vanish once live. No routine "posted"/"removed from queue"/"Telegram slow" notes
  (download note only at 40 fails); sensitive skips go to the run diary (note()); non-permission link-comment
  errors → bot chat. daily_report_due(): ONE report per NY day (state["report_done"]) once yesterday's roundup is
  built/skipped/failed (latest NY noon): post count, breaking, Reels, top 3 (likes+comments+shares), per part
  YouTube/Facebook/TikTok status (platform_text). roundup.py sends no report except in tests.
- Published channel = log of live posts (stats + 🗑 Delete, Reels) + roundup_part_line() at each part's post_at:
  "🎬 Roundup Part n/3 · NAME · 6:25 PM SL · 7:55 AM NY · Facebook · YouTube · TikTok 📥 draft" (links).
- Content channel = ONE roundup zip a day (slides dropped if >48 MB); a part's text + numbered album only when TikTok
  must be posted by hand. mp4s go to the bot chat only when an upload failed / nothing was uploaded, or in tests.
- Times: both_times(t) = "6:25 PM SL · 7:55 AM NY", ny_date_text(t) = "Wed, Nov 18, 2026"; both zones via zoneinfo
  (never a fixed offset). ROUNDUP_TIMES_NY = 07:55/09:55/11:55; there is no SL times setting.
- FB_SOFT_CAP (30): soft_cap_reason() in draft_one (with not_important_reason) — when fb_posts_today (posted +
  queued, NY day) ≥ cap, only BREAKING or importance ≥ FB_SOFT_CAP_MIN_IMPORTANCE (8) stories are made; others are
  skipped quietly (recent_topics "skipped"). AUTO_MAX_PER_DAY 80 stays the absolute limit.

## Design rules (image 1080×1350)
- Brand: black background, white text, red **#CE0000**, Poppins font, logo `assets/logo.png` top-left.
- Footer: "SOURCES: …" + date; small grey photo credit line only for CC BY licences.
- People photos only for people named in the headline (Wikipedia page image, free licence only), up to 3,
  blended side by side (no divider lines). One person + place story → place photo + person in a circle.
- PHOTO ORDER for ALL news (_choose_background): the image must show the ACTION / main thing, not a calm city view.
  1) official_event_photo(): REAL photo of THIS event from OFFICIAL_PHOTO_SOURCES (settings: DVIDS/DoD, Japan MoD/Joint
     Staff, Ukraine SES (DSNS), Ukrainian Armed Forces, IDF, NATO, UN, government press offices; matched by words in
     Commons Artist/Credit(raw, keeps hrefs)/"Files from…" categories, or the Flickr account name). Commons search
     event_query, gsrsort=create_timestamp_desc, upload ≥ news_time − 1 day, DateTimeOriginal not older, licences
     OFFICIAL_LICENSES, half the event words in title/desc/categories; country check = South Asia only (war photos
     name both sides). Flickr official=True (needs FLICKR_API_KEY). Vetted with kind "event: …" (not this event = 0-4).
     bg["event_photo"] = True, no tag.
  2) action_photo(): ACTION FILE PHOTO. Ideas = Gemini "action_subject" (new PROMPT field) first, then ACTION_PHOTO_IDEAS
     (settings, words in headline/subject/event_query); incidents try incident_photo(vetted=False) (that city's police /
     ambulance / fire crews, INCIDENT_PHOTO_IDEAS) first. Per idea "<idea>, <location country>" then "<idea>";
     sources Commons (wiki_search_photo loose=True: half the words in title/desc/categories) → Pexels → Pixabay → Flickr,
     one candidate per search; names_dated_event() (year or month+day AND HARM_WORDS in title/desc) and looks_ai()
     rejected BEFORE the AI sees it; vet kind "file: …"; best score wins (9+ at once, max ACTION_LOOKS=3 looks, 8+ stops
     ideas); none → topic_photo(). bg["file_photo"] = True → render_image draws a "FILE PHOTO" tag top-right level with
     the logo (dark 150-alpha rounded box, red left bar, Poppins SemiBold 22 spaced). With exactly 1 person in the
     headline, steps 1-2 add the person in a circle (inset).
  3) people (person_photo_checked) → scene ideas (not for incidents) → place_photo() → map_card() → incident globe /
     brand. Scene and place photos need only PLACE_MIN_SCORE (5).
  Candidates carry "about" (title/desc/tags, ≤300 chars) for these checks; choose_background() strips it before saving.
- place_photo() = a city view of the location ("<city> skyline/downtown/city center/street/square, <rest>",
  NATURE_WORDS avoided, country-checked). incident_photo(): INCIDENT_PHOTO_IDEAS of THAT city (need= city words,
  EVENT_WORDS in the title rejected), Commons only.
- TOPIC photo (topic_photo(): Gemini "topic_photo" + GENERIC_PHOTO_IDEAS in settings, e.g. rain → "rain street"):
  Pexels → Pixabay → Flickr → Commons Quality images only; countries=AnyOrOwn(story countries) = photo may name no
  country or only the story's; TOPIC_AVOID skips close-ups/events. Used at the end of step 2 (counts as a FILE PHOTO).
  place_ok() always rejects SOUTH_ASIA_PHOTO_WORDS.
- PHOTO_VISION_CHECK (Stage 2): vet(post, photo, kind) → photo_fits() sends a ≤640 px preview to Gemini
  (gemini_json(image=…), VISION_PROMPT scores how well it shows the ACTION ({action} = action_subject/event_query):
  wrong person/extra main person/wrong city/same-name place/car/food/beach/scan/sign/logo/map/drawing/AI image = 0;
  {event_rule} per kind (event: not this event 0-4; file/topic: only a clearly identifiable different event = 0;
  others: any other event = 0); calm skyline/building/landscape for an action story max 5; generic fitting 6–7;
  shows the action 8–10). vet(min_score=…) default PHOTO_MIN_SCORE (7); vet() also drops looks_ai(about). Used for person photos (person_photo_checked, 3 tries),
  event, scene (each source), incident, place and topic photos; score < PHOTO_MIN_SCORE → that URL is excluded and the
  next idea/source is tried, max PHOTO_CHECKS_PER_POST looks, then map → brand. Cache state["photo_memory"]["checked"]
  (url|headline-hash → {s,w,p}, last 500; person checks keyed url|kind; no global exclusion). Not checkable: people photos kept, others dropped; 429 → stop
  for this post (checks_out()). Draft + log channel show photo_score_line ("📷 9/10 Kyiv city", d["photo_line"]).
  GEMINI_GAP_SECONDS between all Gemini calls. NOT_A_PHOTO_TITLE (scans, LCCN, signs…) for Commons, Openverse, Flickr.
  Person pools v2: BAD_PERSON_TITLE (met, swears in, childhood home…), portraits/"only this person" first.
- RUN_ONCE (settings): one-time jobs by id, done ids in state["run_once_done"]: "phototest:…" = photo_test() re-chooses
  photos for the last 10 posts and sends them to the bot chat (nothing published).
- send_draft: if the chosen photo won't download (render_image sets bg["_loaded"]), it re-chooses, then map, then brand
  (never silently the globe). load_photo tries 1280/960 px Wikimedia sizes too.
- Last steps of the chain: place_photo (town → Gemini "nearby_city" → "<State> State Capitol")
  → MAP_CARDS map_card(): MAP_REGIONS (Middle East, Red Sea… no pin), whole countries (map_country_named, highlighted,
  pin only if tiny), US/CA/AU states by name, else Wikipedia geocode (location, nearby_city, its country part, story
  country; nearest_country for coastal points), must fall in the story's country; map_background() draws
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
- photo_quality() checks every Commons/Openverse photo (colour, not B&W/sepia) on a 500 px preview (Wikimedia only
  serves set widths: 250/330/500/960…); a photo that can't be checked is NOT used. Archive scans (LCCN, Bain News…) skipped.
- Flickr (FLICKR_API_KEY, Flickr Pro only; not set → skipped) is used for official event photos, action ideas and
  scene ideas. AI_IMAGE_WORDS / looks_ai() filter every source (Pixabay also isAiGenerated). No AI-generated images.
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
SENSITIVE_FILTER / SENSITIVE_WORDS (suicide, self-harm, overdose, eating disorders… + word forms like -s/-ed): Facebook
age-restricts such posts. Prompt rule + sensitive_words_in() over headline, summary, key_points, hook, location;
one rewrite with SENSITIVE_FIX (leave the cause of death out, never invent one); still there → skipped and noted in
the log channel (log_note).

## Working on this repo
- Owner edits in VS Code and pushes; the bot also commits state every run → always pull/sync first.
- Test changes locally with mocks (no network to news sites needed); keep `python -c "import ast"` clean.
- Owner prefers simple step-by-step English explanations.
