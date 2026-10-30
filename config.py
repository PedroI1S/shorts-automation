import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
SECRETS_DIR = BASE_DIR / "secrets"
STORAGE_DIR = BASE_DIR / "storage"
BACKGROUNDS_DIR = STORAGE_DIR / "backgrounds"
AUDIO_DIR = STORAGE_DIR / "audio"
SUBTITLES_DIR = STORAGE_DIR / "subtitles"
OUTPUT_DIR = STORAGE_DIR / "output"
TEMP_DIR = STORAGE_DIR / "temp"

for d in [BACKGROUNDS_DIR, AUDIO_DIR, SUBTITLES_DIR, OUTPUT_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Video Specs (YouTube Shorts / TikTok standard)
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30
MAX_DURATION_SECONDS = 58
NARRATION_TAIL_SECONDS = 0.8  # Silent tail appended after narration by the compiler

# Speaking rates (words/second) used to reject over-long scripts BEFORE any paid
# or quota-limited TTS call. Lower = more conservative (predicts longer audio).
# fish: measured 146 words -> 56.29 s (2.59 w/s) on the selected voice.
# elevenlabs: short 31-word George sample measured 3.4 w/s; 2.9 adds margin.
# edge: Christopher neural is ~150 wpm before pause tightening.
SPEECH_WORDS_PER_SECOND = {"fish": 2.59, "elevenlabs": 2.9, "edge": 2.5}
# Story length gates. The validator ceiling keeps Fish narration + tail under the limit
# (146 / 2.59 = 56.4s + 0.8s = 57.2s <= 58s). The prompt leaves margin for LLM
# miscounts. There is no minimum length; complete stories must not be padded.
STORY_MAX_WORDS = 146
STORY_PROMPT_MAX_WORDS = 140

# Audio / TTS Settings
DEFAULT_VOICE = "en-US-ChristopherNeural"  # Deep, engaging male narrator
# Alternative voices:
# "en-US-GuyNeural"
# "en-US-JennyNeural" (Female)
# "en-GB-RyanNeural" (British accent)

# Font & Subtitle Styling
_font_candidates = [
    os.getenv("SUBTITLE_FONT_PATH", ""),
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_PATH = next((path for path in _font_candidates if path and os.path.isfile(path)), "")

SUBTITLE_FONT_SIZE = 72
SUBTITLE_PRIMARY_COLOR = (255, 255, 255, 255)  # White
SUBTITLE_HIGHLIGHT_COLOR = (255, 225, 0, 255)  # Electric Yellow
SUBTITLE_STROKE_COLOR = (0, 0, 0, 255)  # Deep Black Outline
SUBTITLE_STROKE_WIDTH = 5
SUBTITLE_BOX_BG = (0, 0, 0, 160)  # Semi-transparent dark card
SUBTITLE_WORDS_PER_CHUNK = 3  # Fast TikTok/Shorts pacing

# LLM / Story Generation Settings
DEFAULT_AGY_MODEL = "gemini-3.8-flash-medium"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "hermes3:latest")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Default Gameplay Search Queries
GAMEPLAY_QUERIES = [
    "Labyrinth Minetest",
]
