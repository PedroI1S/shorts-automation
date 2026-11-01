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

# Speaking rate (words/second) used to reject over-long scripts BEFORE any TTS
# call. Lower = more conservative (predicts longer audio).
# kokoro: a 59-word story measured 3.28-3.71 w/s across voices at speed 1.1; 3.0 adds margin.
SPEECH_WORDS_PER_SECOND = {"kokoro": 3.0}
# Story length gates. The validator ceiling keeps narration + tail under the limit
# (146 / 3.0 = 48.7s + 0.8s = 49.5s <= 58s). The prompt leaves margin for LLM
# miscounts. There is no minimum length; complete stories must not be padded.
STORY_MAX_WORDS = 146
STORY_PROMPT_MAX_WORDS = 140
# Chat-thread Shorts voice every message separately and add silent gaps between
# them, so they get a smaller word budget. Gaps also give the typing indicator time.
CHAT_MAX_WORDS = 115
CHAT_PROMPT_MAX_WORDS = 105
CHAT_MAX_MESSAGES = 18
CHAT_MAX_MESSAGE_WORDS = 30
CHAT_GAP_SECONDS = 0.25  # Between consecutive messages from the same sender
CHAT_SWITCH_GAP_SECONDS = 0.5  # When the other person answers

# Audio / TTS Settings: Kokoro-82M (hexgrad/Kokoro-82M, Apache-2.0), local CPU only.
# Kokoro needs Python <3.13, so it runs in its own .venv-kokoro (Python 3.12).
KOKORO_PYTHON = Path(
    os.getenv("KOKORO_PYTHON", BASE_DIR / ".venv-kokoro" / "Scripts" / "python.exe")
)
KOKORO_REPO = "hexgrad/Kokoro-82M"
KOKORO_SPEED = 1.1
KOKORO_TIMEOUT_SECONDS = 900
# The first voice of each gender narrates stories; the rest give chat contacts
# distinct voices. Prefixes: a = American English, b = British English.
KOKORO_VOICES = {
    "male": ["am_fenrir", "am_michael", "am_puck", "bm_george", "bm_fable"],
    "female": ["af_heart", "af_bella", "af_nicole", "bf_emma", "af_sarah"],
}
DEFAULT_VOICE = KOKORO_VOICES["male"][0]

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

_chat_font_candidates = [
    os.getenv("CHAT_FONT_PATH", ""),
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_chat_bold_candidates = [
    os.getenv("CHAT_BOLD_FONT_PATH", ""),
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
CHAT_FONT_PATH = next((p for p in _chat_font_candidates if p and os.path.isfile(p)), "")
CHAT_BOLD_FONT_PATH = next((p for p in _chat_bold_candidates if p and os.path.isfile(p)), "")

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
