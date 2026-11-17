# 7 Seas News — Automation plan

Status: **Stage 1 done (17 Nov 2026)** — watch 2 days of posts before Stage 2.
**Stage 2 done (17 Nov 2026)** — the AI looks at every photo.
**Stages 3 + 4 done (17 Nov 2026)** — roundup videos, TikTok slides to Telegram, Facebook Reels scheduled; YouTube coded but off until the owner adds the YT_ secrets.

Written 17 Nov 2026 after reading the repo and the bot memory (posts from 12–16 Nov).

Goal: Minura never has to send zips or ask for videos again. Every day the bot itself makes the 3 roundup
videos and posts them to YouTube and Facebook, and sends the TikTok slideshow + captions to Telegram
(owner posts it with a trending track). Also: better news choice and more accurate photos.

Work in 4 stages. Finish, test and push one stage before starting the next. Keep `CLAUDE.md` up to date
after each stage. Keep all new options in `bot/settings.py` with simple comments (owner edits them himself).
Owner prefers simple step-by-step English.

---

## What the data shows (12–16 Nov, 136 published posts)

- Photos: 130 of 136 posts had a photo. Only 6 had none. **The real problem is WRONG or random photos: about 1 in 6
  posts.** Examples:
  - "US visa restrictions block African beauty queens…" → *Nissan Skyline R34 in South Africa* (a car)
  - "British artist Raye leads Grammy nominations" → *Pointe d'Orange (Anse-La-Raye)*, a beach (person search found a place)
  - "US flights return to normal…" → *US-Bangla Airlines aircraft at Dhaka airport* (wrong country, and South Asia)
  - "Texas and Oklahoma execute two men" → *Prison Ship Martyrs Monument* (Brooklyn)
  - "US disrupts North Korean video scheme…" → *Vickers Maxim gun factory, LCCN archive scan* (via Openverse)
  - "Chatham House director discusses Ukraine" → *Christmas at Chatham* (a different place called Chatham)
  - "Canada bars Russia from Junior Worlds in Edmonton" → *Red Deer, Alberta* (wrong city)
  - "Building fire in southern Thailand kills eleven" → *street fast food in Patong*
  - "Democratic lawmakers arrive at COP31 in Turkey" → *Mount Ararat, Armenia*
  - "Media outlets ask readers about funding air traffic control" → *California Senate chamber*
  - "Pope Leo concludes South America tour" → *Pope Leo's childhood home* (shown as a "people" photo)
  - People photos with the wrong main person: Carney story → photo of von der Leyen + Carney + Zelensky;
    Rubio → photo of Canada's foreign minister meeting Rubio; Duffy → Vance swearing in Duffy.
  Cause: every check today is on the photo's **file name / text** only. Nothing ever **looks at the photo**.
- News: some days have weak or repeated stories (Jensen Huang/Nvidia 7 posts in 4 days; FAA ground stop 2×;
  Southeast Asian summit 3×; Washington gunman 2×; Rubio Federalist Society speech 2×; Cape Verde election 2×;
  filler like "Media outlets ask readers about funding…", "Poll explores opinions on…").

---

## Stage 1 — Better news choice ✅ DONE 17 Nov 2026

1. Importance score 1–10 in the Gemini PROMPT; `MIN_IMPORTANCE = 6` (BREAKING always passes).
2. Same-story check with Gemini against posts of the last 36 h (`FOLLOWUP_CHECK`); big new development allowed.
3. `FILLER_TITLE_WORDS` → skipped unless importance ≥ 8.
4. Quiet days: fewer than `MIN_STORIES_PER_DAY` by NY 6 PM → non-focus news needs 2 outlets instead of 3.
5. Feeds: Axios added. CNN RSS feeds are dead (newest items 2022/2023). AP and Reuters have no RSS.

## Stage 2 — Photos that match (the "accuracy" fix) ✅ DONE 17 Nov 2026

1. **Gemini looks at the photo (vision check).** New function `photo_fits(post, photo_url, kind)`:
   download the 500 px preview (`_small()`), send it to Gemini (image part, base64 JPEG) with the headline,
   location, label and the kind ("person: <name>" / "place: <location>" / "scene: <idea>"). Ask JSON:
   `{"score": 0-10, "shows": "<5 words>", "problem": "<short or empty>"}`.
   Rules in the prompt: wrong person or extra main person = 0; wrong country/city = 0; a different place with the
   same name = 0; car/food/beach/holiday/old scan/text sign/logo/map = 0; generic but fitting (e.g. US Capitol
   for a Congress story) = 6–7; the actual place/person = 9–10.
   Accept only `score >= PHOTO_MIN_SCORE` (setting, default 7). Log `shows` + `problem` for rejected photos.
2. Use it everywhere a photo is chosen in `_choose_background()`: person photos (`wiki_person_photo`), event photo,
   incident/place photos, and each scene candidate. If a candidate fails, try the next candidate/idea
   (max `PHOTO_CHECKS_PER_POST`, e.g. 6, to stay inside the Gemini free limit). Cache results by URL in
   `state["photo_memory"]["checked"]` (url → score, keep last 500) so the same photo is never checked twice.
3. People photos: prefer files whose Commons title is **only** that person (cropped / official portrait). Reject
   titles naming another person ("meets", "met", "with", "and", "swears in") unless the other person is also in
   the headline. The vision check also asks "how many people are clearly visible; is <name> the main one?".
4. Openverse results: apply the same title filters as `wiki_search_photo` (LCCN, Bain News, archive, b&w…).
5. South Asia rule for photos too: reject photos whose text names an `EXCLUDE_WORDS` place (Dhaka photo case).
6. If no photo reaches the score → `map_card()` (it is always correct), then the branded design.
7. Telegram/log: show the photo score on the draft ("📷 9/10 Kyiv city") so the owner can see quality.

Test: re-run background choice (mock HTTP + mock Gemini answers) for the wrong examples above → each must be rejected.
Then a live dry run (`DRY_RUN` that renders but doesn't publish) on 10 fresh stories; send the images to Telegram.

## Stage 3 — Daily roundup videos made by the bot

1. **New module `bot/roundup.py`** + new workflow `.github/workflows/roundup.yml` (its own job, `timeout-minutes: 45`,
   installs ffmpeg + fonts, same secrets). Run it from the existing 15-min trigger: `main.py` decides when the
   roundup is due and sets a flag, or `roundup.yml` has its own cron-job.org trigger every 15 min that exits fast
   when nothing is due. Use a separate memory file `state/roundup.json` so the two jobs don't fight over `state.json`.
2. **Collect** (after NY midnight, same moment as `send_day_pack`): the day's published posts from `state["drafts"]`
   (headline, label, bg, sources, created_at). Re-render each post at 1080×1350 with `render_image()` from the saved
   `bg` (`hide_headline=True` for the typing effect, as `make_reel()` does).
3. **Plan** with Gemini: drop duplicates/minor items and stories used the day before, group into 3 parts
   (default WAR & CONFLICT → US NEWS → WORLD NEWS, ~6–14 stories each, 25–35 total), write 2-sentence cover hooks
   (only facts from the headlines), and all titles/captions/tags (rules below).
4. **Approval in Telegram**: plan with buttons ✅ Approve · ✏️ Change · ⏭ Skip today. Reply text = change request
   (Gemini edits the plan, bot sends it again). `ROUNDUP_APPROVAL = "ask"` with `ROUNDUP_AUTO_APPROVE_HOURS = 3`:
   no answer within 3 h → approved automatically. `"auto"` = never ask.
5. **Build** (reuse `make_reel` pieces): per part a 1080×1920 30 fps H.264+AAC video (YouTube + Facebook),
   the 1080×1920 cover, and the TikTok slideshow: 1080×1350 cover + one 1080×1350 slide per story, in story order.
   Max ~1.5 min render per part on Actions.
6. **Post** (Stage 4) and always also send the package zip + DESCRIPTIONS-AND-TIMES.txt to the content channel as a
   backup.
7. Report in Telegram: "✅ Part 1 scheduled YouTube 8:00 AM NY / Facebook ✅ / TikTok slides sent to Telegram", or the error.

### Daily roundup rules (approved by the owner, keep them exactly)
- 3 parts per day; names may change with the day's news. Never "TODAY'S" (posts go out the next US morning);
  use the weekday ("Wednesday's top stories") + date. Weekday is computed, never guessed.
- Design = the owner's manual package, exactly (bot/roundup.py; only the design, never the timing/posting):
  - Cover (every part): same branded globe background as the posts, real logo top-left. Top to bottom: label
    "PART 1/3 · WAR & CONFLICT" → huge "NOV 16" (day number red #CE0000) → "TOP STORIES" (never "TODAY'S", no
    story count) → hook line with a red bar on its left (2 short sentences from the biggest stories of that part,
    wraps to 2 lines) → small "SUNDAY · 2026" (weekday computed from the date). Footer "VERIFIED WORLD NEWS ·
    EVERY DAY" + "SWIPE →". 1080×1920 cover = the 1080×1350 cover in the middle, top filled (25,25,27), bottom
    (8,8,8), seamless. TikTok cover = the 1080×1350 version.
  - Video 1080×1920, 30 fps, H.264 + AAC. Opening: 1080×1920 cover held only 1.3 s with a low boom, then red swipe.
    Each story: post image at y=285; above it a zoom of that story's photo area (post rows 170–900, no logo or text:
    the crop stops above the label/location tag), blurred (r≈34), 45 % darker, feathered into the sharp post over
    ~120 px; below it the post's bottom colour. Headline typed letter by letter in Poppins Bold at the bot's post
    layout (size 80 → down by 4 until ≤4 lines, wrap width 952, line height size×1.2, bottom at y=1238-40 in post
    coords), red cursor, typing clicks, then hold ~2.2 s. Between stories: red full-frame swipe with a white leading
    edge + whoosh. Thin red progress line at the very top edge (y 0–8) across the whole video.
  - Story counter top-right: both numbers always 2 digits ("01 / 06", "05 / 07"), see-through black pill (~55 %
    opacity, rounded ends), white Poppins Bold, NO border/outline.
  - Ending on every part: logo + "FOLLOW FOR MORE" + "VERIFIED WORLD NEWS · EVERY DAY". Never "Follow for Part 2"
    or "next part". Logo = the real 7 Seas News logo (assets/logo.png: 7 mark + "Seas" white + "News" #CE0000).
  - TikTok slides: all 1080×1350 — cover first, then the full post images (with headline) in story order.
  - Design check: run roundup.yml by hand with day "check" (yesterday) or "check 2026-11-16" → Part 1 video, the
    1080×1920 cover and the first 3 TikTok slides go to the bot chat; nothing uploaded or saved.
- Text: headlines exactly as published, no added claims. Hashtags and tags always lowercase.
  TikTok title ≤90 chars; caption = hook, "Part n/3", "Follow 7 Seas News for more 🔔", a question, hashtags incl.
  #7seasnews #newstok. YouTube title ≤100 chars with date + "(Part n/3) #shorts"; description lists headlines,
  "Real News. No Noise.", hashtags; lowercase tags list. Facebook: short hook + follow line, 3–5 hashtags.
- Times: 8 AM / 10 AM / 12 PM New York (= 6:30 / 8:30 / 10:30 PM Sri Lanka in EST).
  `ROUNDUP_TIMES_NY = ["08:00", "10:00", "12:00"]`. If approval/rendering is late, shift all three by the same amount.
- Music: `ROUNDUP_MUSIC`: "off" (only the synthesized sounds, default) or a folder `assets/music/` of royalty-free
  tracks the owner adds (low volume under the sounds).

## Stage 4 — Upload to the platforms

Settings `ROUNDUP_YOUTUBE`, `ROUNDUP_FACEBOOK`, `ROUNDUP_TIKTOK`. Owner does the account steps (short how-to in README).

1. **YouTube (fully automatic).** Data API v3 `videos.insert` (resumable) with `privacyStatus="private"` +
   `publishAt` = scheduled; `selfDeclaredMadeForKids=false`, `containsSyntheticMedia` only if a slide uses an AI
   image, `defaultLanguage/defaultAudioLanguage="en-US"`, `categoryId="25"`; then `thumbnails.set` with the cover.
   Secrets `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`. Owner setup: Google Cloud project → enable
   YouTube Data API v3 → OAuth consent screen → **publish the app "In production"** (Testing = refresh token dies
   after 7 days) → Desktop OAuth client → one-time helper `tools/youtube_token.py`. If Google keeps uploads locked
   private, the project needs YouTube's API audit form.
2. **Facebook (fully automatic).** Reel via `video_reels` (start → rupload → finish). Try `video_state=SCHEDULED` +
   `scheduled_publish_time`; if rejected, the bot publishes it itself at the right time with `video_state=PUBLISHED`.
   Reels API limit 30 per 24 h (single-story Reels + 3 roundups).
3. **TikTok — DECIDED (17 Nov): photo slideshow posted by the owner by hand. NO TikTok API.** Per part, to the content
   channel (`state["tiktok_channel"]`, else bot chat):
   a) text: "📲 TikTok Part n/3 · post at 8:00 AM NY (6:30 PM SL) · <NY date>", then title and caption each in `<code>`;
   b) MOBILE FIRST: slides in order (cover first, 1080×1350) as Telegram photos in albums of max 10 (`sendMediaGroup`),
      each captioned "1/14 · cover", "2/14 · Ukraine strikes…";
   c) one zip of the full-quality slides.
   `TIKTOK_SLIDES_AS = "photos"` (default) or "files". README: how to save a Telegram album on Android and iPhone.
   Sent right after approval; at each posting time "⏰ Time to post TikTok Part n/3" with ✅ Posted button.
   Checklist reminds: TikTok "AI-generated content" label only if a slide uses an AI image.
4. Everything that fails: retry once, then a Telegram message with the reason (backup zip already sent).

---

## Order and checks
1. Stage 1 → push → watch 2 days of posts.
2. Stage 2 → push → watch 2 days (look at the 📷 scores).
3. Stage 3 with uploads OFF (only sends the package + plan to Telegram) → owner compares with the manual package.
4. Stage 4 one platform at a time: TikTok slides to Telegram → YouTube → Facebook.

Never print or commit secrets. Keep `python -c "import ast; ast.parse(open('bot/main.py').read())"` clean.
