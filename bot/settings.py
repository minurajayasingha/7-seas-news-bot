# =============================================================================
# 7 SEAS NEWS BOT — SETTINGS
# This is the only file you normally need to edit.
# After editing: Commit → Sync Changes. The bot uses the new settings on its next run.
# =============================================================================

BRAND_NAME = "7 Seas News"
BRAND_HASHTAG = "#7SeasNews"

# ---------- Colors (R, G, B) ----------
RED = (206, 0, 0)          # #CE0000  (labels, lines, logo "News")
BLACK = (8, 8, 9)
CHARCOAL = (26, 26, 29)
WHITE = (255, 255, 255)
SOFT = (205, 205, 210)     # small grey text

# ---------- Auto-publish (no tapping needed) ----------
AUTO_PUBLISH = True          # True = verified news (MIN_SOURCES outlets) is posted to Facebook by itself.
                             # Telegram shows "🤖 Auto-posting" (↩️ Cancel to stop it), then the log channel gets
                             # the post with a 🗑 Delete button. False = old way: you tap 🚀 Post now / 🕒 Queue.
AUTO_MAX_PER_DAY = 80        # ABSOLUTE max auto posts per New York day (more → normal drafts for you to choose).
                             # Send /stats week to see posts per day vs likes/reach per post and pick the best.
FB_SOFT_CAP = 30             # soft limit: after this many Facebook posts in a New York day, only BREAKING news and
                             # stories the AI rates FB_SOFT_CAP_MIN_IMPORTANCE or more are still posted; smaller
                             # stories are skipped quietly (no draft in Telegram). 0 = no soft limit.
FB_SOFT_CAP_MIN_IMPORTANCE = 8
AUTO_MIN_GAP_MINUTES = 0     # at least this long between auto posts (BREAKING news doesn't wait)
AUTO_NEEDS_PHOTO = True      # True = only news with a real photo is auto-posted; the rest waits in Telegram for you
                             # (reply with a photo, or 🚀 Post now / ❌ Skip). False = posted with the globe/brand design
AUTO_REELS = "breaking"      # "breaking" = only BREAKING (emergency) news gets an automatic Reel, max REELS_PER_DAY (3)
                             # "more" = every BREAKING post + other posts with a real photo (2 kept free for breaking)
                             # "off" = Reels only when you tap 🎬 Reel
BREAKING_WITHOUT_PHOTO = True   # True = BREAKING news is auto-posted even with no real photo (our branded cover)
SKIP_LOOKALIKES = False      # False = news that looks like an earlier post is posted anyway (the log channel says
                             #         "⚠️ Looks like an earlier post" and has 🗑 Delete if you don't want it).
                             # True = old way: look-alikes wait in Telegram for you

# ---------- Space out posts (posts close together get less reach) ----------
MIN_MINUTES_BETWEEN_POSTS = 0    # every post (🚀 Post now, 🕒 Queue slots, auto) waits until this long after the last
                                 # one; Telegram tells you the new time. A waiting post has ⚡ Post now anyway.
BREAKING_SKIPS_GAP = True        # BREAKING news doesn't wait (goes out at once, the others move back)
AUTO_MAX_WAITING = 10            # max auto posts waiting for their turn; more news → normal drafts for you

# ---------- How many posts ----------
DRAFTS_PER_RUN = 5           # new posts sent to Telegram each time it looks for news
DRAFT_EVERY_MINUTES = 15     # how often it looks for news (15 = every run of the bot)

LISTEN_MINUTES = 12          # after its work, each run stays online this long so button taps and replies
                             # are handled within seconds (keep below 14 because a new run starts every 15 min; 0 = off)

# Posting times for the 🕒 Queue button (New York time). One queued post per slot.
SLOT_TIMEZONE = "America/New_York"
POST_SLOTS = ["07:00", "09:30", "12:00", "15:00", "18:00", "20:30"]

# ---------- What news to pick ----------
MIN_SOURCES = 2              # a story must be reported by at least this many different outlets
MAX_AGE_HOURS = 6            # ignore articles older than this
FRESH_HOURS = 3              # the newest report of a story must be within this many hours
BREAKING_MAX_HOURS = 3       # "BREAKING" only if first reported within this time

# Main focus: stories containing any of these words get priority.
# Other stories are only used if they are very big (OTHER_NEWS_MIN_SOURCES outlets).
FOCUS_ONLY = True
OTHER_NEWS_MIN_SOURCES = 3
US_WORDS = [
    "u.s.", "usa", "united states", "washington", "white house", "biden", "harris", "newsom",
    "congress", "senate", "house speaker", "pentagon", "supreme court", "republican",
    "democrat", "gop", "trump", "vance", "rubio", "hegseth", "governor", "election",
    "midterm", "ballot", "fbi", "cia",
]
WAR_WORDS = [
    "war", "attack", "strike", "airstrike", "missile", "drone", "bomb", "bombing",
    "explosion", "shooting", "gunman", "kill", "dead", "troops", "military", "army",
    "invasion", "ceasefire", "nuclear", "hostage", "terror", "nato", "ukraine", "ukrainian", "russia",
    "kyiv", "moscow", "tehran", "jerusalem", "beirut",
    "israel", "gaza", "hamas", "hezbollah", "iran", "china", "taiwan", "north korea",
    "venezuela", "syria", "yemen", "houthi", "red sea",
]

# ---------- Only important news (no filler, no repeats) ----------
MIN_IMPORTANCE = 6           # the AI rates every story 1-10 for a US-first world-news audience
                             # (10 = war / major attack / election result / leader change; 1 = poll, opinion,
                             # "X discusses", media-about-media, gossip). Below this → skipped. BREAKING always passes.
FILLER_TITLE_WORDS = [       # stories whose headline has one of these are skipped unless importance is 8+
    "poll finds", "poll shows", "new poll", "survey", "asks readers", "ask readers", "discusses", "explores",
    "opinions on", "what to know", "explainer", "explained",
]                            # (not plain "poll": that would also catch "polls close in Virginia")
FILLER_MIN_IMPORTANCE = 8
FOLLOWUP_CHECK = True        # True = before writing a post, the AI checks it isn't the same story as one posted in the
                             # last FOLLOWUP_HOURS. Same story is only posted again with a big new development
                             # (e.g. "resigns" after "faces scandal"). One small AI call, only when headlines look alike.
FOLLOWUP_HOURS = 36
SKIPPED_TOPIC_HOURS = 12     # a story skipped as minor/repeated isn't looked at again for this long
# Quiet days: if fewer than MIN_STORIES_PER_DAY posts by QUIET_DAY_HOUR_NY (New York), other world news
# (outside the US/war focus) needs only QUIET_DAY_MIN_SOURCES outlets instead of OTHER_NEWS_MIN_SOURCES.
# Still 2+ outlets and still the importance rule: better a few good posts than filler.
MIN_STORIES_PER_DAY = 15
QUIET_DAY_HOUR_NY = 18       # 18 = 6 PM New York
QUIET_DAY_MIN_SOURCES = 2

# Topics to always skip (South Asia). Matched against headline + summary.
EXCLUDE_WORDS = [
    "india", "indian", "pakistan", "pakistani", "sri lanka", "sri lankan",
    "bangladesh", "nepal", "bhutan", "maldives", "modi", "new delhi", "delhi",
    "mumbai", "karachi", "lahore", "islamabad", "colombo", "dhaka", "kathmandu",
]
# Skip non-news items
SKIP_TITLE_WORDS = [
    "live:", "live updates", "as it happened", "quiz", "opinion", "podcast",
    "watch:", "video:", "in pictures", "newsletter", "crossword", "review:",
]

# ---------- Neutral headlines ----------
# If the AI's headline or summary has one of these words, it must rewrite it once; if it still has one,
# the story is skipped. Write every form you want to block (e.g. "slam", "slams", "slammed").
BANNED_HEADLINE_WORDS = [
    "vulnerability", "vulnerable", "crack", "cracks", "cracked", "slam", "slams", "slammed",
    "destroy", "destroys", "destroyed", "blast", "blasts", "blasted", "humiliate", "humiliates", "humiliated",
    "humiliating", "disaster for", "win for", "victory for", "blow to", "blow for", "crushing", "crushes",
    "stunning", "stuns", "shocking", "shock", "explosive", "bombshell", "rips", "torches", "eviscerates",
    "meltdown", "chaos", "embarrassing", "fury", "furious", "outrage", "red wall", "blue wall", "doubles down",
    "backfires", "epic", "massive", "brutal", "savage", "owns", "claps back", "hits back", "mocks",
]

# ---------- Sensitive topics (Facebook hides / age-restricts these and counts them against the Page) ----------
SENSITIVE_FILTER = True      # True = headline, summary, "What we know" points and image text are checked for these;
                             # Gemini rewrites once without them; still there → story skipped (noted in the log channel)
SENSITIVE_WORDS = [
    "suicide", "suicidal", "killed himself", "killed herself", "took his own life", "took her own life",
    "self-harm", "self harm", "self-inflicted", "overdose", "anorexia", "bulimia", "eating disorder",
]

# ---------- Caption ----------
SHOW_READ_MORE_LINK = True   # include the original article link in the Facebook caption
COMMENT_KEY_FACTS = True     # the link comment also lists 2–3 short facts (not for BREAKING: those are in the caption)
LINK_IN_FIRST_COMMENT = True # True = no URL in the caption ("🔗 Source in the comments 👇"); the link goes in the
                             #        Page's first comment instead (Facebook shows link posts to fewer people).
                             # False = old way: "📖 Read more: <link>" in the caption. Needs pages_manage_engagement.
SHARE_TO_STORY = "breaking"  # Facebook Story: "breaking" = only BREAKING news, "all" = every post, "off" = never
FOLLOW_LINE = "Follow 7 Seas News for US & world news every day 🇺🇸🌍"   # in every caption, before the hashtags ("" = none)
TIKTOK_HASHTAGS = "#news #worldnews #fyp"   # added to the caption sent to your TikTok channel (/tiktok)
SEND_EACH_POST_TO_CONTENT_CHANNEL = False   # True = also send every post one by one to the content channel (/content).
                                            # False = the content channel only gets the 3 TikTok roundup parts + backup zip
DAY_PACK_SIZE = "9x16"       # /day (only when you ask; no automatic daily pack): images in the zip,
                             # "9x16" = TikTok size (1080x1920), "4x5" = the post itself (1080x1350)

# Question at the end of the post (to get comments):
#   "always"    = every post
#   "sometimes" = only when the story is a real debate, never on deaths/attacks/tragedies (recommended)
#   "never"     = no questions
ASK_QUESTION = "sometimes"

# ---------- Single-story Reels (🎬 Reel button) ----------
REELS_ENABLED = True         # True = drafts get a 🎬 Reel button: publishes the post AND a short Reel of it
REELS_PER_DAY = 3            # max single-story Reels per New York day, the 🎬 Reel button included (more → post only).
                             # The 3 daily roundup videos don't count here.
REEL_SECONDS = 10            # length of each Reel (typing headline → hold → "Follow for more" end card)
REELS_ONLY_GOOD_PHOTOS = True   # True = 🎬 Reel button only on drafts with a real photo (people/place),
                                #        not on the plain brand / globe designs
REEL_TYPING_SOUND = True     # keyboard click for every letter while the headline types
REEL_BREAKING_SOUND = True   # BREAKING posts start with a short news-alert sound (made by the bot, no copyright)
REEL_SOUND_VOLUME = 0.8      # 0.0 (silent) … 1.0 (full)
REEL_HASHTAGS = "#news #worldnews"   # extra lowercase hashtags for Reel captions (3–5 in total)

# ---------- Post stats (likes, comments, shares) ----------
STATS_EVERY_MINUTES = 60     # how often the numbers under published posts are refreshed
STATS_DAYS = 3               # keep updating a post's numbers for this many days after publishing

# ---------- Photo variety ----------
USE_OPENVERSE = True         # free photo search (Flickr + Wikimedia + more, free licences only, credit kept). No key.
INCIDENT_PLACE_PHOTO = True  # shootings/crashes/disasters: use a photo of the PLACE (city/landmark) instead of the globe
                             # design. Never a photo of an older, different event.
MAP_CARDS = True             # no photo at all → the bot draws a news map: the country/state, borders and a red pin on
                             # the place (Natural Earth map data, public domain). These are auto-posted too.
                             # Works for cities, states, whole countries and regions ("Middle East", "Red Sea"…).
# ---------- Photo ORDER for every story (the image must show the ACTION / main thing, not a calm city view) ----------
# 1) A REAL photo of this event from an OFFICIAL free source (Wikimedia Commons uploads since the news started, or
#    Flickr uploads from these accounts). The AI must confirm it shows this event.
# 2) An ACTION FILE PHOTO of the story's main thing (fighter jets, rescuers at a collapsed building, firefighters…),
#    from the story's country when possible. The image gets a small "FILE PHOTO" tag (top right).
#    A file photo whose title names another dated event (e.g. "2023 Turkey earthquake rescue") is never used.
# 3) Only then: the person's photo, a place/city view, the news map.
# No AI-generated images, ever.
#
# Official sources: words that must be in the photo's author / credit / source (Commons) or the Flickr account name.
OFFICIAL_PHOTO_SOURCES = {
    "DVIDS / US Department of Defense": ["dvidshub", "dvids", "defense.gov", "department of defense", "army.mil",
                                         "navy.mil", "af.mil", "marines.mil", "u.s. army", "u.s. navy", "u.s. air force",
                                         "u.s. marine corps", "u.s. coast guard", "national guard", "spacecom"],
    "Japan Ministry of Defense / Joint Staff": ["mod.go.jp", "ministry of defense (japan)", "japan ministry of defense",
                                                "joint staff office", "防衛省", "統合幕僚監部"],
    "Ukraine State Emergency Service": ["dsns.gov.ua", "state emergency service of ukraine", "дснс"],
    "Ukrainian Armed Forces": ["mil.gov.ua", "armed forces of ukraine", "general staff of the armed forces",
                               "ministry of defence of ukraine", "ministry of defense of ukraine", "зсу"],
    "Israel Defense Forces": ["idf spokesperson", "israel defense forces", "idf.il"],
    "NATO": ["nato.int", "nato photo", "north atlantic treaty organization"],
    "United Nations": ["un photo", "united nations photo", "un.org", "unicef", "unhcr", "un ocha"],
    "Government press offices": ["president.gov.ua", "office of the president of ukraine", "kremlin.ru",
                                 "whitehouse.gov", "official white house photo", "fema.gov", "fema", "state.gov",
                                 "gov.uk", "number 10", "bundesregierung", "elysee.fr", "gov.il", "gpo israel"],
}
# Action file photo ideas: if the headline (or the AI's "action_subject") has a word on the left, these ideas are
# searched (after the AI's own action_subject). 2-5 words each, a thing or an activity, never a named event.
ACTION_PHOTO_IDEAS = {
    ("jet", "jets", "fighter", "fighters", "scramble", "scrambles", "scrambled", "airspace", "warplane", "warplanes",
     "bomber", "bombers", "air force", "f-15", "f-16", "f-35"):
        ["fighter jet", "fighter jets in flight", "fighter jet takeoff", "military aircraft intercept"],
    ("navy", "naval", "warship", "warships", "destroyer", "frigate", "aircraft carrier", "submarine", "fleet"):
        ["warship at sea", "navy destroyer", "aircraft carrier", "naval ship"],
    ("troops", "soldiers", "army", "military", "infantry", "frontline", "front line", "offensive"):
        ["soldiers", "troops on patrol", "army soldiers training", "military vehicles"],
    ("tank", "tanks", "armored", "armoured"): ["main battle tank", "tank", "armored vehicle"],
    ("missile", "missiles", "ballistic", "air defense", "air defence", "interceptor", "patriot"):
        ["missile launch", "air defense system", "missile test launch"],
    ("drone", "drones", "uav"): ["military drone", "drone in flight"],
    ("earthquake", "quake", "collapse", "collapsed", "rubble", "landslide"):
        ["search and rescue team", "rescue workers rubble", "collapsed building rescue", "urban search and rescue"],
    ("fire", "fires", "blaze", "wildfire", "wildfires", "burning", "bushfire"):
        ["firefighters fighting fire", "firefighters at work", "fire truck", "wildfire firefighters"],
    ("flood", "floods", "flooding", "flooded"): ["flood rescue boat", "flooded street", "rescuers in flood water"],
    ("storm", "hurricane", "typhoon", "cyclone", "tornado"): ["emergency crews storm", "hurricane clouds", "storm clouds"],
    ("explosion", "blast", "exploded", "bomb", "bombing", "airstrike", "airstrikes", "shelling", "strike", "strikes"):
        ["rescue workers", "emergency responders", "firefighters at work", "ambulance crew"],
    ("shooting", "shot", "gunman", "gunmen", "gunfire", "stabbing", "hostage"):
        ["police officers at work", "police cordon", "ambulance crew", "police car"],
    ("protest", "protests", "protesters", "protestors", "demonstration", "demonstrators"):
        ["protest crowd with flags", "demonstrators with flags", "protest march"],
    ("court", "judge", "judges", "trial", "ruling", "verdict", "supreme court", "lawsuit", "jury"):
        ["courtroom", "judge gavel", "court building"],
    ("election", "elections", "vote", "voting", "voters", "ballot", "polls", "referendum"):
        ["voters at polling station", "ballot box", "voting booth"],
    ("economy", "inflation", "tariff", "tariffs", "stocks", "stock market", "trade", "recession", "interest rates"):
        ["stock exchange trading floor", "container port cranes", "shipping containers", "supermarket shoppers"],
}

# Shootings, crashes, fires… : first try a photo of that city's emergency services (a "file photo"), then a city view.
# Photos whose title mentions another event (shooting, crash, memorial…) are never used.
INCIDENT_PHOTO_IDEAS = {
    ("shooting", "shot", "gunman", "gunmen", "gunfire", "stabbing", "stabbed", "hostage", "killed", "kills", "attack"):
        ["police car", "police vehicle", "police line"],
    ("crash", "collision", "derail", "derailed", "plane", "helicopter"): ["ambulance", "police car"],
    ("fire", "blaze", "wildfire", "burned"): ["fire engine", "fire truck", "firefighters"],
    ("explosion", "blast", "bomb", "bombing"): ["police car", "ambulance"],
    ("flood", "storm", "hurricane", "tornado", "earthquake"): ["ambulance", "fire engine"],
}
# No photo of the place/people? A simple photo of the TOPIC (any country, never another event):
# "rain" news → a rain photo, airport news → an airport photo. Words on the left are looked for in the headline.
# The AI also suggests one idea per story ("topic_photo"). Bombings/attacks get the news map instead.
GENERIC_PHOTO_IDEAS = {
    ("rain", "rains", "rainfall", "downpour", "rainstorm", "monsoon"): ["rain street", "rain umbrella", "rain window", "heavy rain"],
    ("flood", "floods", "flooding", "flooded", "floodwaters"): ["flooded street", "flooding", "sandbags"],
    ("storm", "storms", "hurricane", "hurricanes", "typhoon", "cyclone", "tornado", "tornadoes", "lightning"):
        ["storm clouds", "lightning", "hurricane", "tornado"],
    ("snow", "snowfall", "snowstorm", "snowstorms", "blizzard", "winter storm", "ice storm", "freezing"):
        ["snow street", "snowstorm", "snow plow", "snowfall"],
    ("heat", "heatwave", "heat wave", "drought"): ["heat wave", "drought cracked earth", "thermometer heat"],
    ("wildfire", "wildfires", "bushfire", "forest fire"): ["wildfire smoke", "firefighters", "fire truck"],
    ("earthquake", "quake", "tsunami", "volcano", "eruption"): ["seismograph", "rescue team", "volcano"],
    ("flight", "flights", "airline", "airlines", "airport", "faa", "air traffic", "plane", "aircraft", "jet"):
        ["airport terminal", "airplane taking off", "air traffic control tower", "airport departures board"],
    ("oil", "opec", "gasoline", "gas prices", "fuel", "pipeline"): ["oil pumpjack", "oil refinery", "gas station"],
    ("nuclear", "uranium", "reactor"): ["nuclear power plant", "cooling towers"],
    ("vote", "votes", "voting", "voters", "ballot", "election", "elections", "polls", "referendum"):
        ["ballot box", "voting booth", "polling station", "I voted sticker"],
    ("court", "judge", "trial", "ruling", "lawsuit", "verdict", "sentenced", "jury"):
        ["judge gavel", "courtroom", "scales of justice"],
    ("stock", "stocks", "stock market", "dow", "nasdaq", "wall street"): ["stock market screen", "stock exchange"],
    ("tariff", "tariffs", "trade", "exports", "imports"): ["shipping containers", "container ship", "cargo port"],
    ("police", "arrest", "arrested", "shooting", "gunman", "stabbing", "suspect", "charged"):
        ["police car lights", "police lights", "police tape"],
    ("drone", "drones"): ["military drone", "drone flying"],
    ("hospital", "health", "virus", "outbreak", "vaccine", "disease", "measles", "flu", "doctors"):
        ["hospital corridor", "ambulance", "vaccine vial", "doctor stethoscope"],
    ("ship", "vessel", "tanker", "cargo", "navy", "warship", "coast guard"): ["cargo ship", "oil tanker", "warship"],
    ("train", "rail", "railway", "derail", "derailed", "subway"): ["train tracks", "freight train", "railway station"],
    ("cyber", "hack", "hacker", "hackers", "outage", "microsoft", "google", "apple", "meta", "ai", "tech"):
        ["computer code screen", "server room", "data center", "smartphone"],
    ("school", "schools", "university", "universities", "students", "college"): ["university campus", "classroom"],
    ("rocket", "spacex", "nasa", "space station", "astronaut", "satellite", "starship"): ["rocket launch", "space rocket", "night sky stars"],
    ("food", "grocery", "groceries", "prices", "inflation", "cost of living"): ["supermarket shelves", "grocery store", "shopping cart"],
    ("jobs", "unemployment", "workers", "layoffs", "labor union"): ["factory workers", "help wanted sign", "office building"],
    ("housing", "mortgage", "rent", "homes"): ["houses for sale sign", "suburban houses", "apartment buildings"],
    ("crypto", "bitcoin"): ["bitcoin coins", "cryptocurrency"],
    ("prison", "inmate", "jail", "prisoner", "prisoners"): ["prison bars", "prison fence"],
    ("farm", "farmers", "crops", "harvest"): ["farm field", "tractor", "wheat field"],
    ("electric vehicle", "electric vehicles", "tesla", "automaker", "carmakers"): ["car factory", "electric car charging", "traffic jam"],
}
STRICT_PHOTO_MATCH = True    # True = a place photo must clearly be from the story's country (checked in the photo's
                             # name, description and categories); photos naming another country are rejected.
                             # No safe photo → the branded globe design instead of a random photo.
PHOTO_VISION_CHECK = True    # True = the AI LOOKS at every photo before it is used (wrong person, wrong city, a car,
                             # a beach, an old scan… → rejected) and the next photo idea is tried. The draft shows the
                             # score, e.g. "📷 9/10 Kyiv city". No photo good enough → the news map (always correct).
PHOTO_MIN_SCORE = 7          # 0-10: event and action photos below this score are not used
                             # (8-10 = shows the story's action, e.g. jets for a jets story; 10 = this exact event)
PLACE_MIN_SCORE = 5          # the last-resort place/city view may score lower (a calm city view for an action story
                             # gets at most 5 from the AI), so it is still better than the plain map
PHOTO_CHECKS_PER_POST = 8    # max photos the AI looks at per post (keeps inside the free Gemini limit)
GEMINI_GAP_SECONDS = 4       # wait at least this long between AI calls (free limit is about 15 per minute)
PHOTOS_PER_PERSON = 12       # how many different free photos the bot collects per person (e.g. Trump)
NO_REPEAT_PHOTOS = 40        # a photo is not used again until this many other photos were used
PHOTO_POOL_DAYS = 7          # refresh each person's photo collection after this many days
# Better photo searches for some places: "what Gemini asks": ("what to search", [words the photo name must NOT have])
PHOTO_SEARCH_FIX = {
    "white house": ("White House Washington", ["moscow", "russia", "russian", "minsk", "canyon", "ruin", "arizona"]),
    "capitol": ("United States Capitol", ["state capitol", "texas", "havana", "seattle", "denver"]),
}                                    # "Capitol Hill" counts as "capitol" (the US Capitol, never Seattle's Capitol Hill)

# Photo ideas per topic. If a headline has one of the words on the left, the bot rotates through
# these photo ideas (plus the AI's own ideas), so stories about the same topic look different.
# Add or change ideas freely: 2-4 words each, a place or a thing (never a person).
TOPIC_PHOTO_IDEAS = {
    ("democrat", "dnc", "schumer", "jeffries"): [
        "Democratic National Convention", "US Capitol dome", "Senate chamber, United States Capitol",
        "House chamber, United States Capitol", "Capitol Hill", "United States Capitol rotunda",
        "Capitol at night", "National Mall, Washington", "voting booth, United States", "Library of Congress"],
    ("republican", "gop", "rnc", "maga"): [
        "Republican National Convention", "US Capitol dome", "Senate chamber, United States Capitol",
        "House chamber, United States Capitol", "Capitol Hill", "United States Capitol rotunda",
        "Capitol at night", "National Mall, Washington", "voting booth, United States", "Library of Congress"],
    ("congress", "senate", "senator", "lawmaker", "shutdown", "speaker"): [
        "US Capitol dome", "Senate chamber, United States Capitol", "House chamber, United States Capitol",
        "Capitol Hill", "United States Capitol rotunda", "Capitol at night", "Russell Senate Office Building",
        "Library of Congress", "US Capitol west front", "Capitol Reflecting Pool"],
    ("election", "voter", "ballot", "midterm", "primaries"): [
        "voting booth, United States", "ballot box, United States", "polling place, United States",
        "early voting, United States", "I voted sticker", "vote counting, United States",
        "US Capitol dome", "absentee ballot"],
    ("supreme court", "judge", "justices", "ruling", "lawsuit", "indicted", "indictment"): [
        "Supreme Court of the United States", "Supreme Court building, Washington", "Robert F. Kennedy Department of Justice Building",
        "E. Barrett Prettyman United States Courthouse", "federal courthouse, United States",
        "Supreme Court, Washington DC", "Thurgood Marshall Federal Judiciary Building"],
    ("tariff", "trade war", "economy", "inflation", "stock market", "wall street", "federal reserve", "prices"): [
        "Port of Long Beach", "Port of Los Angeles", "container ship", "shipping containers, port",
        "New York Stock Exchange", "Wall Street, New York", "Marriner S. Eccles Federal Reserve Board Building",
        "Treasury Building, Washington", "factory assembly line", "Port of Savannah"],
    ("execute", "execution", "death row", "death penalty", "inmate"): [
        "federal courthouse, United States", "Supreme Court of the United States", "courthouse, United States",
        "Robert F. Kennedy Department of Justice Building", "Texas State Capitol", "Oklahoma State Capitol"],
    ("crypto", "bitcoin", "hacker", "hacking", "cyber", "scam", "fraud", "money laundering"): [
        "J. Edgar Hoover Building", "Robert F. Kennedy Department of Justice Building", "data center servers",
        "server room", "FBI headquarters, Washington", "Treasury Building, Washington"],
    ("immigra", "migrant", "border", "deport", "asylum"): [
        "Mexico-United States border", "border wall, Mexico United States", "San Ysidro Port of Entry",
        "Statue of Liberty", "Ellis Island", "Rio Grande, Texas", "border patrol, Texas", "US Customs and Border Protection"],
    ("pentagon", "military", "troops", "hegseth", "air strike", "airstrike", "navy"): [
        "Pentagon, Arlington", "aircraft carrier, United States Navy", "destroyer, United States Navy",
        "Arlington National Cemetery", "F-35 Lightning", "USS Gerald R. Ford", "US Army soldiers", "Fort Bragg"],
    ("white house", "oval office", "executive order"): [
        "White House, Washington", "Oval Office", "Air Force One", "Marine One",
        "Eisenhower Executive Office Building", "White House south lawn", "White House north portico",
        "Lafayette Square, Washington", "Pennsylvania Avenue, Washington"],
    ("ukrain", "kyiv", "zelensk", "putin", "kremlin", "moscow"): [
        "Kyiv", "Moscow Kremlin", "Red Square, Moscow", "Maidan Nezalezhnosti", "Saint Sophia Cathedral, Kyiv",
        "Verkhovna Rada", "Kharkiv", "Saint Basil's Cathedral", "Mother Ukraine", "Odesa"],
    ("israel", "gaza", "hamas", "netanyahu", "jerusalem", "west bank", "hezbollah"): [
        "Jerusalem", "Tel Aviv skyline", "Knesset", "Gaza City", "Western Wall", "Dome of the Rock",
        "Gaza Strip", "Haifa", "Old City, Jerusalem", "Tower of David"],
    ("iran", "tehran", "khamenei"): [
        "Tehran", "Azadi Tower", "Milad Tower", "Tehran skyline", "Isfahan", "Naqsh-e Jahan Square"],
    ("united nations", "nato", "g7", "g20", "security council"): [
        "United Nations Headquarters, New York", "United Nations Security Council",
        "United Nations General Assembly Hall", "NATO headquarters, Brussels", "Palais des Nations, Geneva"],
}

# ---------- Expiry ----------
PENDING_EXPIRE_HOURS = 8     # unanswered posts are removed after this
QUEUE_EXPIRE_HOURS = 12      # a queued post is removed (and you are told) when its NEWS is older than this.
                             # Waiting in line alone never removes a post.

# ---------- News sources (RSS) ----------
FEEDS = {
    "BBC": [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
    ],
    "NPR": [
        "https://feeds.npr.org/1014/rss.xml",   # Politics
        "https://feeds.npr.org/1004/rss.xml",   # World
    ],
    "Al Jazeera": ["https://www.aljazeera.com/xml/rss/all.xml"],
    "The Guardian": [
        "https://www.theguardian.com/us-news/us-politics/rss",
        "https://www.theguardian.com/world/rss",
    ],
    "Politico": ["https://rss.politico.com/politics-news.xml"],
    "CBS News": [
        "https://www.cbsnews.com/latest/rss/politics",
        "https://www.cbsnews.com/latest/rss/world",
    ],
    "ABC News": [
        "https://feeds.abcnews.com/abcnews/politicsheadlines",
        "https://feeds.abcnews.com/abcnews/internationalheadlines",
    ],
    "DW": ["https://rss.dw.com/rdf/rss-en-world"],
    "France 24": ["https://www.france24.com/en/rss"],
    "The Hill": ["https://thehill.com/homenews/feed/"],
    # 24/7 outlets, so news keeps coming while America sleeps (Sri Lanka daytime)
    "Sky News": [
        "https://feeds.skynews.com/feeds/rss/world.xml",
        "https://feeds.skynews.com/feeds/rss/us.xml",
    ],
    "NBC News": [
        "https://feeds.nbcnews.com/nbcnews/public/news",
        "https://feeds.nbcnews.com/nbcnews/public/politics",
    ],
    "Fox News": [
        "https://moxie.foxnews.com/google-publisher/politics.xml",
        "https://moxie.foxnews.com/google-publisher/world.xml",
    ],
    "New York Times": [
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
    ],
    "Washington Post": [
        "https://feeds.washingtonpost.com/rss/world",
        "https://feeds.washingtonpost.com/rss/politics",
    ],
    "The Independent": [
        "https://www.independent.co.uk/news/world/rss",
        "https://www.independent.co.uk/news/world/americas/us-politics/rss",
    ],
    "Euronews": ["https://www.euronews.com/rss?level=theme&name=news"],
    "Times of Israel": ["https://www.timesofisrael.com/feed/"],
    "Kyiv Independent": ["https://kyivindependent.com/news-archive/rss/"],
    "Newsweek": ["https://www.newsweek.com/rss"],
    "Washington Examiner": ["https://www.washingtonexaminer.com/feed/"],
    "UPI": ["https://rss.upi.com/news/top_news.rss"],
    "Axios": ["https://api.axios.com/feed/"],   # (CNN's RSS feeds are dead since 2023: not used)
}

# ---------- Daily roundup videos (3 parts, made by the bot after midnight New York) ----------
# After NY midnight the bot sends you the PLAN in Telegram (✅ Approve · ✏️ Change · ⏭ Skip today).
# Reply to the plan with words to change it ("move the Gaza story to Part 1"). Then it makes the 3 videos,
# uploads them (scheduled) and sends the TikTok slides + captions to your content channel (/content).
# When it is scheduled you get ONE daily report in the bot chat (yesterday's posts, top 3, roundup status), and
# at each posting time the published-posts channel gets one line with that part's Facebook + YouTube links.
ROUNDUP_ENABLED = True
ROUNDUP_START_DAY = "2026-11-17"     # first New York day that gets real roundup videos (older days: none)
ROUNDUP_APPROVAL = "ask"             # "ask" = send the plan and wait for you; "auto" = never ask
ROUNDUP_AUTO_APPROVE_HOURS = 3       # "ask": no answer within this many hours → the bot approves by itself
ROUNDUP_TIMES_NY = ["07:55", "09:55", "11:55"]   # posting times (New York) of Part 1/2/3, the next morning.
                                     # Sri Lanka time is worked out by itself and follows US summer/winter time:
                                     # NY winter = 6:25 / 8:25 / 10:25 PM SL, NY summer = 5:25 / 7:25 / 9:25 PM SL.
                                     # Late? All three move together.
ROUNDUP_PART_NAMES = ["WAR & CONFLICT", "US NEWS", "WORLD NEWS"]   # FIXED part names, always this order. The AI
                                     # only picks the stories (and hooks) for each part, it never renames them.
ROUNDUP_PART_HASHTAGS = ["#warnews", "#usnews", "#worldnews"]      # one per part, in every caption of that part
ROUNDUP_MIN_CONFLICT_STORIES = 4     # fewer war/conflict/security stories than this → only 2 parts that day:
                                     # "US NEWS" and "WORLD NEWS" (the few conflict stories go into those)
ROUNDUP_MAX_PER_PART = 14            # max stories per part (keeps each video under Facebook's 90 s)
ROUNDUP_MIN_POSTS = 9                # fewer posts that day → no roundup
ROUNDUP_MUSIC = "off"                # "off" = only the bot's own sounds; or a folder, e.g. "assets/music", of
                                     # royalty-free tracks you add (played quietly under the sounds)
ROUNDUP_FACEBOOK = True              # upload each part as a Facebook Reel, scheduled at its time
ROUNDUP_YOUTUBE = True               # upload each part as a YouTube Short (needs the YT_… secrets, see README)
ROUNDUP_TIKTOK = True                # send the TikTok slides + title + caption to your content channel
                                     # (you post them in the TikTok app with a trending sound)
TIKTOK_SLIDES_AS = "photos"          # "photos" = albums you can save on your phone; "files" = full quality files

# ---------- One-time test jobs ----------
# Each id runs ONCE on the next bot run (the bot remembers it). Change the id (e.g. add "b") to run it again.
#   "phototest:<id>"           = new photos for the last 10 posts, sent to Telegram with the AI's score (nothing published)
#   "roundup_test:YYYY-MM-DD"  = the daily roundup of that New York day, sent to Telegram only (no uploads)
#   "yttest:<id>"              = YouTube check: private 3 s video, read back if scheduling works, then deleted
#   "roundup_real:YYYY-MM-DD"  = make that day's roundup for REAL (Facebook + YouTube uploads) at the times in
#                                ROUNDUP_MANUAL_TIMES below (no TikTok slides: you do TikTok yourself)
RUN_ONCE = ["phototest:2026-11-17", "roundup_test:2026-11-16", "yttest:1", "roundup_test:2026-11-16b"]
# ON HOLD: add "roundup_real:2026-11-16" back here (and remove the day from ROUNDUP_HOLD_DAYS) to publish it.
ROUNDUP_HOLD_DAYS = ["2026-11-16"]   # roundup days that must NOT be made/uploaded for real (safety hold)

# One-off posting times for a roundup day (Sri Lanka time, "YYYY-MM-DD HH:MM"), Part 1/2/3.
# A time that is already too close is moved to ~15 min after the videos are ready.
ROUNDUP_MANUAL_TIMES = {"2026-11-16": ["2026-11-17 20:00", "2026-11-17 22:00", "2026-11-17 23:55"]}
