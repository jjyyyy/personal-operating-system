#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import ssl
import shutil
import subprocess
import time
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from transcription_service import transcribe


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
DAILY_DIR = VOICE_ROOT / "daily"
TOPICS_DIR = VOICE_ROOT / "topics"
REVIEWS_DIR = VOICE_ROOT / "reviews"
TEMPLATES_DIR = VOICE_ROOT / "templates"
LOGS_DIR = VOICE_ROOT / "logs"
INDEX_FILE = VOICE_ROOT / "index.json"
CATALOG_FILE = VOICE_ROOT / "catalog.md"
LOG_FILE = VOICE_ROOT / "log.md"
TRANSCRIPT_EXTENSIONS = {".txt", ".md", ".markdown"}
AUDIO_EXTENSIONS = {".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".wav", ".webm"}
TEMP_SOURCE_SUFFIXES = {".icloud", ".download", ".part", ".tmp", ".crdownload"}
TRANSIENT_API_STATUS_CODES = {429, 500, 502, 503, 504}


def ensure_dirs() -> None:
    for path in [
        VOICE_ROOT,
        INBOX_DIR,
        PROCESSED_DIR,
        DISCARDED_DIR,
        DAILY_DIR,
        TOPICS_DIR,
        REVIEWS_DIR,
        TEMPLATES_DIR,
        LOGS_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    if not INDEX_FILE.exists():
        INDEX_FILE.write_text("[]\n", encoding="utf-8")
    if not LOG_FILE.exists():
        LOG_FILE.write_text("# Voice Notes Log\n\n", encoding="utf-8")


def require_api_key() -> str:
    load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY. Add it to .env or your shell environment.")
    return api_key


def read_index() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    return json.loads(INDEX_FILE.read_text(encoding="utf-8"))


def write_index(items: list[dict]) -> None:
    INDEX_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    cleaned = []
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
        elif char in {" ", "-", "_"}:
            cleaned.append("-")
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "note"


def topic_link(topic: str) -> str:
    slug = slugify(topic)
    topic_file = topic_file_for_name(topic)
    if topic_file.exists():
        return f"[[topics/{slug}|{topic}]]"
    return f"{topic} (unpromoted)"


def path_for_index(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(VOICE_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def obsidian_link(path: Path, label: str | None = None) -> str:
    target = path_for_index(path)
    if target.endswith(".md"):
        target = target[:-3]
    return f"[[{target}|{label or path.stem}]]"


def append_log(kind: str, title: str, lines: list[str] | None = None) -> None:
    ensure_dirs()
    entry_lines = [
        f"## [{dt.date.today().isoformat()}] {kind} | {title}",
        "",
    ]
    if lines:
        entry_lines.extend(lines)
        entry_lines.append("")
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(entry_lines) + "\n")


def notifications_enabled() -> bool:
    value = os.environ.get("VOICE_NOTES_NOTIFICATIONS", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def send_notification(message: str, title: str = "Voice Notes") -> bool:
    if not notifications_enabled():
        return False

    script = (
        "on run argv\n"
        "display notification (item 1 of argv) with title (item 2 of argv)\n"
        "end run"
    )
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", script, message, title],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Could not send notification: {exc}")
        return False


def first_content_line(path: Path) -> str:
    in_frontmatter = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter or not stripped or stripped.startswith("#") or stripped.startswith("- "):
            continue
        if len(stripped) > 160:
            return stripped[:157] + "..."
        return stripped
    return "No summary yet."


def topic_file_for_name(topic: str) -> Path:
    return TOPICS_DIR / f"{slugify(topic)}.md"


def existing_topic_links(topics: list[str]) -> str:
    links = []
    for topic in topics:
        topic_file = topic_file_for_name(topic)
        if topic_file.exists():
            links.append(obsidian_link(topic_file, topic))
        else:
            links.append(topic)
    return ", ".join(links) or "none"


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def retry_delay(attempt: int) -> int:
    return min(2**attempt, 8)


def api_post_json(url: str, payload: dict, api_key: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, context=ssl_context()) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in TRANSIENT_API_STATUS_CODES and attempt < 2:
                delay = retry_delay(attempt)
                print(f"OpenAI API returned {exc.code}; retrying in {delay}s...")
                time.sleep(delay)
                continue
            raise SystemExit(f"OpenAI API request failed: {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            if attempt < 2:
                delay = retry_delay(attempt)
                print(f"OpenAI API connection failed; retrying in {delay}s...")
                time.sleep(delay)
                continue
            raise SystemExit(f"Could not reach OpenAI API: {exc.reason}") from exc
    raise SystemExit("OpenAI API request failed after retries.")


def summarize_transcript(transcript: str, note_date: str, api_key: str) -> dict:
    model = os.environ.get("OPENAI_SUMMARY_MODEL", "gpt-4.1-mini")
    prompt = textwrap.dedent(
        f"""
        You are organizing a user's personal voice note into a clean knowledge note.
        Return valid JSON with exactly these keys:
        date, title, source, topics, summary, action_items, people, raw_transcript

        Rules:
        - date must stay "{note_date}"
        - source must be "voice"
        - title should be short and concrete
        - topics should be a JSON array of 1-5 short strings
        - summary should be 2-5 bullet-worthy sentences combined into one paragraph
        - action_items should be a JSON array
        - people should be a JSON array
        - raw_transcript should preserve the transcript with light cleanup only

        Transcript:
        {transcript}
        """
    ).strip()

    response = api_post_json(
        "https://api.openai.com/v1/responses",
        payload={
            "model": model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "voice_note",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "date": {"type": "string"},
                            "title": {"type": "string"},
                            "source": {"type": "string"},
                            "topics": {"type": "array", "items": {"type": "string"}},
                            "summary": {"type": "string"},
                            "action_items": {"type": "array", "items": {"type": "string"}},
                            "people": {"type": "array", "items": {"type": "string"}},
                            "raw_transcript": {"type": "string"},
                        },
                        "required": [
                            "date",
                            "title",
                            "source",
                            "topics",
                            "summary",
                            "action_items",
                            "people",
                            "raw_transcript",
                        ],
                    },
                }
            },
        },
        api_key=api_key,
    )

    try:
        output_text = response.get("output_text") or response["output"][0]["content"][0]["text"]
        data = json.loads(output_text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not parse summary response: {json.dumps(response, ensure_ascii=False)}") from exc

    required_keys = [
        "date",
        "title",
        "source",
        "topics",
        "summary",
        "action_items",
        "people",
        "raw_transcript",
    ]
    for key in required_keys:
        if key not in data:
            raise SystemExit(f"Summary response missing key: {key}")

    return data


def note_markdown(note: dict) -> str:
    topics = "\n".join(f"- {item}" for item in note["topics"]) or "-"
    action_items = "\n".join(f"- {item}" for item in note["action_items"]) or "-"
    people = "\n".join(f"- {item}" for item in note["people"]) or "-"
    links = "\n".join(f"- {topic_link(topic)}" for topic in note["topics"]) or "-"

    return (
        f"---\n"
        f"date: {note['date']}\n"
        f"source: {note['source']}\n"
        f"topics: {json.dumps(note['topics'], ensure_ascii=False)}\n"
        f"people: {json.dumps(note['people'], ensure_ascii=False)}\n"
        f"title: {note['title']}\n"
        f"---\n\n"
        f"# {note['title']}\n\n"
        f"## Summary\n\n"
        f"{note['summary']}\n\n"
        f"## Topics\n\n"
        f"{topics}\n\n"
        f"## Action Items\n\n"
        f"{action_items}\n\n"
        f"## People\n\n"
        f"{people}\n\n"
        f"## Links\n\n"
        f"{links}\n\n"
        f"## Raw Transcript\n\n"
        f"{note['raw_transcript']}\n"
    )


def save_note(note: dict, source_file: Path) -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{note['date']}-{slugify(note['title'])}-{timestamp}.md"
    output_path = DAILY_DIR / filename
    output_path.write_text(note_markdown(note), encoding="utf-8")

    index = read_index()
    index.append(
        {
            "date": note["date"],
            "title": note["title"],
            "topics": note["topics"],
            "people": note["people"],
            "summary": note["summary"],
            "source_file": path_for_index(source_file),
            "note_file": path_for_index(output_path),
        }
    )
    write_index(index)
    return output_path


def rebuild_catalog() -> Path:
    ensure_dirs()
    items = sorted(read_index(), key=lambda item: (item.get("date", ""), item.get("title", "")))
    topic_files = sorted(TOPICS_DIR.glob("*.md"), key=lambda path: path.name.lower())
    review_files = sorted(REVIEWS_DIR.glob("*.md"), key=lambda path: path.name.lower())

    lines = [
        "# Voice Notes Catalog",
        "",
        "Generated content catalog. Keep `index.md` small; read this file only for broad discovery.",
        "",
        "## Topic Notes",
        "",
    ]

    if topic_files:
        for path in topic_files:
            lines.append(f"- {obsidian_link(path)}: {first_content_line(path)}")
    else:
        lines.append("- No topic notes yet.")

    lines.extend(["", "## Reviews", ""])
    if review_files:
        for path in review_files:
            lines.append(f"- {obsidian_link(path)}: {first_content_line(path)}")
    else:
        lines.append("- No reviews yet.")

    lines.extend(["", "## Daily Notes", ""])
    if items:
        for item in items:
            note_path = VOICE_ROOT / item["note_file"]
            title = item.get("title", note_path.stem)
            topics = ", ".join(item.get("topics", [])) or "none"
            summary = item.get("summary", "No summary.")
            lines.append(f"- {item.get('date', 'undated')} {obsidian_link(note_path, title)}")
            lines.append(f"  - Topics: {topics}")
            lines.append(f"  - Summary: {summary}")
    else:
        lines.append("- No daily notes yet.")

    CATALOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return CATALOG_FILE


def archive_source(source_path: Path) -> Path:
    destination = PROCESSED_DIR / source_path.name
    counter = 1
    while destination.exists():
        destination = PROCESSED_DIR / f"{source_path.stem}-{counter}{source_path.suffix}"
        counter += 1
    shutil.move(str(source_path), str(destination))
    return destination


def move_to_discarded(source_path: Path) -> Path:
    ensure_dirs()
    destination = DISCARDED_DIR / source_path.name
    counter = 1
    while destination.exists():
        destination = DISCARDED_DIR / f"{source_path.stem}-{counter}{source_path.suffix}"
        counter += 1
    shutil.move(str(source_path), str(destination))
    append_log(
        "discard",
        source_path.name,
        [f"- Discarded source: {path_for_index(destination)}"],
    )
    return destination


def is_transcript_file(source_path: Path) -> bool:
    return source_path.suffix.lower() in TRANSCRIPT_EXTENSIONS


def is_supported_source(source_path: Path) -> bool:
    return source_path.suffix.lower() in AUDIO_EXTENSIONS | TRANSCRIPT_EXTENSIONS


def is_temporary_source(source_path: Path) -> bool:
    if source_path.name.startswith("."):
        return True
    lowered = source_path.name.lower()
    return any(lowered.endswith(suffix) for suffix in TEMP_SOURCE_SUFFIXES)


def is_source_ready(source_path: Path, settle_seconds: int = 0) -> bool:
    if is_temporary_source(source_path) or not is_supported_source(source_path):
        return False
    if settle_seconds <= 0:
        return True
    try:
        age_seconds = time.time() - source_path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age_seconds >= settle_seconds


def ingest(source_path: Path, note_date: dt.date | None = None) -> None:
    ensure_dirs()
    if not source_path.exists():
        raise SystemExit(f"Source file not found: {source_path}")

    api_key = require_api_key()
    resolved_date = (note_date or dt.date.today()).isoformat()

    if is_transcript_file(source_path):
        print(f"Reading transcript {source_path.name}...")
        transcript = source_path.read_text(encoding="utf-8").strip()
        if not transcript:
            raise SystemExit(f"Transcript file is empty: {source_path}")
    else:
        print(f"Transcribing {source_path.name}...")
        transcript = transcribe(source_path, api_key)["text"]

    print("Generating structured note...")
    note = summarize_transcript(transcript, resolved_date, api_key)
    note["raw_transcript"] = transcript
    archived_path = archive_source(source_path)
    output_path = save_note(note, archived_path)
    rebuild_catalog()
    append_log(
        "ingest",
        note["title"],
        [
            f"- Source: {path_for_index(archived_path)}",
            f"- Daily note: {obsidian_link(output_path, note['title'])}",
            f"- Topics: {existing_topic_links(note['topics'])}",
        ],
    )
    print(f"Saved note: {output_path}")
    print(f"Archived source: {archived_path}")
    send_notification(note["title"], "Voice note parsed")


def process_source_safely(source_path: Path, note_date: dt.date | None = None) -> bool:
    try:
        ingest(source_path, note_date)
        return True
    except SystemExit as exc:
        error_message = str(exc)
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"

    print(f"Failed to process {source_path.name}: {error_message}")
    append_log(
        "error",
        source_path.name,
        [
            f"- Source: {path_for_index(source_path)}",
            f"- Error: {error_message}",
        ],
    )
    send_notification(f"{source_path.name}: {error_message}", "Voice note failed")
    return False


def inbox_sources() -> list[Path]:
    ensure_dirs()
    return sorted(path for path in INBOX_DIR.iterdir() if path.is_file() and is_supported_source(path))


def ready_inbox_sources(settle_seconds: int = 0) -> list[Path]:
    ensure_dirs()
    return sorted(path for path in INBOX_DIR.iterdir() if path.is_file() and is_source_ready(path, settle_seconds))


def resolve_inbox_source(raw_path: Path) -> Path:
    if raw_path.exists():
        return raw_path
    inbox_path = INBOX_DIR / raw_path
    if inbox_path.exists():
        return inbox_path
    raise SystemExit(f"Source file not found: {raw_path}")


def discard_inbox(source_files: list[Path], latest: bool = False) -> None:
    ensure_dirs()
    if source_files:
        sources = [resolve_inbox_source(path) for path in source_files]
    elif latest:
        sources = ready_inbox_sources(0)
        if not sources:
            print("No supported files found in inbox.")
            return
        sources = [max(sources, key=lambda path: path.stat().st_mtime)]
    else:
        raise SystemExit("Pass one or more inbox files, or use --latest.")

    for source_path in sources:
        discarded_path = move_to_discarded(source_path)
        print(f"Discarded: {discarded_path}")


def process_inbox(note_date: dt.date | None = None, settle_seconds: int = 0) -> None:
    sources = ready_inbox_sources(settle_seconds)
    if not sources:
        print("No supported files found in inbox.")
        return

    for source_path in sources:
        process_source_safely(source_path, note_date)


def watch_inbox(
    note_date: dt.date | None = None,
    interval_seconds: int = 30,
    settle_seconds: int = 20,
    once: bool = False,
) -> None:
    ensure_dirs()
    print(f"Watching inbox: {INBOX_DIR}")
    print(f"Settle seconds: {settle_seconds}; poll interval: {interval_seconds}")
    while True:
        sources = ready_inbox_sources(settle_seconds)
        if sources:
            for source_path in sources:
                process_source_safely(source_path, note_date)
        elif once:
            print("No ready files found in inbox.")

        if once:
            return
        time.sleep(interval_seconds)


def load_note_files_in_range(date_from: dt.date, date_to: dt.date) -> list[Path]:
    files: list[Path] = []
    for path in sorted(DAILY_DIR.glob("*.md")):
        date_prefix = path.name[:10]
        try:
            note_date = dt.date.fromisoformat(date_prefix)
        except ValueError:
            continue
        if date_from <= note_date <= date_to:
            files.append(path)
    return files


def weekly_review(date_from: dt.date, date_to: dt.date) -> Path:
    ensure_dirs()
    api_key = require_api_key()
    note_files = load_note_files_in_range(date_from, date_to)
    if not note_files:
        raise SystemExit(f"No notes found between {date_from} and {date_to}.")

    notes_blob = "\n\n".join(path.read_text(encoding="utf-8") for path in note_files)
    model = os.environ.get("OPENAI_SUMMARY_MODEL", "gpt-4.1-mini")
    prompt = textwrap.dedent(
        f"""
        Read the following weekly voice notes and write a weekly review in Markdown.

        Include:
        - Top themes
        - Repeated topics
        - Action items
        - People mentioned
        - Suggested updates for long-term topic notes

        Date range: {date_from} to {date_to}

        Notes:
        {notes_blob}
        """
    ).strip()

    response = api_post_json(
        "https://api.openai.com/v1/responses",
        payload={"model": model, "input": prompt},
        api_key=api_key,
    )
    try:
        review_text = (response.get("output_text") or response["output"][0]["content"][0]["text"]).strip()
    except (KeyError, IndexError) as exc:
        raise SystemExit(f"Could not parse weekly review response: {json.dumps(response, ensure_ascii=False)}") from exc

    filename = f"{date_from}_to_{date_to}_weekly_review.md"
    output_path = REVIEWS_DIR / filename
    output_path.write_text(review_text + "\n", encoding="utf-8")
    rebuild_catalog()
    append_log(
        "review",
        f"Weekly review {date_from} to {date_to}",
        [f"- Review: {obsidian_link(output_path)}"],
    )
    return output_path


def search_notes(query: str) -> list[tuple[Path, int, str]]:
    ensure_dirs()
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results: list[tuple[Path, int, str]] = []
    root_files = [
        VOICE_ROOT / "index.md",
        VOICE_ROOT / "00-home.md",
        VOICE_ROOT / "01-methodology.md",
        VOICE_ROOT / "02-operating-system.md",
        VOICE_ROOT / "AGENTS.md",
        VOICE_ROOT / "catalog.md",
        VOICE_ROOT / "log.md",
    ]
    for path in root_files:
        if not path.exists():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                results.append((path, line_number, line.strip()))

    for base_dir in [TOPICS_DIR, REVIEWS_DIR, DAILY_DIR]:
        for path in sorted(base_dir.glob("*.md")):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.search(line):
                    results.append((path, line_number, line.strip()))
    return results


def markdown_files() -> list[Path]:
    root_files = [
        VOICE_ROOT / "index.md",
        VOICE_ROOT / "catalog.md",
        VOICE_ROOT / "log.md",
        VOICE_ROOT / "00-home.md",
        VOICE_ROOT / "01-methodology.md",
        VOICE_ROOT / "02-operating-system.md",
        VOICE_ROOT / "AGENTS.md",
        VOICE_ROOT / "README.md",
        VOICE_ROOT / "CLAUDE.md",
    ]
    files = [path for path in root_files if path.exists()]
    for base_dir in [TOPICS_DIR, REVIEWS_DIR, DAILY_DIR, TEMPLATES_DIR, VOICE_ROOT / "prompts", VOICE_ROOT / "docs"]:
        if base_dir.exists():
            files.extend(sorted(base_dir.glob("*.md")))
    return files


def link_target_exists(target: str, all_files: list[Path]) -> bool:
    clean_target = target.split("#", 1)[0].strip()
    if not clean_target:
        return True

    if clean_target.endswith(".md"):
        direct = VOICE_ROOT / clean_target
    else:
        direct = VOICE_ROOT / f"{clean_target}.md"
    if direct.exists():
        return True

    target_stem = Path(clean_target).stem
    return any(path.stem == target_stem for path in all_files)


def lint_wiki() -> Path:
    ensure_dirs()
    all_files = markdown_files()
    link_pattern = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
    missing_links: list[tuple[Path, str]] = []

    for path in all_files:
        if path.name.endswith("_wiki_lint.md"):
            continue
        for match in link_pattern.finditer(path.read_text(encoding="utf-8")):
            target = match.group(1)
            if not link_target_exists(target, all_files):
                missing_links.append((path, target))

    topic_files = sorted(TOPICS_DIR.glob("*.md"), key=lambda path: path.name.lower())
    topics_without_sources = [
        path for path in topic_files if "[[" not in path.read_text(encoding="utf-8").split("## Source Notes")[-1]
    ]

    topic_counts: dict[str, int] = {}
    for item in read_index():
        for topic in item.get("topics", []):
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
    promotion_candidates = sorted(
        topic for topic, count in topic_counts.items() if count > 1 and not topic_file_for_name(topic).exists()
    )

    today = dt.date.today().isoformat()
    output_path = REVIEWS_DIR / f"{today}_wiki_lint.md"
    lines = [
        f"# Wiki Lint: {today}",
        "",
        "## Missing Link Targets",
        "",
    ]
    if missing_links:
        for path, target in missing_links:
            lines.append(f"- {obsidian_link(path)} links to missing target `{target}`.")
    else:
        lines.append("- No missing link targets found.")

    lines.extend(["", "## Topic Notes Without Source Links", ""])
    if topics_without_sources:
        for path in topics_without_sources:
            lines.append(f"- {obsidian_link(path)}")
    else:
        lines.append("- Every topic note has at least one source-style wikilink.")

    lines.extend(["", "## Promotion Candidates", ""])
    if promotion_candidates:
        for topic in promotion_candidates:
            lines.append(f"- `{topic}` appears repeatedly in daily notes and may deserve a topic note.")
    else:
        lines.append("- No repeated unpromoted topics found.")

    lines.extend(["", "## Follow-Up", ""])
    lines.append("- Review missing links before creating new topic pages; some may be intentionally lightweight tags.")
    lines.append("- Update topic notes only when the evidence has durable value.")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rebuild_catalog()
    append_log("lint", "Wiki health check", [f"- Report: {obsidian_link(output_path)}"])
    return output_path


def init_topics() -> list[Path]:
    ensure_dirs()
    defaults = {
        "career.md": "# Career\n\n## Notes\n\n## Open Questions\n\n## Next Actions\n",
        "health.md": "# Health\n\n## Notes\n\n## Patterns\n\n## Next Actions\n",
        "system-design.md": "# System Design\n\n## Notes\n\n## Concepts\n\n## Practice Ideas\n",
        "ideas.md": "# Ideas\n\n## Active\n\n## Backlog\n",
    }

    created: list[Path] = []
    for filename, content in defaults.items():
        path = TOPICS_DIR / filename
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(path)
    return created


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Voice notes AI workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Transcribe or organize one source file")
    ingest_parser.add_argument("source_files", nargs="+", type=Path)
    ingest_parser.add_argument("--date", dest="note_date", type=str, default=None)

    inbox_parser = subparsers.add_parser("process-inbox", help="Process every supported file in inbox")
    inbox_parser.add_argument("--date", dest="note_date", type=str, default=None)
    inbox_parser.add_argument("--settle-seconds", dest="settle_seconds", type=int, default=0)

    watch_parser = subparsers.add_parser("watch-inbox", help="Poll inbox and process files once they finish syncing")
    watch_parser.add_argument("--date", dest="note_date", type=str, default=None)
    watch_parser.add_argument("--interval", dest="interval_seconds", type=int, default=30)
    watch_parser.add_argument("--settle-seconds", dest="settle_seconds", type=int, default=20)
    watch_parser.add_argument("--once", action="store_true", help="Check once and exit")

    discard_parser = subparsers.add_parser("discard-inbox", help="Move accidental inbox recordings to discarded/")
    discard_parser.add_argument("source_files", nargs="*", type=Path)
    discard_parser.add_argument("--latest", action="store_true", help="Discard the newest supported inbox file")

    review_parser = subparsers.add_parser("weekly-review", help="Create a weekly review from daily notes")
    review_parser.add_argument("--from", dest="date_from", type=str, default=None)
    review_parser.add_argument("--to", dest="date_to", type=str, default=None)

    search_parser = subparsers.add_parser("search", help="Search topic, review, and daily notes")
    search_parser.add_argument("query", type=str)

    subparsers.add_parser("rebuild-catalog", help="Regenerate catalog.md from vault files")
    subparsers.add_parser("lint-wiki", help="Create a wiki health-check report")
    subparsers.add_parser("test-notification", help="Send a macOS notification without calling OpenAI")
    subparsers.add_parser("init-topics", help="Create default topic note files")
    return parser.parse_args()


def resolve_date_range(raw_from: str | None, raw_to: str | None) -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    if raw_from:
        date_from = dt.date.fromisoformat(raw_from)
    else:
        date_from = today - dt.timedelta(days=today.weekday())

    if raw_to:
        date_to = dt.date.fromisoformat(raw_to)
    else:
        date_to = date_from + dt.timedelta(days=6)
    return date_from, date_to


def resolve_note_date(raw_date: str | None) -> dt.date | None:
    if not raw_date:
        return None
    return dt.date.fromisoformat(raw_date)


def main() -> None:
    args = parse_args()
    if args.command == "ingest":
        note_date = resolve_note_date(args.note_date)
        for source_file in args.source_files:
            ingest(source_file, note_date)
        return

    if args.command == "process-inbox":
        process_inbox(resolve_note_date(args.note_date), args.settle_seconds)
        return

    if args.command == "watch-inbox":
        watch_inbox(
            note_date=resolve_note_date(args.note_date),
            interval_seconds=args.interval_seconds,
            settle_seconds=args.settle_seconds,
            once=args.once,
        )
        return

    if args.command == "discard-inbox":
        discard_inbox(args.source_files, args.latest)
        return

    if args.command == "weekly-review":
        date_from, date_to = resolve_date_range(args.date_from, args.date_to)
        output_path = weekly_review(date_from, date_to)
        print(f"Saved review: {output_path}")
        return

    if args.command == "search":
        results = search_notes(args.query)
        if not results:
            print(f"No matches found for: {args.query}")
            return
        for path, line_number, line in results:
                print(f"{path_for_index(path)}:{line_number}: {line}")
        return

    if args.command == "rebuild-catalog":
        output_path = rebuild_catalog()
        append_log("catalog", "Rebuilt content catalog", [f"- Catalog: {obsidian_link(output_path)}"])
        print(f"Saved catalog: {output_path}")
        return

    if args.command == "lint-wiki":
        output_path = lint_wiki()
        print(f"Saved lint report: {output_path}")
        return

    if args.command == "test-notification":
        if send_notification("Notifications are working.", "Voice Notes"):
            print("Notification test sent.")
        else:
            raise SystemExit("Notification test failed.")
        return

    if args.command == "init-topics":
        created = init_topics()
        if created:
            print("Created:")
            for path in created:
                print(f"- {path}")
        else:
            print("Topic files already exist.")
        return

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
