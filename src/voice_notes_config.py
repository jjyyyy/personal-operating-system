from __future__ import annotations

import errno
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

VOICE_ROOT = Path(os.environ.get("VOICE_NOTES_ROOT", ROOT)).expanduser()
INBOX_DIR = Path(os.environ.get("VOICE_NOTES_INBOX", VOICE_ROOT / "inbox")).expanduser()
PROCESSED_DIR = VOICE_ROOT / "processed"
DISCARDED_DIR = VOICE_ROOT / "discarded"
DEFERRED_DIR = VOICE_ROOT / "deferred"
DAILY_DIR = VOICE_ROOT / "daily"
XHS_DIR = VOICE_ROOT / "xhs"
TOPICS_DIR = VOICE_ROOT / "topics"
REVIEWS_DIR = VOICE_ROOT / "reviews"
SNIPPETS_DIR = VOICE_ROOT / "snippets"
TEMPLATES_DIR = VOICE_ROOT / "templates"
LOGS_DIR = VOICE_ROOT / "logs"
STATE_DIR = VOICE_ROOT / "state"
MAPS_DIR = VOICE_ROOT / "maps"
OUTBOX_DIR = VOICE_ROOT / "outbox"
ROUTES_DIR = VOICE_ROOT / "routes"
CALENDAR_OUTBOX_DIR = OUTBOX_DIR / "calendar"
CALENDAR_CREATED_DIR = OUTBOX_DIR / "calendar-created"
CALENDAR_TELEGRAM_DIR = OUTBOX_DIR / "calendar-telegram"
INDEX_FILE = VOICE_ROOT / "index.json"
CATALOG_FILE = VOICE_ROOT / "catalog.md"
LOG_FILE = VOICE_ROOT / "log.md"
XHS_AUTO_STATE_FILE = STATE_DIR / "xhs-auto-imports.json"

TRANSCRIPT_EXTENSIONS = {".txt", ".md", ".markdown"}
AUDIO_EXTENSIONS = {".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".wav", ".webm"}
TEMP_SOURCE_SUFFIXES = {".icloud", ".download", ".part", ".tmp", ".crdownload"}
TRANSIENT_API_STATUS_CODES = {429, 500, 502, 503, 504}
MOVE_FALLBACK_ERRNOS = {errno.EAGAIN, errno.EDEADLK}
SOURCE_TYPES = ("voice", "xhs", "bot")
XHS_SHARE_PREFIXES = ("xhs-share-", "xiaohongshu-share-")
XHS_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:xhslink\.com|xiaohongshu\.com)/[^\s\"'<>，。；;]+",
    re.IGNORECASE,
)


def ensure_dirs() -> None:
    paths = [
        VOICE_ROOT,
        INBOX_DIR,
        PROCESSED_DIR,
        DISCARDED_DIR,
        DEFERRED_DIR,
        DAILY_DIR,
        XHS_DIR,
        TOPICS_DIR,
        REVIEWS_DIR,
        SNIPPETS_DIR,
        TEMPLATES_DIR,
        LOGS_DIR,
        STATE_DIR,
        MAPS_DIR,
        OUTBOX_DIR,
        CALENDAR_OUTBOX_DIR,
        CALENDAR_CREATED_DIR,
        CALENDAR_TELEGRAM_DIR,
        ROUTES_DIR,
    ]
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
    for root in [INBOX_DIR, PROCESSED_DIR, DISCARDED_DIR, DEFERRED_DIR]:
        for source_type in SOURCE_TYPES:
            (root / source_type).mkdir(parents=True, exist_ok=True)
    if not INDEX_FILE.exists():
        INDEX_FILE.write_text("[]\n", encoding="utf-8")
    if not LOG_FILE.exists():
        LOG_FILE.write_text("# Personal Operating System Log\n\n", encoding="utf-8")


def require_api_key() -> str:
    load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY. Add it to .env or your shell environment.")
    return api_key


def user_alias_hint() -> str:
    user_file = VOICE_ROOT / "USER.md"
    if not user_file.exists():
        return "No self aliases configured."
    for line in user_file.read_text(encoding="utf-8").splitlines():
        if "**Self alias:**" in line:
            return line.split("**Self alias:**", 1)[1].strip()
    return "No self aliases configured."


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer.") from exc
