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
