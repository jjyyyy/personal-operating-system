#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import datetime as dt
import errno
import hashlib
import json
import mimetypes
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
from calendar_flow import (
    build_calendar_candidate,
    create_event,
    telegram_confirmation_package,
)
from capture_sessions import (
    archive_capture_session,
    combined_transcript,
    has_explicit_continuation,
    inbox_capture_groups,
    model_continuation_decision,
    read_capture_transcript,
    split_capture_sessions,
)
from extracted_items import (
    calendar_outbox_candidates,
    extracted_item_schema,
    extracted_items_markdown,
    normalize_extracted_items,
    write_json as write_extracted_json,
)
from google_maps_flow import (
    build_maps_candidates,
    maps_task_payload,
    render_maps_save_markdown,
    render_telegram_preview,
)
from google_calendar_provider import authorize_google_calendar
from note_router import (
    deliver_item_route_package,
    deliver_route_package,
    item_matches_route,
    load_route_registrations,
    matching_registrations,
)
from note_corrections import apply_note_correction, parse_cli_list
from transcription_service import read_source_bytes, transcribe
from video_ingestion import build_video_content_package, video_evidence_text
from xhs_import import download_xhs_video, fetch_xhs_note


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
    for path in [
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
    ]:
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


def send_notification(message: str, title: str = "Personal Operating System") -> bool:
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


def summarize_capture(
    transcript: str,
    note_date: str,
    source_type: str,
    api_key: str,
) -> dict:
    model = os.environ.get("OPENAI_SUMMARY_MODEL", "gpt-4.1-mini")
    prompt = textwrap.dedent(
        f"""
        You are organizing captured material into a clean personal knowledge note.
        Return valid JSON with exactly these keys:
        date, title, source, topics, summary, action_items, people, annotations,
        extracted_items, raw_transcript

        Rules:
        - date must stay "{note_date}"
        - source must be "{source_type}"
        - title should be short and concrete
        - topics should be a JSON array of 1-5 short strings
        - summary should be 2-5 bullet-worthy sentences combined into one paragraph
        - action_items should be a JSON array
        - people should be a JSON array
        - annotations should be a JSON array with 0-3 items
        - extracted_items should be a JSON array of independent generic items
          from the transcript. Return [] if there are no distinct items worth
          routing, reviewing, or remembering.
        - raw_transcript should preserve the transcript with light cleanup only
        - USER.md self-alias hint: {user_alias_hint()}
        - Use the self-alias hint only when context is clear.
        - If a person reference remains ambiguous, label it "unsure" instead of
          guessing whether it means the user or another person.
        - Match the transcript's primary language for title, summary, topics,
          action_items, and annotations unless a proper noun requires otherwise.
        - Do not turn analogies into topics or titles. If the transcript says an
          action is "like badminton" or "similar to serving", keep that as an
          analogy, not as the activity being practiced.
        - If the transcript context suggests a likely transcription ambiguity
          between sports terms, prefer the broader established context and mark
          uncertainty instead of inventing a new sport category.

        Extracted item policy:
        - Extract separate items for mixed memos. For example, a massage
          appointment and tennis technique note should become separate items.
        - item_type must be one of: calendar_event, reminder, task, weak_intent,
          knowledge_note.
        - Use calendar_event only for a clearly scheduled event or appointment.
        - Set calendar_ready true only when the event has enough date/time
          information to review as a calendar candidate.
        - Set needs_confirmation false only when the transcript sounds definite,
          not like maybe/consider/should.
        - Use reminder for something to remember that is not clearly scheduled.
        - Use task for a concrete action without a reminder time.
        - Use weak_intent for vague maybe/should/consider items.
        - Use knowledge_note for reusable observations, learning, or technique.
        - route_categories must use only these broad categories: calendar,
          health, sports, food, travel, work, projects, relationships, finance,
          shopping, learning, home, system.
        - Keep route_categories broad and generic. Do not use domain-specific
          project labels.
        - evidence should be a short phrase from the transcript supporting the
          extraction.

        Annotation policy:
        - Returning an empty annotations array is normal and preferred for most notes.
        - Add an annotation only when it clearly helps with a likely knowledge gap,
          a well-established concept or viewpoint, an important ambiguity, or a
          claim that needs verification.
        - Do not add generic encouragement, repeat the summary, comment on obvious
          statements, or manufacture a comment just because the field exists.
        - Match the transcript's primary language.
        - Keep each annotation concise and useful.
        - anchor_quote should be a short exact or lightly cleaned phrase from the
          transcript that the annotation comments on.
        - type must be one of: concept, clarification, verification-needed,
          counterpoint.
        - basis must be one of: established-knowledge, model-inference,
          needs-research.
        - Never present changing or uncertain information as established knowledge.
        - For XHS video evidence, distinguish creator speech, visibly observed
          evidence, OCR text, and AI interpretation. Never turn an AI visual
          inference into a claim made by the creator.
        - For tutorials or demonstrations, preserve ordered steps and attach
          timestamps to important actions when timestamps are available.

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
                            "extracted_items": {
                                "type": "array",
                                "items": extracted_item_schema(),
                            },
                            "annotations": {
                                "type": "array",
                                "maxItems": 3,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "title": {"type": "string"},
                                        "type": {
                                            "type": "string",
                                            "enum": [
                                                "concept",
                                                "clarification",
                                                "verification-needed",
                                                "counterpoint",
                                            ],
                                        },
                                        "anchor_quote": {"type": "string"},
                                        "body": {"type": "string"},
                                        "confidence": {
                                            "type": "string",
                                            "enum": ["low", "medium", "high"],
                                        },
                                        "basis": {
                                            "type": "string",
                                            "enum": [
                                                "established-knowledge",
                                                "model-inference",
                                                "needs-research",
                                            ],
                                        },
                                    },
                                    "required": [
                                        "title",
                                        "type",
                                        "anchor_quote",
                                        "body",
                                        "confidence",
                                        "basis",
                                    ],
                                },
                            },
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
                            "annotations",
                            "extracted_items",
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
        "annotations",
        "extracted_items",
        "raw_transcript",
    ]
    for key in required_keys:
        if key not in data:
            if key == "extracted_items":
                data[key] = []
                continue
            raise SystemExit(f"Summary response missing key: {key}")

    data["extracted_items"] = normalize_extracted_items(data.get("extracted_items", []))
    return data


def summarize_transcript(transcript: str, note_date: str, api_key: str) -> dict:
    return summarize_capture(transcript, note_date, "voice", api_key)


def quote_callout_text(value: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in value.splitlines())


def annotations_markdown(annotations: list[dict]) -> str:
    if not annotations:
        return ""

    blocks = ["## AI Comments", ""]
    for annotation in annotations[:3]:
        annotation_type = annotation["type"].replace("-", " ").title()
        title = annotation["title"].strip()
        anchor_quote = annotation["anchor_quote"].strip()
        body = annotation["body"].strip()
        confidence = annotation["confidence"].strip().title()
        basis = annotation["basis"].replace("-", " ").title()

        blocks.append(f"> [!ai-comment]+ AI Comment · {annotation_type}")
        blocks.append(f"> **{title}**")
        if anchor_quote:
            blocks.append(">")
            blocks.append(f'> <span class="ai-comment-anchor">“{anchor_quote}”</span>')
        if body:
            blocks.append(">")
            blocks.append(quote_callout_text(body))
        blocks.append(">")
        blocks.append(
            f'> <span class="ai-comment-meta">Confidence: {confidence} · Basis: {basis}</span>'
        )
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n\n"


def note_markdown(note: dict) -> str:
    topics = "\n".join(f"- {item}" for item in note["topics"]) or "-"
    action_items = "\n".join(f"- {item}" for item in note["action_items"]) or "-"
    people = "\n".join(f"- {item}" for item in note["people"]) or "-"
    links = "\n".join(f"- {topic_link(topic)}" for topic in note["topics"]) or "-"
    extracted_items = normalize_extracted_items(note.get("extracted_items", []))
    source_details = ""
    if note.get("source_url") or note.get("source_author"):
        details = ["## Source", ""]
        if note.get("source_url"):
            details.append(f"- URL: {note['source_url']}")
        if note.get("source_author"):
            details.append(f"- Author: {note['source_author']}")
        if note.get("source_kind"):
            details.append(f"- Content kind: {note['source_kind']}")
        if note.get("source_artifact"):
            details.append(f"- Evidence package: `{note['source_artifact']}`")
        source_details = "\n".join(details) + "\n\n"
    raw_heading = "Raw Transcript" if note["source"] == "voice" else "Imported Content"
    source_frontmatter = ""
    if note.get("source_url"):
        source_frontmatter += (
            f"source_url: {json.dumps(note['source_url'], ensure_ascii=False)}\n"
        )
    if note.get("source_author"):
        source_frontmatter += (
            f"source_author: {json.dumps(note['source_author'], ensure_ascii=False)}\n"
        )
    if note.get("source_kind"):
        source_frontmatter += f"source_kind: {note['source_kind']}\n"
    return (
        f"---\n"
        f"date: {note['date']}\n"
        f"source: {note['source']}\n"
        f"{source_frontmatter}"
        f"topics: {json.dumps(note['topics'], ensure_ascii=False)}\n"
        f"extracted_items: {json.dumps(extracted_items, ensure_ascii=False)}\n"
        f"people: {json.dumps(note['people'], ensure_ascii=False)}\n"
        f"title: {note['title']}\n"
        f"---\n\n"
        f"# {note['title']}\n\n"
        f"## Summary\n\n"
        f"{note['summary']}\n\n"
        f"{annotations_markdown(note.get('annotations', []))}"
        f"## Topics\n\n"
        f"{topics}\n\n"
        f"## Action Items\n\n"
        f"{action_items}\n\n"
        f"{extracted_items_markdown(extracted_items)}"
        f"## People\n\n"
        f"{people}\n\n"
        f"## Links\n\n"
        f"{links}\n\n"
        f"{source_details}"
        f"## {raw_heading}\n\n"
        f"{note['raw_transcript']}\n"
    )


def save_note(note: dict, source_file: Path) -> Path:
    ensure_dirs()
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{note['date']}-{slugify(note['title'])}-{timestamp}.md"
    output_dir = XHS_DIR if note.get("source") == "xhs" else DAILY_DIR
    output_path = output_dir / filename
    output_path.write_text(note_markdown(note), encoding="utf-8")

    index = read_index()
    index.append(
        {
            "date": note["date"],
            "title": note["title"],
            "topics": note["topics"],
            "extracted_items": normalize_extracted_items(note.get("extracted_items", [])),
            "people": note["people"],
            "summary": note["summary"],
            "source": note.get("source", "voice"),
            "source_url": note.get("source_url"),
            "source_kind": note.get("source_kind"),
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
    snippet_files = sorted(SNIPPETS_DIR.glob("*.md"), key=lambda path: path.name.lower())
    report_files = sorted(REVIEWS_DIR.glob("*.md"), key=lambda path: path.name.lower())

    lines = [
        "# Personal Operating System Catalog",
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

    lines.extend(["", "## Snippets", ""])
    if snippet_files:
        for path in snippet_files:
            lines.append(f"- {obsidian_link(path)}: {first_content_line(path)}")
    else:
        lines.append("- No snippets yet.")

    lines.extend(["", "## Maintenance Reports", ""])
    if report_files:
        for path in report_files:
            lines.append(f"- {obsidian_link(path)}: {first_content_line(path)}")
    else:
        lines.append("- No maintenance reports yet.")

    personal_items = [item for item in items if item.get("source", "voice") != "xhs"]
    xhs_items = [item for item in items if item.get("source") == "xhs"]
    lines.extend(["", "## Personal Captures", ""])
    append_catalog_items(lines, personal_items)
    lines.extend(["", "## XHS Knowledge", ""])
    append_catalog_items(lines, xhs_items)

    CATALOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return CATALOG_FILE


def append_catalog_items(lines: list[str], items: list[dict]) -> None:
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
        lines.append("- None yet.")


def vault_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = VOICE_ROOT / path
    resolved = path.resolve()
    try:
        resolved.relative_to(VOICE_ROOT.resolve())
    except ValueError as exc:
        raise SystemExit(f"Refusing to operate outside vault: {path}") from exc
    return resolved


def find_index_item_for_note(note_path: Path) -> tuple[dict, list[dict]]:
    target = path_for_index(note_path)
    items = read_index()
    matches = [item for item in items if item.get("note_file") == target]
    if not matches:
        raise SystemExit(f"Note is not tracked in index.json: {target}")
    if len(matches) > 1:
        raise SystemExit(f"Multiple index entries match note: {target}")
    return matches[0], items


def delete_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def unique_destination(destination_dir: Path, source_path: Path) -> Path:
    destination = destination_dir / source_path.name
    counter = 1
    while destination.exists():
        destination = destination_dir / f"{source_path.stem}-{counter}{source_path.suffix}"
        counter += 1
    return destination


def replace_with_source_bytes(source_path: Path, destination: Path) -> None:
    data = read_source_bytes(source_path)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(destination)
    try:
        source_path.unlink()
    except OSError:
        destination.unlink(missing_ok=True)
        raise


def move_source_file(source_path: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_destination(destination_dir, source_path)
    try:
        shutil.move(str(source_path), str(destination))
        return destination
    except OSError as exc:
        if exc.errno not in MOVE_FALLBACK_ERRNOS:
            raise
        if destination.exists():
            destination.unlink()
        replace_with_source_bytes(source_path, destination)
        return destination


def delete_note(note_path: Path, dry_run: bool = False) -> tuple[Path, Path | None]:
    ensure_dirs()
    resolved_note = vault_path(note_path)
    item, items = find_index_item_for_note(resolved_note)
    raw_source = item.get("source_file")
    source_path = vault_path(raw_source) if raw_source else None

    removed = [
        f"- Note: {path_for_index(resolved_note)}",
    ]
    if source_path:
        removed.append(f"- Source: {path_for_index(source_path)}")

    if dry_run:
        print("Would delete:")
        for line in removed:
            print(line)
        return resolved_note, source_path

    delete_path(resolved_note)
    if source_path:
        delete_path(source_path)

    write_index([entry for entry in items if entry is not item])
    rebuild_catalog()
    append_log("delete", item.get("title", resolved_note.stem), removed)
    print(f"Deleted note: {resolved_note}")
    if source_path:
        print(f"Deleted source: {source_path}")
    return resolved_note, source_path


def resolve_deferred_source(raw_path: Path, source_type: str | None = None) -> Path:
    ensure_dirs()
    candidates = [raw_path]
    if not raw_path.is_absolute():
        candidates.append(DEFERRED_DIR / raw_path)
        if source_type:
            candidates.append(DEFERRED_DIR / normalized_source_type(source_type) / raw_path)
        else:
            for candidate_type in SOURCE_TYPES:
                candidates.append(DEFERRED_DIR / candidate_type / raw_path)

    for candidate in candidates:
        resolved = candidate.expanduser()
        if not resolved.is_absolute():
            resolved = VOICE_ROOT / resolved
        if resolved.exists():
            try:
                resolved.resolve().relative_to(DEFERRED_DIR.resolve())
            except ValueError as exc:
                raise SystemExit(f"Refusing to discard non-deferred file: {resolved}") from exc
            return resolved.resolve()
    raise SystemExit(f"Deferred source not found: {raw_path}")


def discard_deferred(
    source_files: list[Path],
    source_type: str | None = None,
    dry_run: bool = False,
) -> list[Path]:
    if not source_files:
        raise SystemExit("Pass one or more deferred files to discard.")

    discarded: list[Path] = []
    for raw_path in source_files:
        source_path = resolve_deferred_source(raw_path, source_type)
        target_type = source_type or infer_source_type(source_path)
        if dry_run:
            destination = DISCARDED_DIR / normalized_source_type(target_type) / source_path.name
            print(f"Would discard deferred source: {path_for_index(source_path)} -> {path_for_index(destination)}")
            discarded.append(destination)
            continue
        discarded_path = move_to_discarded(source_path, target_type)
        print(f"Discarded deferred source: {discarded_path}")
        discarded.append(discarded_path)
    return discarded


def update_index_item_for_note(note_path: Path, updates: dict) -> None:
    item, items = find_index_item_for_note(note_path)
    item.update({key: value for key, value in updates.items() if value is not None})
    write_index(items)


def correct_note(
    note_path: Path,
    reason: str,
    title: str | None = None,
    summary: str | None = None,
    topics: list[str] | None = None,
    action_items: list[str] | None = None,
    people: list[str] | None = None,
    dry_run: bool = False,
) -> Path:
    ensure_dirs()
    if not reason.strip():
        raise SystemExit("--reason is required for semantic corrections.")
    resolved_note = vault_path(note_path)
    find_index_item_for_note(resolved_note)

    text = resolved_note.read_text(encoding="utf-8")
    correction = apply_note_correction(
        text,
        reason=reason,
        topic_linker=topic_link,
        title=title,
        summary=summary,
        topics=topics,
        action_items=action_items,
        people=people,
    )
    if not correction.changed_fields:
        raise SystemExit("Pass at least one field to correct.")

    if dry_run:
        print(f"Would correct note: {path_for_index(resolved_note)}")
        print(f"Changed fields: {', '.join(correction.changed_fields)}")
        return resolved_note

    resolved_note.write_text(correction.text, encoding="utf-8")
    update_index_item_for_note(resolved_note, correction.index_updates)
    rebuild_catalog()
    append_log(
        "correct",
        resolved_note.stem,
        [
            f"- Note: {obsidian_link(resolved_note)}",
            f"- Reason: {reason.strip()}",
            f"- Updated fields: {', '.join(correction.changed_fields)}",
        ],
    )
    print(f"Corrected note: {resolved_note}")
    return resolved_note


def google_maps_save_queue(
    note_path: Path,
    city: str = "",
    output_path: Path | None = None,
    dry_run: bool = False,
) -> Path:
    ensure_dirs()
    resolved_note = vault_path(note_path)
    note_text = resolved_note.read_text(encoding="utf-8")
    candidates = build_maps_candidates(note_text, city)
    if output_path:
        resolved_output = output_path.expanduser()
        if not resolved_output.is_absolute():
            resolved_output = MAPS_DIR / resolved_output
    else:
        resolved_output = MAPS_DIR / f"{resolved_note.stem}-google-maps-save-queue.md"

    rendered = render_maps_save_markdown(
        source_note=resolved_note,
        source_link=obsidian_link(resolved_note),
        city=city,
        candidates=candidates,
    )
    if dry_run:
        print(rendered)
        return resolved_output

    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(rendered, encoding="utf-8")
    append_log(
        "maps",
        f"Google Maps save queue for {resolved_note.stem}",
        [
            f"- Source note: {obsidian_link(resolved_note)}",
            f"- Output: {path_for_index(resolved_output)}",
            f"- Candidates: {len(candidates)}",
        ],
    )
    print(f"Saved Google Maps queue: {resolved_output}")
    print(f"Candidates: {len(candidates)}")
    return resolved_output


def google_maps_task(
    note_path: Path,
    city: str = "",
    output_path: Path | None = None,
    telegram_preview: bool = False,
) -> Path:
    ensure_dirs()
    resolved_note = vault_path(note_path)
    note_text = resolved_note.read_text(encoding="utf-8")
    candidates = build_maps_candidates(note_text, city)
    if output_path:
        resolved_output = output_path.expanduser()
        if not resolved_output.is_absolute():
            resolved_output = OUTBOX_DIR / "google-maps" / resolved_output
    else:
        resolved_output = OUTBOX_DIR / "google-maps" / f"{resolved_note.stem}-google-maps-task.json"

    payload = maps_task_payload(
        source_note=resolved_note,
        source_path=path_for_index(resolved_note),
        city=city,
        candidates=candidates,
    )
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    append_log(
        "maps-task",
        f"Google Maps task for {resolved_note.stem}",
        [
            f"- Source note: {obsidian_link(resolved_note)}",
            f"- Output: {path_for_index(resolved_output)}",
            f"- Candidates: {len(candidates)}",
        ],
    )
    print(f"Saved Google Maps task: {resolved_output}")
    print(f"Candidates: {len(candidates)}")
    if telegram_preview:
        print(render_telegram_preview(payload))
    return resolved_output


def route_registrations():
    return load_route_registrations(VOICE_ROOT, ROUTES_DIR)


def route_note(
    note_path: Path,
    dry_run: bool = False,
    *,
    strict: bool = True,
    verbose: bool = True,
) -> list[Path]:
    try:
        resolved_note = vault_path(note_path)
        note_item, _ = find_index_item_for_note(resolved_note)
        registrations = route_registrations()
        outputs: list[Path] = []
        extracted_items = normalize_extracted_items(note_item.get("extracted_items", []))
        if extracted_items:
            for item_index, item in enumerate(extracted_items, start=1):
                for registration in registrations:
                    if not item_matches_route(item, note_item, registration):
                        continue
                    output_path = deliver_item_route_package(
                        note_item,
                        resolved_note,
                        registration,
                        item,
                        item_index,
                        dry_run=dry_run,
                    )
                    outputs.append(output_path)
                    if verbose:
                        action = "Would route" if dry_run else "Routed"
                        print(
                            f"{action} item {item_index} from "
                            f"{path_for_index(resolved_note)} -> {output_path}"
                        )
                    if not dry_run:
                        append_log(
                            "route",
                            str(note_item.get("title") or resolved_note.stem),
                            [
                                f"- Source note: {obsidian_link(resolved_note)}",
                                f"- Item: {item.get('item_type')} | {item.get('text')}",
                                f"- Route: {registration.route_id}",
                                f"- Target: {registration.target}",
                                f"- Package: {output_path}",
                            ],
                        )
        else:
            matches = matching_registrations(note_item, registrations)
            for registration in matches:
                output_path = deliver_route_package(
                    note_item,
                    resolved_note,
                    registration,
                    dry_run=dry_run,
                )
                outputs.append(output_path)
                if verbose:
                    action = "Would route" if dry_run else "Routed"
                    print(f"{action} {path_for_index(resolved_note)} -> {output_path}")
                if not dry_run:
                    append_log(
                        "route",
                        str(note_item.get("title") or resolved_note.stem),
                        [
                            f"- Source note: {obsidian_link(resolved_note)}",
                            f"- Route: {registration.route_id}",
                            f"- Target: {registration.target}",
                            f"- Package: {output_path}",
                        ],
                    )
        if verbose and not outputs:
            print(f"No route matched: {path_for_index(resolved_note)}")
        return outputs
    except Exception as exc:
        if strict:
            raise SystemExit(str(exc)) from exc
        append_log(
            "error",
            f"route {note_path}",
            [
                f"- Note: {note_path}",
                f"- Error: {type(exc).__name__}: {exc}",
            ],
        )
        return []


def list_routes() -> list:
    try:
        registrations = route_registrations()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not registrations:
        print("No route registrations found.")
        return registrations
    for registration in registrations:
        print(f"{registration.route_id} -> {registration.target_inbox}")
        print(f"  target: {registration.target}")
        print(f"  manifest: {registration.manifest_path}")
    return registrations


def calendar_candidate_path(note_item: dict, item: dict) -> Path:
    note_stem = slugify(Path(str(note_item.get("note_file", "note"))).stem)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "source_note": note_item.get("note_file"),
                "text": item.get("text"),
                "date_text": item.get("date_text"),
                "time_text": item.get("time_text"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return CALENDAR_OUTBOX_DIR / f"{note_stem}-{fingerprint}.json"


def calendar_outbox(limit: int = 20, dry_run: bool = False) -> list[Path]:
    ensure_dirs()
    if limit <= 0:
        raise SystemExit("--limit must be at least 1.")
    outputs: list[Path] = []
    for note_item in read_index():
        for item in calendar_outbox_candidates(note_item):
            output_path = calendar_candidate_path(note_item, item)
            if output_path.exists() and not dry_run:
                existing = read_json_file(output_path, {})
                if existing.get("version") == 2:
                    continue
            outputs.append(output_path)
            if not dry_run:
                package = build_calendar_candidate(item, note_item)
                write_extracted_json(output_path, package)
                append_log(
                    "calendar-outbox",
                    str(note_item.get("title") or output_path.stem),
                    [
                        f"- Source note: {note_item.get('note_file')}",
                        f"- Candidate: {item.get('text')}",
                        f"- Output: {path_for_index(output_path)}",
                    ],
                )
            if len(outputs) >= limit:
                break
        if len(outputs) >= limit:
            break

    if outputs:
        action = "Would write" if dry_run else "Wrote"
        for output_path in outputs:
            print(f"{action} calendar candidate: {output_path}")
    else:
        print("No calendar-ready extracted items found.")
    return outputs


def calendar_telegram_path(candidate_path: Path) -> Path:
    return CALENDAR_TELEGRAM_DIR / f"{candidate_path.stem}-telegram.json"


def update_candidate(path: Path, candidate: dict) -> None:
    write_extracted_json(path, candidate)


def calendar_dispatch(
    limit: int = 20,
    dry_run: bool = False,
    provider: str | None = None,
) -> list[Path]:
    ensure_dirs()
    if limit <= 0:
        raise SystemExit("--limit must be at least 1.")
    selected_provider = provider or os.environ.get("VOICE_NOTES_CALENDAR_PROVIDER", "json")
    handled: list[Path] = []
    for candidate_path in sorted(CALENDAR_OUTBOX_DIR.glob("*.json")):
        candidate = read_json_file(candidate_path, {})
        status = str(candidate.get("status") or "")
        if status == "needs_telegram_confirmation":
            telegram_path = calendar_telegram_path(candidate_path)
            handled.append(telegram_path)
            if not dry_run and not telegram_path.exists():
                candidate["candidate_path"] = path_for_index(candidate_path)
                write_extracted_json(telegram_path, telegram_confirmation_package(candidate))
                candidate["status"] = "telegram_confirmation_sent"
                candidate["telegram_task"] = path_for_index(telegram_path)
                update_candidate(candidate_path, candidate)
                append_log(
                    "calendar-telegram",
                    str(candidate.get("text") or candidate_path.stem),
                    [
                        f"- Candidate: {path_for_index(candidate_path)}",
                        f"- Telegram task: {path_for_index(telegram_path)}",
                    ],
                )
            action = "Would send Telegram confirmation" if dry_run else "Telegram confirmation task"
            print(f"{action}: {telegram_path}")
        elif status == "ready_to_create":
            handled.append(candidate_path)
            if not dry_run:
                result = create_event(candidate, selected_provider, CALENDAR_CREATED_DIR)
                candidate["status"] = "created"
                candidate["created_with_provider"] = result
                update_candidate(candidate_path, candidate)
                append_log(
                    "calendar-create",
                    str(candidate.get("text") or candidate_path.stem),
                    [
                        f"- Candidate: {path_for_index(candidate_path)}",
                        f"- Provider: {selected_provider}",
                        f"- Event: {result.get('event_id')}",
                    ],
                )
            action = "Would create calendar event" if dry_run else "Created calendar event"
            print(f"{action}: {candidate_path}")
        if len(handled) >= limit:
            break
    if not handled:
        print("No pending calendar candidates to dispatch.")
    return handled


def normalized_source_type(source_type: str | None) -> str:
    return source_type if source_type in SOURCE_TYPES else "voice"


def infer_source_type(source_path: Path) -> str:
    name = source_path.name.lower()
    if source_path.parent.name in SOURCE_TYPES:
        return source_path.parent.name
    if name.startswith("xhs-"):
        return "xhs"
    if name.startswith("shared-capture-"):
        return "bot"
    return "voice"


def archive_source(source_path: Path, source_type: str = "voice") -> Path:
    destination_dir = PROCESSED_DIR / normalized_source_type(source_type)
    return move_source_file(source_path, destination_dir)


def move_to_discarded(source_path: Path, source_type: str = "voice") -> Path:
    ensure_dirs()
    destination_dir = DISCARDED_DIR / normalized_source_type(source_type)
    destination = move_source_file(source_path, destination_dir)
    append_log(
        "discard",
        source_path.name,
        [f"- Discarded source: {path_for_index(destination)}"],
    )
    return destination


def move_to_deferred(source_path: Path, source_type: str, reason: str) -> Path:
    ensure_dirs()
    destination_dir = DEFERRED_DIR / normalized_source_type(source_type)
    destination = move_source_file(source_path, destination_dir)
    append_log(
        "defer",
        source_path.name,
        [
            f"- Deferred source: {path_for_index(destination)}",
            f"- Reason: {reason}",
        ],
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


def source_metadata_from_text(text: str) -> tuple[str | None, str | None]:
    url_match = re.search(r"^Source URL:\s*(\S+)", text, re.MULTILINE)
    author_match = re.search(r"^Author:\s*(.+)$", text, re.MULTILINE)
    return (
        url_match.group(1).strip() if url_match else None,
        author_match.group(1).strip() if author_match else None,
    )


def read_source_text(source_path: Path) -> str:
    return read_source_bytes(source_path).decode("utf-8", errors="replace").strip()


def extract_xhs_url(text: str) -> str | None:
    match = XHS_URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,!?)]}）】")


def is_xhs_share_source(source_path: Path) -> bool:
    if not is_transcript_file(source_path):
        return False
    lowered = source_path.name.lower()
    return any(lowered.startswith(prefix) for prefix in XHS_SHARE_PREFIXES)


def auto_xhs_imports_enabled() -> bool:
    value = os.environ.get("VOICE_NOTES_AUTO_XHS_IMPORTS", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def state_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def xhs_auto_min_interval_seconds() -> int:
    return max(0, env_int("VOICE_NOTES_XHS_AUTO_MIN_INTERVAL_SECONDS", 21600))


def xhs_auto_max_per_day() -> int:
    return max(0, env_int("VOICE_NOTES_XHS_AUTO_MAX_PER_DAY", 2))


def read_json_file(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def write_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def xhs_auto_import_check(now: dt.datetime | None = None) -> tuple[bool, str]:
    if not auto_xhs_imports_enabled():
        return False, "Automatic XHS imports are paused after account warning."

    current = now or dt.datetime.now(dt.timezone.utc)
    state = read_json_file(XHS_AUTO_STATE_FILE, {})
    today = current.date().isoformat()
    count = state_int(state.get("count", 0)) if state.get("date") == today else 0
    max_per_day = xhs_auto_max_per_day()
    if max_per_day <= 0:
        return False, "Automatic XHS imports are disabled by daily limit."
    if count >= max_per_day:
        return False, f"Automatic XHS daily limit reached ({count}/{max_per_day})."

    last_success = state.get("last_success_at")
    if last_success:
        try:
            last_dt = dt.datetime.fromisoformat(str(last_success))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=dt.timezone.utc)
            elapsed = (current - last_dt).total_seconds()
        except ValueError:
            elapsed = None
        min_interval = xhs_auto_min_interval_seconds()
        if elapsed is not None and elapsed < min_interval:
            remaining = int(min_interval - elapsed)
            return False, f"Automatic XHS cooldown active for {remaining}s."

    return True, "Automatic XHS import allowed."


def record_xhs_auto_import(now: dt.datetime | None = None) -> None:
    current = now or dt.datetime.now(dt.timezone.utc)
    state = read_json_file(XHS_AUTO_STATE_FILE, {})
    today = current.date().isoformat()
    count = state_int(state.get("count", 0)) if state.get("date") == today else 0
    write_json_file(
        XHS_AUTO_STATE_FILE,
        {
            "date": today,
            "count": count + 1,
            "last_success_at": current.isoformat(),
        },
    )


def xhs_source_text(imported: dict) -> str:
    source_lines = [f"Source URL: {imported['url']}"]
    if imported.get("title"):
        source_lines.append(f"Original title: {imported['title']}")
    if imported.get("author"):
        source_lines.append(f"Author: {imported['author']}")
    source_lines.extend(["", imported["text"]])
    return "\n".join(source_lines).strip()


def ingest(
    source_path: Path,
    note_date: dt.date | None = None,
    source_type: str | None = None,
) -> Path:
    ensure_dirs()
    if not source_path.exists():
        raise SystemExit(f"Source file not found: {source_path}")
    if source_type is None and is_xhs_share_source(source_path):
        return ingest_xhs_share_source(source_path)
    api_key = require_api_key()
    resolved_date = (note_date or dt.date.today()).isoformat()

    if is_transcript_file(source_path):
        print(f"Reading transcript {source_path.name}...")
        transcript = read_source_text(source_path)
        if not transcript:
            raise SystemExit(f"Transcript file is empty: {source_path}")
    else:
        print(f"Transcribing {source_path.name}...")
        transcript = transcribe(source_path, api_key)["text"]

    resolved_source = source_type or infer_source_type(source_path)
    print("Generating structured note...")
    note = summarize_capture(transcript, resolved_date, resolved_source, api_key)
    note["source"] = resolved_source
    if resolved_source == "xhs":
        source_url, source_author = source_metadata_from_text(transcript)
        note["source_url"] = source_url
        note["source_author"] = source_author
    note["raw_transcript"] = transcript
    return finalize_ingest(note, source_path, resolved_source)


def finalize_ingest(
    note: dict,
    source_path: Path,
    resolved_source: str,
) -> Path:
    archived_path = archive_source(source_path, resolved_source)
    return finalize_archived_ingest(note, archived_path, resolved_source)


def finalize_archived_ingest(
    note: dict,
    archived_path: Path,
    resolved_source: str,
) -> Path:
    if note.get("source_kind") == "video":
        note["source_artifact"] = path_for_index(
            archived_path / "content-package.json"
        )
    output_path = save_note(note, archived_path)
    rebuild_catalog()
    append_log(
        "ingest",
        note["title"],
        [
            f"- Source: {path_for_index(archived_path)}",
            f"- Knowledge note: {obsidian_link(output_path, note['title'])}",
            f"- Topics: {existing_topic_links(note['topics'])}",
        ],
    )
    print(f"Saved note: {output_path}")
    print(f"Archived source: {archived_path}")
    routed = route_note(output_path, strict=False, verbose=False)
    for route_output in routed:
        print(f"Routed note package: {route_output}")
    send_notification(
        note["title"],
        "XHS note imported" if resolved_source == "xhs" else "Voice note parsed",
    )
    return output_path


def finalize_voice_transcript(
    source_paths: list[Path],
    transcripts: list[str],
    note_date: dt.date | None,
    api_key: str,
) -> Path:
    resolved_date = (note_date or dt.date.today()).isoformat()
    transcript = combined_transcript(transcripts)
    print("Generating structured note...")
    note = summarize_capture(transcript, resolved_date, "voice", api_key)
    note["source"] = "voice"
    note["raw_transcript"] = transcript
    if len(source_paths) == 1:
        return finalize_ingest(note, source_paths[0], "voice")
    archived_path = archive_capture_session(
        source_paths,
        processed_voice_dir=PROCESSED_DIR / "voice",
        move_source_file=move_source_file,
    )
    return finalize_archived_ingest(note, archived_path, "voice")


def ingest_voice_sources(
    source_paths: list[Path],
    note_date: dt.date | None = None,
) -> list[Path]:
    if not source_paths:
        return []
    api_key = require_api_key()
    transcripts = []
    for path in source_paths:
        action = "Reading transcript" if is_transcript_file(path) else "Transcribing"
        print(f"{action} {path.name}...")
        transcripts.append(
            read_capture_transcript(
                path,
                api_key=api_key,
                is_transcript_file=is_transcript_file,
                read_source_text=read_source_text,
                transcribe=transcribe,
            )
        )
    continuation_model = os.environ.get(
        "OPENAI_CONTINUATION_MODEL",
        os.environ.get("OPENAI_SUMMARY_MODEL", "gpt-4.1-mini"),
    )
    sessions = split_capture_sessions(
        source_paths,
        transcripts,
        should_merge=lambda previous, next_item: (
            has_explicit_continuation(next_item)
            or model_continuation_decision(
                previous,
                next_item,
                api_key=api_key,
                model=continuation_model,
                api_post_json=api_post_json,
            )
        ),
    )
    return [
        finalize_voice_transcript(paths, texts, note_date, api_key)
        for paths, texts in sessions
    ]


def prepare_xhs_source(
    url: str,
    fallback_text: str | None = None,
    title: str | None = None,
    author: str | None = None,
    imported: dict | None = None,
) -> Path:
    ensure_dirs()
    if fallback_text:
        imported = {
            "url": url,
            "title": title or "",
            "author": author or "",
            "text": fallback_text.strip(),
        }
    elif imported is None:
        print("Fetching XHS note...")
        imported = fetch_xhs_note(url)

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    source_path = INBOX_DIR / f"xhs-{timestamp}.txt"
    source_path.write_text(xhs_source_text(imported) + "\n", encoding="utf-8")
    return source_path


def ingest_xhs(url: str, fallback_text: str | None = None) -> Path:
    imported = None if fallback_text else fetch_xhs_note(url)
    if imported and imported.get("kind") == "video":
        return ingest_xhs_video(imported)
    source_path = prepare_xhs_source(
        url,
        fallback_text,
        imported=imported,
    )
    return ingest(source_path, source_type="xhs")


def image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def analyze_video_frames(frame_records: list[dict], api_key: str) -> list[dict]:
    content: list[dict] = [
        {
            "type": "input_text",
            "text": (
                "Analyze these chronological XHS video frames as evidence. "
                "For each frame, report only clearly visible content and visible "
                "text, then optionally provide a cautious interpretation. Do not "
                "infer creator intent, unseen actions, identities, exact counts, "
                "or claims that the image does not establish."
            ),
        }
    ]
    for record in frame_records:
        content.extend(
            [
                {
                    "type": "input_text",
                    "text": (
                        f"Frame {record['index']} at "
                        f"{record['timestamp']:.3f} seconds"
                    ),
                },
                {
                    "type": "input_image",
                    "image_url": image_data_url(record["path"]),
                    "detail": "high",
                },
            ]
        )
    response = api_post_json(
        "https://api.openai.com/v1/responses",
        payload={
            "model": os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini"),
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "video_frame_evidence",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "events": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "frame_index": {"type": "integer"},
                                        "timestamp": {"type": "number"},
                                        "visible_content": {"type": "string"},
                                        "visible_text": {"type": "string"},
                                        "interpretation": {"type": "string"},
                                    },
                                    "required": [
                                        "frame_index",
                                        "timestamp",
                                        "visible_content",
                                        "visible_text",
                                        "interpretation",
                                    ],
                                },
                            }
                        },
                        "required": ["events"],
                    },
                }
            },
        },
        api_key=api_key,
    )
    try:
        output_text = (
            response.get("output_text")
            or response["output"][0]["content"][0]["text"]
        )
        raw_events = json.loads(output_text)["events"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("Could not parse video frame analysis.") from exc
    authoritative_times = {
        int(record["index"]): float(record["timestamp"])
        for record in frame_records
    }
    events = []
    for event in raw_events:
        frame_index = int(event.get("frame_index", 0))
        if frame_index not in authoritative_times:
            continue
        events.append(
            {
                "frame_index": frame_index,
                "timestamp": authoritative_times[frame_index],
                "visible_content": str(event.get("visible_content", "")).strip(),
                "visible_text": str(event.get("visible_text", "")).strip(),
                "interpretation": str(event.get("interpretation", "")).strip(),
            }
        )
    return sorted(events, key=lambda event: event["timestamp"])


def ingest_xhs_video(
    imported: dict,
    local_video: Path | None = None,
    share_source: Path | None = None,
) -> Path:
    ensure_dirs()
    api_key = require_api_key()
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    bundle_dir = INBOX_DIR / f"xhs-video-{timestamp}"
    bundle_dir.mkdir(parents=True)
    video_path = bundle_dir / "source-video.mp4"
    try:
        if share_source:
            shutil.copy2(share_source, bundle_dir / "share.txt")
        if local_video:
            source = local_video.expanduser().resolve()
            if not source.exists():
                raise SystemExit(f"Video file not found: {source}")
            shutil.copy2(source, video_path)
        else:
            video_url = str(imported.get("video_url") or "")
            if not video_url:
                raise SystemExit(
                    "This post appears to be a video, but no downloadable media URL "
                    "was exposed. Export it locally and pass --video-file."
                )
            print("Downloading XHS video...")
            download_xhs_video(
                video_url,
                video_path,
                referer=str(imported.get("url") or ""),
            )

        print("Extracting timestamped video evidence...")
        package = build_video_content_package(
            video_path=video_path,
            destination_dir=bundle_dir,
            api_key=api_key,
            analyze_frames=analyze_video_frames,
            title=str(imported.get("title") or ""),
            post_text=str(imported.get("text") or ""),
            source_url=str(imported.get("url") or ""),
        )
        evidence = video_evidence_text(
            package,
            author=str(imported.get("author") or ""),
        )
        print("Generating structured video knowledge note...")
        note = summarize_capture(
            evidence,
            dt.date.today().isoformat(),
            "xhs",
            api_key,
        )
        note.update(
            {
                "source": "xhs",
                "source_kind": "video",
                "source_url": imported.get("url"),
                "source_author": imported.get("author"),
                "raw_transcript": evidence,
            }
        )
        return finalize_ingest(note, bundle_dir, "xhs")
    except (Exception, SystemExit):
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        raise


def ingest_xhs_share_source(source_path: Path) -> Path:
    share_text = read_source_text(source_path)
    url = extract_xhs_url(share_text)
    if not url:
        raise SystemExit(
            "XHS share file did not contain an xhslink.com or xiaohongshu.com URL."
        )

    print("Fetching shared XHS note...")
    imported = fetch_xhs_note(url)
    if imported.get("kind") == "video":
        output_path = ingest_xhs_video(imported, share_source=source_path)
        source_path.unlink(missing_ok=True)
        return output_path

    source_path.write_text(xhs_source_text(imported) + "\n", encoding="utf-8")
    return ingest(source_path, source_type="xhs")


def path_is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def defer_xhs_share(source_path: Path, reason: str) -> Path:
    if path_is_under(source_path, DEFERRED_DIR / "xhs"):
        print(f"XHS share already deferred: {source_path} ({reason})")
        return source_path
    deferred_path = move_to_deferred(source_path, "xhs", reason)
    print(f"Deferred XHS share: {deferred_path} ({reason})")
    send_notification(
        f"{source_path.name} moved to deferred/xhs",
        "XHS share deferred",
    )
    return deferred_path


def process_xhs_share_with_safety(source_path: Path) -> bool:
    allowed, reason = xhs_auto_import_check()
    if not allowed:
        defer_xhs_share(source_path, reason)
        return True
    ingest_xhs_share_source(source_path)
    record_xhs_auto_import()
    return True


def process_source_safely(source_path: Path, note_date: dt.date | None = None) -> bool:
    try:
        if is_xhs_share_source(source_path):
            process_xhs_share_with_safety(source_path)
        else:
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
    title = "XHS share failed" if is_xhs_share_source(source_path) else "Voice note failed"
    send_notification(f"{source_path.name}: {error_message}", title)
    return False


def continuation_window_seconds() -> int:
    return max(
        0,
        env_int("VOICE_NOTES_CONTINUATION_WINDOW_SECONDS", 600),
    )


def process_voice_group_safely(
    source_paths: list[Path],
    note_date: dt.date | None = None,
) -> bool:
    try:
        ingest_voice_sources(source_paths, note_date)
        return True
    except SystemExit as exc:
        error_message = str(exc)
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"

    names = ", ".join(path.name for path in source_paths)
    print(f"Failed to process voice capture group {names}: {error_message}")
    append_log(
        "error",
        "voice capture group",
        [
            f"- Sources: {names}",
            f"- Error: {error_message}",
        ],
    )
    send_notification(f"{names}: {error_message}", "Voice note failed")
    return False


def inbox_processing_groups(sources: list[Path]) -> list[list[Path]]:
    return inbox_capture_groups(
        sources,
        max_gap_seconds=continuation_window_seconds(),
        is_voice_source=lambda path: (
            infer_source_type(path) == "voice" and not is_xhs_share_source(path)
        ),
    )


def inbox_sources() -> list[Path]:
    ensure_dirs()
    sources = [
        path
        for path in INBOX_DIR.iterdir()
        if path.is_file() and is_supported_source(path)
    ]
    for source_type in SOURCE_TYPES:
        source_dir = INBOX_DIR / source_type
        sources.extend(
            path
            for path in source_dir.iterdir()
            if path.is_file() and is_supported_source(path)
        )
    return sorted(sources)


def ready_inbox_sources(settle_seconds: int = 0) -> list[Path]:
    ensure_dirs()
    return sorted(
        path for path in inbox_sources() if is_source_ready(path, settle_seconds)
    )


def deferred_sources(source_type: str = "xhs") -> list[Path]:
    ensure_dirs()
    source_dir = DEFERRED_DIR / normalized_source_type(source_type)
    return sorted(
        path
        for path in source_dir.iterdir()
        if path.is_file() and is_supported_source(path)
    )


def process_deferred_xhs(limit: int = 1) -> int:
    if limit <= 0:
        raise SystemExit("--limit must be at least 1.")
    processed = 0
    for source_path in deferred_sources("xhs"):
        allowed, reason = xhs_auto_import_check()
        if not allowed:
            print(f"Deferred XHS processing paused: {reason}")
            break
        try:
            ingest_xhs_share_source(source_path)
            record_xhs_auto_import()
            processed += 1
        except SystemExit as exc:
            print(f"Failed to process deferred XHS share {source_path.name}: {exc}")
            append_log(
                "error",
                source_path.name,
                [
                    f"- Source: {path_for_index(source_path)}",
                    f"- Error: {exc}",
                ],
            )
            break
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            print(f"Failed to process deferred XHS share {source_path.name}: {error_message}")
            append_log(
                "error",
                source_path.name,
                [
                    f"- Source: {path_for_index(source_path)}",
                    f"- Error: {error_message}",
                ],
            )
            break
        if processed >= limit:
            break
    if processed == 0:
        print("No deferred XHS shares processed.")
    else:
        print(f"Processed deferred XHS shares: {processed}")
    return processed


def resolve_inbox_source(raw_path: Path) -> Path:
    if raw_path.exists():
        return raw_path
    inbox_path = INBOX_DIR / raw_path
    if inbox_path.exists():
        return inbox_path
    for source_type in SOURCE_TYPES:
        nested_path = INBOX_DIR / source_type / raw_path
        if nested_path.exists():
            return nested_path
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
        discarded_path = move_to_discarded(
            source_path,
            infer_source_type(source_path),
        )
        print(f"Discarded: {discarded_path}")


def process_inbox(note_date: dt.date | None = None, settle_seconds: int = 0) -> None:
    sources = ready_inbox_sources(settle_seconds)
    if not sources:
        print("No supported files found in inbox.")
        return

    for group in inbox_processing_groups(sources):
        if len(group) > 1 and all(infer_source_type(path) == "voice" for path in group):
            process_voice_group_safely(group, note_date)
        else:
            process_source_safely(group[0], note_date)


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
            for group in inbox_processing_groups(sources):
                if len(group) > 1 and all(
                    infer_source_type(path) == "voice" for path in group
                ):
                    process_voice_group_safely(group, note_date)
                else:
                    process_source_safely(group[0], note_date)
        elif once:
            print("No ready files found in inbox.")

        if once:
            return
        time.sleep(interval_seconds)


def note_dirs_for_scope(scope: str) -> list[Path]:
    if scope == "personal":
        return [DAILY_DIR]
    if scope == "xhs":
        return [XHS_DIR]
    if scope == "all":
        return [DAILY_DIR, XHS_DIR]
    raise ValueError(f"Unsupported scope: {scope}")


def load_note_files_in_range(
    date_from: dt.date,
    date_to: dt.date,
    scope: str = "personal",
    query: str | None = None,
) -> list[Path]:
    files: list[Path] = []
    query_pattern = re.compile(re.escape(query), re.IGNORECASE) if query else None
    for base_dir in note_dirs_for_scope(scope):
        for path in sorted(base_dir.glob("*.md")):
            date_prefix = path.name[:10]
            try:
                note_date = dt.date.fromisoformat(date_prefix)
            except ValueError:
                continue
            if not date_from <= note_date <= date_to:
                continue
            if query_pattern and not query_pattern.search(path.read_text(encoding="utf-8")):
                continue
            files.append(path)
    return files


def period_review(
    date_from: dt.date,
    date_to: dt.date,
    label: str,
    scope: str = "personal",
    query: str | None = None,
    force: bool = False,
) -> Path:
    ensure_dirs()
    filename = f"{date_from}_to_{date_to}_{slugify(label)}_snippet.md"
    output_path = SNIPPETS_DIR / filename
    if output_path.exists() and not force:
        print(f"Snippet already exists, skipping: {output_path}")
        return output_path

    note_files = load_note_files_in_range(date_from, date_to, scope, query)
    if not note_files:
        focus = f" matching {query!r}" if query else ""
        raise SystemExit(
            f"No {scope} notes found between {date_from} and {date_to}{focus}."
        )

    api_key = require_api_key()
    notes_blob = "\n\n".join(path.read_text(encoding="utf-8") for path in note_files)
    model = os.environ.get("OPENAI_SUMMARY_MODEL", "gpt-4.1-mini")
    focus_instruction = (
        f"- Focus only on material relevant to: {query}" if query else
        "- Cover the most important material in the selected period."
    )
    prompt = textwrap.dedent(
        f"""
        Read the following personal knowledge notes and write a {label} snippet
        in Markdown.

        Style:
        - This is a personal weekly snippet, not a project status report.
        - Match the user's dominant language in the selected notes. If most
          notes are Mandarin, write in natural, easy Mandarin.
        - Sound warm, close, and readable, like a thoughtful personal digest.
        - Avoid corporate tone, instruction-manual structure, and inflated
          headings.
        - Prefer a few meaningful sections over exhaustive coverage.

        Review scope: {scope}
        Date range: {date_from} to {date_to}
        {focus_instruction}
        Source fidelity:
        - Do not introduce activities, tools, people, or decisions unless they
          appear in the notes.
        - Do not turn analogies into topics. If a note says something is similar
          to badminton, do not call it badminton practice.
        - If a note title/topic conflicts with its raw transcript, mention the
          uncertainty or follow the raw transcript.
        If the scope is "all", clearly distinguish personal observations from
        imported XHS knowledge. Do not attribute imported claims to the user.

        Include, in a natural format:
        - What seemed to matter emotionally or practically this week
        - Repeated themes
        - Loose ends or things to return to
        - A few topic-note promotion suggestions only if they truly feel durable

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
        raise SystemExit(f"Could not parse snippet response: {json.dumps(response, ensure_ascii=False)}") from exc

    output_path.write_text(review_text + "\n", encoding="utf-8")
    rebuild_catalog()
    append_log(
        "review",
        f"{label.title()} snippet {date_from} to {date_to}",
        [
            f"- Scope: {scope}",
            f"- Snippet: {obsidian_link(output_path)}",
        ],
    )
    return output_path


def weekly_review(
    date_from: dt.date,
    date_to: dt.date,
    scope: str = "personal",
    query: str | None = None,
    force: bool = False,
) -> Path:
    return period_review(date_from, date_to, "weekly", scope, query, force)


def resolve_scheduled_snippet_range(
    period: str,
    today: dt.date | None = None,
) -> tuple[dt.date, dt.date]:
    current = today or dt.date.today()
    if period == "weekly":
        current_week_start = current - dt.timedelta(days=current.weekday())
        date_to = current_week_start - dt.timedelta(days=1)
        date_from = date_to - dt.timedelta(days=6)
        return date_from, date_to
    if period == "monthly":
        return resolve_review_range("monthly", None, None, current)
    raise SystemExit(f"Unsupported scheduled snippet period: {period}")


def scheduled_snippet(period: str, today: dt.date | None = None) -> Path:
    started = dt.datetime.now().isoformat(timespec="seconds")
    print(f"{period}-snippet start: {started}")
    try:
        if period == "weekly":
            date_from, date_to = resolve_scheduled_snippet_range(period, today)
            output_path = weekly_review(date_from, date_to, scope="personal")
        elif period == "monthly":
            date_from, date_to = resolve_scheduled_snippet_range(period, today)
            output_path = period_review(date_from, date_to, "monthly", scope="personal")
        else:
            raise SystemExit(f"Unsupported scheduled snippet period: {period}")
    except SystemExit as exc:
        print(f"{period}-snippet failed: {exc}")
        raise
    except Exception as exc:
        print(f"{period}-snippet failed: {type(exc).__name__}: {exc}")
        raise
    finished = dt.datetime.now().isoformat(timespec="seconds")
    print(f"{period}-snippet saved: {output_path}")
    print(f"{period}-snippet exit=0: {finished}")
    return output_path


def note_source(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines()[:20]:
        if line.startswith("source:"):
            return line.split(":", 1)[1].strip()
    return "voice"


def search_notes(
    query: str,
    scope: str = "all",
) -> list[tuple[Path, int, str]]:
    ensure_dirs()
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results: list[tuple[Path, int, str]] = []
    if scope == "all":
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
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if pattern.search(line):
                    results.append((path, line_number, line.strip()))

    base_dirs = (
        [TOPICS_DIR, REVIEWS_DIR, SNIPPETS_DIR, DAILY_DIR, XHS_DIR]
        if scope == "all"
        else note_dirs_for_scope(scope)
    )
    for base_dir in base_dirs:
        for path in sorted(base_dir.glob("*.md")):
            source = note_source(path)
            if scope == "personal" and source == "xhs":
                continue
            if scope == "xhs" and source != "xhs":
                continue
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
    for base_dir in [TOPICS_DIR, REVIEWS_DIR, SNIPPETS_DIR, DAILY_DIR, XHS_DIR, TEMPLATES_DIR, VOICE_ROOT / "prompts", VOICE_ROOT / "docs"]:
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


def save_text_capture(text: str, prefix: str) -> Path:
    ensure_dirs()
    cleaned = text.strip()
    if not cleaned:
        raise SystemExit("Capture text is empty.")
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output_path = INBOX_DIR / f"{prefix}-{timestamp}.txt"
    output_path.write_text(cleaned + "\n", encoding="utf-8")
    return output_path


def capture_manifest_as_regular_source(manifest_path: Path) -> tuple[Path, str]:
    if not manifest_path.exists():
        raise SystemExit(f"Manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_type = normalized_source_type(str(payload.get("source_type") or "bot"))
    text = str(payload.get("text") or payload.get("body") or "").strip()
    if text:
        source_url = str(payload.get("url") or payload.get("source_uri") or "").strip()
        if source_url:
            text = f"Source: {source_url}\n\n{text}"
        return save_text_capture(text, "shared-capture"), source_type

    files = payload.get("files") or []
    if len(files) == 1:
        source = Path(files[0]).expanduser()
        if not source.is_absolute():
            source = manifest_path.parent / source
        source = source.resolve()
        if source.exists() and is_supported_source(source):
            destination = INBOX_DIR / source.name
            if source != destination:
                shutil.copy2(source, destination)
            return destination, source_type
    raise SystemExit(
        "Manifest compatibility mode requires text/body or one supported local file."
    )


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

    discard_deferred_parser = subparsers.add_parser(
        "discard-deferred",
        help="Move deferred sources that should not be retried to discarded/",
    )
    discard_deferred_parser.add_argument("source_files", nargs="+", type=Path)
    discard_deferred_parser.add_argument(
        "--source-type",
        choices=SOURCE_TYPES,
        default=None,
        help="Resolve filenames under a specific deferred subfolder",
    )
    discard_deferred_parser.add_argument("--dry-run", action="store_true")

    deferred_xhs_parser = subparsers.add_parser(
        "process-deferred-xhs",
        help="Process a limited number of deferred XHS shares when safety gates allow it",
    )
    deferred_xhs_parser.add_argument("--limit", type=int, default=1)

    delete_parser = subparsers.add_parser("delete-note", help="Delete an indexed note and its archived source")
    delete_parser.add_argument("note_file", type=Path)
    delete_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")

    correct_parser = subparsers.add_parser(
        "correct-note",
        help="Apply a semantic correction to an indexed note",
    )
    correct_parser.add_argument("note_file", type=Path)
    correct_parser.add_argument("--reason", required=True)
    correct_parser.add_argument("--title", default=None)
    correct_parser.add_argument("--summary", default=None)
    correct_parser.add_argument(
        "--topic",
        dest="topics",
        action="append",
        default=None,
        help="Correct topics; pass multiple times or comma-separate",
    )
    correct_parser.add_argument(
        "--action-item",
        dest="action_items",
        action="append",
        default=None,
        help="Correct action items; pass multiple times or comma-separate",
    )
    correct_parser.add_argument(
        "--people",
        action="append",
        default=None,
        help="Correct people; pass multiple times or comma-separate",
    )
    correct_parser.add_argument("--dry-run", action="store_true")

    maps_parser = subparsers.add_parser(
        "google-maps-save-queue",
        help="Create a manual Google Maps save queue from an XHS note",
    )
    maps_parser.add_argument("note_file", type=Path)
    maps_parser.add_argument("--city", default="", help="Add a city to each Maps search query")
    maps_parser.add_argument("--output", type=Path, default=None)
    maps_parser.add_argument("--dry-run", action="store_true")

    maps_task_parser = subparsers.add_parser(
        "google-maps-task",
        help="Create a JSON Google Maps save task for OpenClaw/Telegram",
    )
    maps_task_parser.add_argument("note_file", type=Path)
    maps_task_parser.add_argument("--city", default="", help="Add a city to each Maps search query")
    maps_task_parser.add_argument("--output", type=Path, default=None)
    maps_task_parser.add_argument(
        "--telegram-preview",
        action="store_true",
        help="Print a compact Telegram-ready preview after writing the task",
    )

    subparsers.add_parser(
        "list-routes",
        help="List generic note route registrations",
    )

    route_parser = subparsers.add_parser(
        "route-note",
        help="Route a tracked note to matching registered project inboxes",
    )
    route_parser.add_argument("note_file", type=Path)
    route_parser.add_argument("--dry-run", action="store_true")

    review_parser = subparsers.add_parser("weekly-review", help="Legacy alias for weekly-snippet")
    review_parser.add_argument("--from", dest="date_from", type=str, default=None)
    review_parser.add_argument("--to", dest="date_to", type=str, default=None)
    add_review_options(review_parser)

    weekly_snippet_parser = subparsers.add_parser("weekly-snippet", help="Create a weekly personal snippet")
    weekly_snippet_parser.add_argument("--from", dest="date_from", type=str, default=None)
    weekly_snippet_parser.add_argument("--to", dest="date_to", type=str, default=None)
    add_review_options(weekly_snippet_parser)

    monthly_parser = subparsers.add_parser(
        "monthly-review",
        help="Legacy alias for monthly-snippet",
    )
    add_review_options(monthly_parser)

    monthly_snippet_parser = subparsers.add_parser(
        "monthly-snippet",
        help="Create a snippet for the previous calendar month",
    )
    add_review_options(monthly_snippet_parser)

    scheduled_snippet_parser = subparsers.add_parser(
        "scheduled-snippet",
        help="Run a scheduled snippet with cron-friendly logging",
    )
    scheduled_snippet_parser.add_argument("period", choices=["weekly", "monthly"])

    period_parser = subparsers.add_parser(
        "review",
        help="Review a preset or custom time range",
    )
    period_parser.add_argument(
        "--preset",
        choices=["weekly", "monthly", "yearly"],
        default=None,
    )
    period_parser.add_argument("--from", dest="date_from", type=str, default=None)
    period_parser.add_argument("--to", dest="date_to", type=str, default=None)
    period_parser.add_argument("--label", default=None)
    add_review_options(period_parser)

    search_parser = subparsers.add_parser("search", help="Search topic, review, and daily notes")
    search_parser.add_argument("query", type=str)
    search_parser.add_argument(
        "--scope",
        choices=["personal", "xhs", "all"],
        default="all",
        help="Search personal captures, XHS imports, or the whole vault",
    )

    capture_parser = subparsers.add_parser(
        "capture",
        help="Compatibility: convert a text/media manifest into the regular inbox",
    )
    capture_parser.add_argument("--manifest", required=True, type=Path)

    xhs_parser = subparsers.add_parser(
        "capture-xhs",
        help="Fetch an XHS share link and convert it into a knowledge note",
    )
    xhs_parser.add_argument("--url", required=True)
    xhs_parser.add_argument("--text", default=None)
    xhs_parser.add_argument("--text-file", type=Path, default=None)
    xhs_parser.add_argument("--title", default=None)
    xhs_parser.add_argument("--author", default=None)
    xhs_parser.add_argument(
        "--video-file",
        type=Path,
        default=None,
        help="Use an exported local video when XHS does not expose the media URL",
    )
    xhs_parser.add_argument("--note-id", default=None)
    xhs_parser.add_argument("--enqueue-only", action="store_true")

    status_parser = subparsers.add_parser("status", help="Compatibility command; platform state is deferred")
    status_parser.add_argument("capture_id")

    cancel_parser = subparsers.add_parser(
        "cancel",
        help="Compatibility command; use discard-inbox for pending files",
    )
    cancel_parser.add_argument("capture_id")

    calendar_parser = subparsers.add_parser(
        "calendar-outbox",
        help="Write reviewable calendar candidate JSON from extracted items",
    )
    calendar_parser.add_argument("--limit", type=int, default=20)
    calendar_parser.add_argument("--dry-run", action="store_true")

    calendar_dispatch_parser = subparsers.add_parser(
        "calendar-dispatch",
        help="Create ready calendar events or write Telegram confirmation tasks",
    )
    calendar_dispatch_parser.add_argument("--limit", type=int, default=20)
    calendar_dispatch_parser.add_argument("--dry-run", action="store_true")
    calendar_dispatch_parser.add_argument(
        "--provider",
        choices=["json", "apple", "google"],
        default=None,
        help="Calendar provider; defaults to VOICE_NOTES_CALENDAR_PROVIDER or json",
    )

    subparsers.add_parser(
        "calendar-auth-google",
        help="Authorize Google Calendar without creating an event",
    )

    subparsers.add_parser("rebuild-catalog", help="Regenerate catalog.md from vault files")
    subparsers.add_parser("lint-wiki", help="Create a wiki health-check report")
    subparsers.add_parser("test-notification", help="Send a macOS notification without calling OpenAI")
    subparsers.add_parser("init-topics", help="Create default topic note files")
    return parser.parse_args()


def add_review_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scope",
        choices=["personal", "xhs", "all"],
        default="personal",
    )
    parser.add_argument("--query", default=None, help="Only include notes matching this text")
    parser.add_argument("--force", action="store_true", help="Replace an existing snippet")


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


def resolve_review_range(
    preset: str | None,
    raw_from: str | None,
    raw_to: str | None,
    today: dt.date | None = None,
) -> tuple[dt.date, dt.date]:
    if raw_from or raw_to:
        if not raw_from or not raw_to:
            raise SystemExit("Custom reviews require both --from and --to.")
        date_from = dt.date.fromisoformat(raw_from)
        date_to = dt.date.fromisoformat(raw_to)
    else:
        current = today or dt.date.today()
        if preset == "weekly":
            date_from = current - dt.timedelta(days=current.weekday())
            date_to = date_from + dt.timedelta(days=6)
        elif preset == "monthly":
            first_this_month = current.replace(day=1)
            date_to = first_this_month - dt.timedelta(days=1)
            date_from = date_to.replace(day=1)
        elif preset == "yearly":
            year = current.year - 1
            date_from = dt.date(year, 1, 1)
            date_to = dt.date(year, 12, 31)
        else:
            raise SystemExit("Pass --preset weekly|monthly|yearly or both --from and --to.")
    if date_from > date_to:
        raise SystemExit("--from must be on or before --to.")
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

    if args.command == "discard-deferred":
        discard_deferred(args.source_files, args.source_type, args.dry_run)
        return

    if args.command == "process-deferred-xhs":
        process_deferred_xhs(args.limit)
        return

    if args.command == "delete-note":
        delete_note(args.note_file, args.dry_run)
        return

    if args.command == "correct-note":
        correct_note(
            args.note_file,
            reason=args.reason,
            title=args.title,
            summary=args.summary,
            topics=parse_cli_list(args.topics),
            action_items=parse_cli_list(args.action_items),
            people=parse_cli_list(args.people),
            dry_run=args.dry_run,
        )
        return

    if args.command == "google-maps-save-queue":
        google_maps_save_queue(args.note_file, args.city, args.output, args.dry_run)
        return

    if args.command == "google-maps-task":
        google_maps_task(
            args.note_file,
            city=args.city,
            output_path=args.output,
            telegram_preview=args.telegram_preview,
        )
        return

    if args.command == "list-routes":
        list_routes()
        return

    if args.command == "route-note":
        route_note(args.note_file, dry_run=args.dry_run)
        return

    if args.command in {"weekly-review", "weekly-snippet"}:
        date_from, date_to = resolve_date_range(args.date_from, args.date_to)
        output_path = weekly_review(
            date_from,
            date_to,
            args.scope,
            args.query,
            args.force,
        )
        print(f"Saved snippet: {output_path}")
        return

    if args.command in {"monthly-review", "monthly-snippet"}:
        date_from, date_to = resolve_review_range("monthly", None, None)
        output_path = period_review(
            date_from,
            date_to,
            "monthly",
            args.scope,
            args.query,
            args.force,
        )
        print(f"Saved snippet: {output_path}")
        return

    if args.command == "scheduled-snippet":
        scheduled_snippet(args.period)
        return

    if args.command == "review":
        date_from, date_to = resolve_review_range(
            args.preset,
            args.date_from,
            args.date_to,
        )
        label = args.label or args.preset or "custom"
        output_path = period_review(
            date_from,
            date_to,
            label,
            args.scope,
            args.query,
            args.force,
        )
        print(f"Saved snippet: {output_path}")
        return

    if args.command == "search":
        results = search_notes(args.query, args.scope)
        if not results:
            print(f"No matches found for: {args.query}")
            return
        for path, line_number, line in results:
                print(f"{path_for_index(path)}:{line_number}: {line}")
        return

    if args.command == "capture":
        source_path, source_type = capture_manifest_as_regular_source(args.manifest)
        ingest(source_path, source_type=source_type)
        return

    if args.command == "capture-xhs":
        text = args.text
        if args.text_file:
            text = args.text_file.read_text(encoding="utf-8").strip()
        if args.video_file:
            imported = {
                "url": args.url,
                "title": args.title or "",
                "author": args.author or "",
                "text": text or "",
                "kind": "video",
                "video_url": "",
            }
        elif text:
            imported = {
                "url": args.url,
                "title": args.title or "",
                "author": args.author or "",
                "text": text,
                "kind": "article",
                "video_url": "",
            }
        else:
            print("Fetching XHS note...")
            imported = fetch_xhs_note(args.url)

        if imported.get("kind") == "video":
            if args.enqueue_only:
                raise SystemExit(
                    "--enqueue-only is not supported for video captures because "
                    "the evidence bundle must be built atomically."
                )
            ingest_xhs_video(imported, args.video_file)
        else:
            capture_path = prepare_xhs_source(
                args.url,
                text,
                title=args.title,
                author=args.author,
                imported=imported,
            )
            if args.enqueue_only:
                print(f"Queued XHS capture: {capture_path}")
            else:
                ingest(capture_path, source_type="xhs")
        return

    if args.command == "status":
        print(
            "Capture state tracking is deferred in lightweight mode. "
            "Check inbox/, processed/, daily/, xhs/, and log.md."
        )
        return

    if args.command == "cancel":
        print(
            "Capture IDs are not tracked in lightweight mode. "
            "Use discard-inbox --latest or pass the pending inbox filename."
        )
        return

    if args.command == "calendar-outbox":
        calendar_outbox(args.limit, args.dry_run)
        return

    if args.command == "calendar-dispatch":
        calendar_dispatch(args.limit, args.dry_run, args.provider)
        return

    if args.command == "calendar-auth-google":
        result = authorize_google_calendar()
        print(f"Google Calendar authorized for: {result['calendar_id']}")
        print(f"Token saved: {result['token_path']}")
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
        if send_notification("Notifications are working.", "Personal Operating System"):
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
