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

# ---------- How many posts ----------
DRAFTS_PER_RUN = 3           # new posts sent to Telegram each time it looks for news
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
OTHER_NEWS_MIN_SOURCES = 4
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

# ---------- Caption ----------
SHOW_READ_MORE_LINK = True   # include the original article link in the Facebook caption
SHARE_TO_STORY = True        # also share every published post to the Page's Facebook Story (True / False)
TIKTOK_HASHTAGS = "#news #worldnews #fyp"   # added to the caption sent to your TikTok channel (/tiktok)

# Question at the end of the post (to get comments):
#   "always"    = every post
#   "sometimes" = only when the story is a real debate, never on deaths/attacks/tragedies (recommended)
#   "never"     = no questions
ASK_QUESTION = "sometimes"

# ---------- Post stats (likes, comments, shares) ----------
STATS_EVERY_MINUTES = 60     # how often the numbers under published posts are refreshed
STATS_DAYS = 3               # keep updating a post's numbers for this many days after publishing

# ---------- Photo variety ----------
PHOTOS_PER_PERSON = 12       # how many different free photos the bot collects per person (e.g. Trump)
NO_REPEAT_PHOTOS = 40        # a photo is not used again until this many other photos were used
PHOTO_POOL_DAYS = 7          # refresh each person's photo collection after this many days
# Better photo searches for some places: "what Gemini asks": ("what to search", [words the photo name must NOT have])
PHOTO_SEARCH_FIX = {
    "white house": ("White House Washington", ["moscow", "russia", "russian", "minsk", "canyon", "ruin", "arizona"]),
    "capitol": ("United States Capitol", ["state capitol", "texas", "havana"]),
}

# Photo ideas per topic. If a headline has one of the words on the left, the bot rotates through
# these photo ideas (plus the AI's own ideas), so stories about the same topic look different.
# Add or change ideas freely: 2-4 words each, a place or a thing (never a person).
TOPIC_PHOTO_IDEAS = {
    ("democrat", "dnc", "schumer", "jeffries"): [
        "Democratic National Convention", "US Capitol dome", "Senate chamber, United States Capitol",
        "House chamber, United States Capitol", "Capitol Hill", "United States Capitol rotunda",
        "Capitol at night", "National Mall, Washington", "voting booth, United States", "Library of Congress",
        "campaign rally, United States"],
    ("republican", "gop", "rnc", "maga"): [
        "Republican National Convention", "US Capitol dome", "Senate chamber, United States Capitol",
        "House chamber, United States Capitol", "Capitol Hill", "United States Capitol rotunda",
        "Capitol at night", "National Mall, Washington", "voting booth, United States", "Library of Congress",
        "campaign rally, United States"],
    ("congress", "senate", "senator", "lawmaker", "shutdown", "speaker"): [
        "US Capitol dome", "Senate chamber, United States Capitol", "House chamber, United States Capitol",
        "Capitol Hill", "United States Capitol rotunda", "Capitol at night", "Russell Senate Office Building",
        "Library of Congress", "US Capitol west front", "Capitol Reflecting Pool"],
    ("election", "voter", "ballot", "midterm", "primaries"): [
        "voting booth, United States", "ballot box, United States", "polling place, United States",
        "early voting, United States", "I voted sticker", "vote counting, United States",
        "campaign rally, United States", "US Capitol dome", "absentee ballot"],
    ("supreme court", "judge", "justices", "ruling", "lawsuit", "indicted", "indictment"): [
        "Supreme Court of the United States", "Supreme Court building, Washington", "Robert F. Kennedy Department of Justice Building",
        "E. Barrett Prettyman United States Courthouse", "federal courthouse, United States",
        "Supreme Court, Washington DC", "Thurgood Marshall Federal Judiciary Building"],
    ("tariff", "trade war", "economy", "inflation", "stock market", "wall street", "federal reserve", "prices"): [
        "Port of Long Beach", "Port of Los Angeles", "container ship", "shipping containers, port",
        "New York Stock Exchange", "Wall Street, New York", "Marriner S. Eccles Federal Reserve Board Building",
        "Treasury Building, Washington", "factory assembly line", "Port of Savannah"],
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
}
