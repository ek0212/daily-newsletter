"""Centralized constants for the daily newsletter pipeline."""

# ── Fetch defaults (newsletter.py orchestration) ────────────────────────
DEFAULT_NEWS_COUNT = 5
DEFAULT_YOUTUBE_DAYS = 1
DEFAULT_PAPERS_DAYS_BACK = 3
DEFAULT_PAPERS_TOP_N = 5
DEFAULT_AI_NEWS_COUNT = 4

# ── HTTP & retry config ─────────────────────────────────────────────────
HTTP_TIMEOUT_SHORT = 5       # quick probes (HEAD requests, socket checks)
HTTP_TIMEOUT_DEFAULT = 10    # standard API calls (weather, citations)
HTTP_TIMEOUT_MEDIUM = 15     # slower feeds (arxiv, HF, events, health)
HTTP_TIMEOUT_LONG = 30       # arxiv bulk queries

GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_BASE_DELAY = 6  # seconds, multiplied by (attempt + 1)

# ── Tor proxy ────────────────────────────────────────────────────────────
TOR_SOCKS_PORT_DEFAULT = 9050
TOR_CONTROL_PORT_DEFAULT = 9051
TOR_MAX_RETRIES = 12
TOR_SLEEP_SECONDS = 5

# ── Text processing thresholds ──────────────────────────────────────────
MIN_TEXT_LENGTH_SHORT = 100   # minimum useful article text
MIN_TEXT_LENGTH_MEDIUM = 200  # minimum podcast/transcript text
MIN_TEXT_LENGTH_LONG = 500    # minimum full website transcript

TEXT_TRUNCATE_PAPER = 1500
TEXT_TRUNCATE_NEWS = 3000
TEXT_TRUNCATE_YOUTUBE = 5000
TEXT_SAMPLE_CHUNK = 2500      # chunk size when sampling long transcripts
TEXT_SKIP_INTRO = 200         # chars to skip at start of transcripts

SUMMARIZER_MIN_TEXT = 200     # minimum input for extractive summarizer
SUMMARIZER_URL_THRESHOLD = 3  # skip text with more URLs than this
SUMMARIZER_SKIP_INTRO = 500   # chars to skip for long transcripts

# ── Scoring & similarity ────────────────────────────────────────────────
PODCAST_MATCH_THRESHOLD = 0.3
DEDUP_OVERLAP_THRESHOLD = 0.6
DEMOTE_MULTIPLIER = 3
CITATION_SCORE_CAP = 20
RELEVANCE_TERM_SCORE = 2
HEALTH_DEVIATION_THRESHOLD = 25  # percent above/below average

# ── Content limits ───────────────────────────────────────────────────────
MAX_VIDEOS = 8
MAX_PODCAST_ENTRIES = 20      # podcast episodes to search for match
MAX_AUTHORS_DISPLAY = 5
MAX_PAPERS_ENRICH = 10        # papers to enrich with citation counts
HF_DAILY_LIMIT = 50
NEWS_FEED_LIMIT_MULTIPLIER = 3
AI_NEWS_CANDIDATE_MULTIPLIER = 3
AI_NEWS_DAYS_CUTOFF = 7
EVENTS_API_LIMIT = 50

# ── LLM quality validation ──────────────────────────────────────────────
MIN_SUMMARY_LENGTH = 10
MIN_EMOJI_BULLETS = 2
MIN_BULLET_SEGMENTS = 2

# ── Display & site ───────────────────────────────────────────────────────
DATE_DISPLAY_FORMAT = "%A, %B %d, %Y"
RSS_PUB_DATE_FORMAT = "%a, %d %b %Y 07:00:00 +0000"
RSS_BUILD_DATE_FORMAT = "%a, %d %b %Y %H:%M:%S +0000"
MAX_FEED_ITEMS = 30
DEFAULT_SITE_URL = "https://ek0212.github.io/daily-newsletter"
USER_AGENT = "DailyNewsletter/1.0"

# ── API URLs ─────────────────────────────────────────────────────────────
ARXIV_API_URL = "http://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1"
HF_DAILY_PAPERS_API_URL = "https://huggingface.co/api/daily_papers"
NWS_FORECAST_URL = "https://api.weather.gov/gridpoints/OKX/33,35/forecast"
NWS_HOURLY_URL = "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly"
NYC_EVENTS_API_URL = "https://data.cityofnewyork.us/resource/tvpp-9vvx.json"
NYC_HEALTH_BASE_URL = "https://raw.githubusercontent.com/nychealth/respiratory-illness-data/main/data"
GOOGLE_NEWS_SEARCH_URL = "https://news.google.com/rss/search"

# ── Weather ──────────────────────────────────────────────────────────────
EST_OFFSET_HOURS = -5
TARGET_HOURS = [7, 9, 15, 17, 19]
WIND_CHILL_TEMP_THRESHOLD = 50   # °F
WIND_CHILL_WIND_THRESHOLD = 3    # mph
HEAT_INDEX_TEMP_THRESHOLD = 80   # °F
HEAT_INDEX_HUMIDITY_THRESHOLD = 40  # %

# ── YouTube Shorts generator ──────────────────────────────────────────
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
SHORTS_DIR = "site/shorts"
SHORTS_HOOK_BG = "#1a1a1a"
SHORTS_BODY_BG = "#fffdf7"
SHORTS_CTA_BG = "#1a1a1a"
SHORTS_ACCENT = "#c0392b"
SHORTS_TEXT_LIGHT = "#ffffff"
SHORTS_TEXT_DARK = "#1a1a1a"
SHORTS_FONT_HOOK = 60
SHORTS_FONT_BODY = 48
SHORTS_FONT_STAT = 72
SHORTS_FONT_CTA = 52
SHORTS_FONT_SMALL = 28
SHORTS_MARGIN = 80
