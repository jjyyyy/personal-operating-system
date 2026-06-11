from __future__ import annotations

import base64
import datetime as dt
import json
import mimetypes
import os
import re
import shutil
import time
from pathlib import Path

from integration_service import route_note
from extracted_items import normalize_extracted_items
from openai_note_service import api_post_json, summarize_capture
from transcription_service import read_source_bytes, transcribe
from video_ingestion import build_video_content_package, video_evidence_text
from voice_note_merging import (
    continuation_decision, local_continuation_signal, merged_recordings,
    merged_source_files, note_date_for_recording, previous_voice_item,
    raw_transcript_from_markdown, source_recorded_at, timestamped_transcript,
)
from voice_notes_config import (
    AUDIO_EXTENSIONS, DAILY_DIR, DEFERRED_DIR, DISCARDED_DIR, INBOX_DIR,
    PROCESSED_DIR, SOURCE_TYPES, STATE_DIR, TEMP_SOURCE_SUFFIXES,
    TRANSCRIPT_EXTENSIONS, VOICE_ROOT, XHS_AUTO_STATE_FILE,
    XHS_SHARE_PREFIXES, XHS_URL_RE, env_int, ensure_dirs, require_api_key,
)
from vault_service import (
    append_log, delete_path, existing_topic_links, find_index_item_for_note, move_source_file,
    note_markdown, obsidian_link, path_for_index, read_index, rebuild_catalog,
    save_note, send_notification, vault_path, write_index,
)
from xhs_import import download_xhs_video, fetch_xhs_note

def normalized_source_type(source_type: str | None) -> str:
    return source_type if source_type in SOURCE_TYPES else "voice"


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
            destination = (
                DISCARDED_DIR / normalized_source_type(target_type) / source_path.name
            )
            print(
                "Would discard deferred source: "
                f"{path_for_index(source_path)} -> {path_for_index(destination)}"
            )
            discarded.append(destination)
            continue
        discarded_path = move_to_discarded(source_path, target_type)
        print(f"Discarded deferred source: {discarded_path}")
        discarded.append(discarded_path)
    return discarded


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


def voice_day_rollover_hour() -> int:
    hour = env_int("VOICE_NOTES_DAY_ROLLOVER_HOUR", 4)
    if not 0 <= hour <= 12:
        raise SystemExit("VOICE_NOTES_DAY_ROLLOVER_HOUR must be between 0 and 12.")
    return hour


def resolved_capture_date(
    source_path: Path,
    source_type: str,
    note_date: dt.date | None,
) -> dt.date:
    if note_date is not None:
        return note_date
    if source_type == "voice":
        return note_date_for_recording(
            source_recorded_at(source_path),
            rollover_hour=voice_day_rollover_hour(),
        )
    return dt.date.today()


def maybe_merge_voice_note(
    current_note_path: Path,
    *,
    api_key: str,
) -> Path:
    current_item, items = find_index_item_for_note(current_note_path)
    previous_item = previous_voice_item(current_item, items)
    if previous_item is None:
        return current_note_path

    previous_path = vault_path(previous_item["note_file"])
    previous_transcript = raw_transcript_from_markdown(
        previous_path.read_text(encoding="utf-8")
    )
    current_transcript = raw_transcript_from_markdown(
        current_note_path.read_text(encoding="utf-8")
    )
    if not previous_transcript or not current_transcript:
        return current_note_path
    shared_topics = {
        str(topic).casefold() for topic in previous_item.get("topics", [])
    } & {
        str(topic).casefold() for topic in current_item.get("topics", [])
    }
    if not local_continuation_signal(current_transcript) and not shared_topics:
        return current_note_path

    model = os.environ.get(
        "OPENAI_CONTINUATION_MODEL",
        os.environ.get("OPENAI_SUMMARY_MODEL", "gpt-4.1-mini"),
    )
    decision = continuation_decision(
        previous_transcript,
        current_transcript,
        api_key=api_key,
        model=model,
        api_post_json=api_post_json,
    )
    if not decision.should_merge:
        return current_note_path

    recordings = merged_recordings(
        previous_item,
        current_item,
        resolve_source=vault_path,
    )
    combined_transcript_text = (
        previous_transcript.rstrip() + "\n\n" + current_transcript.lstrip()
    )

    merged = summarize_capture(
        combined_transcript_text,
        previous_item["date"],
        "voice",
        api_key,
    )
    merged["source"] = "voice"
    merged["raw_transcript"] = combined_transcript_text
    merged["recordings"] = recordings
    merged["extracted_items"] = [
        *previous_item.get("extracted_items", []),
        *current_item.get("extracted_items", []),
    ]
    source_files = merged_source_files(previous_item, current_item)
    merged["source_files"] = source_files

    previous_path.write_text(note_markdown(merged), encoding="utf-8")
    previous_item.update(
        {
            "date": merged["date"],
            "title": merged["title"],
            "topics": merged["topics"],
            "extracted_items": normalize_extracted_items(
                merged.get("extracted_items", [])
            ),
            "people": merged["people"],
            "summary": merged["summary"],
            "source_files": source_files,
            "recordings": recordings,
        }
    )
    delete_path(current_note_path)
    write_index([item for item in items if item is not current_item])
    rebuild_catalog()
    append_log(
        "merge",
        merged["title"],
        [
            f"- Kept note: {obsidian_link(previous_path, merged['title'])}",
            f"- Folded note: {path_for_index(current_note_path)}",
            f"- Signal: {decision.signal}",
            f"- Recordings: {len(recordings)}",
        ],
    )
    print(f"Merged continuation into: {previous_path}")
    return previous_path


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
    resolved_source = source_type or infer_source_type(source_path)
    resolved_date = resolved_capture_date(
        source_path,
        resolved_source,
        note_date,
    ).isoformat()

    if is_transcript_file(source_path):
        print(f"Reading transcript {source_path.name}...")
        transcript = read_source_text(source_path)
        if not transcript:
            raise SystemExit(f"Transcript file is empty: {source_path}")
    else:
        print(f"Transcribing {source_path.name}...")
        transcript = transcribe(source_path, api_key)["text"]

    print("Generating structured note...")
    note = summarize_capture(transcript, resolved_date, resolved_source, api_key)
    note["source"] = resolved_source
    if resolved_source == "xhs":
        source_url, source_author = source_metadata_from_text(transcript)
        note["source_url"] = source_url
        note["source_author"] = source_author
    if resolved_source == "voice":
        recorded_at = source_recorded_at(source_path)
        note["raw_transcript"] = timestamped_transcript([(recorded_at, transcript)])
        note["recordings"] = [{"recorded_at": recorded_at.isoformat()}]
    else:
        note["raw_transcript"] = transcript
    output_path = finalize_ingest(note, source_path, resolved_source)
    if resolved_source == "voice":
        try:
            return maybe_merge_voice_note(output_path, api_key=api_key)
        except (SystemExit, Exception) as exc:
            print(f"Retrospective note merge skipped: {exc}")
            append_log(
                "merge-skip",
                note["title"],
                [
                    f"- Note: {obsidian_link(output_path, note['title'])}",
                    f"- Error: {exc}",
                ],
            )
    return output_path


def finalize_ingest(
    note: dict,
    source_path: Path,
    resolved_source: str,
) -> Path:
    archived_path = archive_source(source_path, resolved_source)
    if resolved_source == "voice":
        recordings = note.get("recordings", [])
        if recordings:
            recordings[-1]["source_file"] = path_for_index(archived_path)
        note["source_files"] = [path_for_index(archived_path)]
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


def ingest_voice_sources(
    source_paths: list[Path],
    note_date: dt.date | None = None,
) -> list[Path]:
    return [ingest(path, note_date, "voice") for path in source_paths]


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
    return [[path] for path in sorted(sources)]


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
