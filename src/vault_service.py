from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path

from extracted_items import extracted_items_markdown, normalize_extracted_items
from note_corrections import apply_note_correction
from openai_note_service import annotations_markdown
from transcription_service import read_source_bytes
from voice_notes_config import (
    CATALOG_FILE, DAILY_DIR, DEFERRED_DIR, DISCARDED_DIR, INDEX_FILE, LOG_FILE,
    MOVE_FALLBACK_ERRNOS, PROCESSED_DIR, REVIEWS_DIR, SNIPPETS_DIR,
    SOURCE_TYPES, TOPICS_DIR, VOICE_ROOT, XHS_DIR, ensure_dirs,
)

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
    recordings_frontmatter = ""
    if note.get("recordings"):
        recordings_frontmatter = (
            f"recordings: {json.dumps(note['recordings'], ensure_ascii=False)}\n"
        )
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
        f"{recordings_frontmatter}"
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
    output_path = unique_destination(output_dir, Path(filename))
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
            "source_files": note.get("source_files", [path_for_index(source_file)]),
            "recordings": note.get("recordings", []),
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
    raw_sources = item.get("source_files") or [item.get("source_file")]
    source_paths = [vault_path(raw) for raw in raw_sources if raw]
    source_path = source_paths[0] if source_paths else None

    removed = [
        f"- Note: {path_for_index(resolved_note)}",
    ]
    for path in source_paths:
        removed.append(f"- Source: {path_for_index(path)}")

    if dry_run:
        print("Would delete:")
        for line in removed:
            print(line)
        return resolved_note, source_path

    delete_path(resolved_note)
    for path in source_paths:
        delete_path(path)

    write_index([entry for entry in items if entry is not item])
    rebuild_catalog()
    append_log("delete", item.get("title", resolved_note.stem), removed)
    print(f"Deleted note: {resolved_note}")
    for path in source_paths:
        print(f"Deleted source: {path}")
    return resolved_note, source_path


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
