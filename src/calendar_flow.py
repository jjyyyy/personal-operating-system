from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from google_calendar_provider import create_google_calendar_event


DEFAULT_TIMEZONE = "Europe/Madrid"
DEFAULT_DURATION_MINUTES = 60


def calendar_timezone() -> str:
    return os.environ.get("VOICE_NOTES_CALENDAR_TIMEZONE", DEFAULT_TIMEZONE)


def calendar_duration_minutes() -> int:
    try:
        return max(1, int(os.environ.get("VOICE_NOTES_CALENDAR_DEFAULT_DURATION_MINUTES", "60")))
    except ValueError:
        return DEFAULT_DURATION_MINUTES


def parse_time_text(*values: str | None) -> tuple[int, int] | None:
    text = " ".join(value or "" for value in values).lower()
    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if match:
        return int(match.group(1)), int(match.group(2))

    match = re.search(r"(\d{1,2})\s*(?:点|時|时)", text)
    if match:
        hour = int(match.group(1))
        if any(token in text for token in ("下午", "晚上", "pm")) and hour < 12:
            hour += 12
        if any(token in text for token in ("上午", "早上", "am")) and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            return hour, 0

    match = re.search(r"\b(\d{1,2})\s*(am|pm)\b", text)
    if match:
        hour = int(match.group(1))
        if match.group(2) == "pm" and hour < 12:
            hour += 12
        if match.group(2) == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            return hour, 0
    return None


def parse_date_text(note_date: str, *values: str | None) -> dt.date | None:
    base = dt.date.fromisoformat(note_date)
    text = " ".join(value or "" for value in values).lower()
    if any(token in text for token in ("明天", "tomorrow")):
        return base + dt.timedelta(days=1)
    if any(token in text for token in ("今天", "今晚", "today", "tonight")):
        return base
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if match:
        return dt.date.fromisoformat(match.group(1))
    return None


def resolve_event_times(
    item: dict[str, Any],
    note_date: str,
    *,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    timezone = timezone_name or calendar_timezone()
    event_date = parse_date_text(note_date, item.get("date_text"), item.get("time_text"), item.get("text"))
    event_time = parse_time_text(item.get("time_text"), item.get("date_text"), item.get("text"))
    if not event_date or not event_time:
        return {
            "resolved": False,
            "timezone": timezone,
            "reason": "Could not resolve date or time deterministically.",
        }
    zone = ZoneInfo(timezone)
    start = dt.datetime.combine(event_date, dt.time(event_time[0], event_time[1]), tzinfo=zone)
    end = start + dt.timedelta(minutes=calendar_duration_minutes())
    return {
        "resolved": True,
        "timezone": timezone,
        "start_datetime": start.isoformat(),
        "end_datetime": end.isoformat(),
        "duration_minutes": calendar_duration_minutes(),
    }


def confirmation_required(item: dict[str, Any], resolved: dict[str, Any]) -> bool:
    return (
        item.get("confidence") != "high"
        or item.get("needs_confirmation") is True
        or item.get("calendar_ready") is not True
        or resolved.get("resolved") is not True
    )


def build_calendar_candidate(
    item: dict[str, Any],
    note_item: dict[str, Any],
) -> dict[str, Any]:
    resolved = resolve_event_times(item, str(note_item.get("date")))
    requires_confirmation = confirmation_required(item, resolved)
    status = "needs_telegram_confirmation" if requires_confirmation else "ready_to_create"
    return {
        "type": "voice_notes_calendar_candidate",
        "version": 2,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": status,
        "confirmation_channel": "telegram" if requires_confirmation else None,
        "source_project": "voice-notes",
        "source_note": note_item.get("note_file"),
        "source_file": note_item.get("source_file"),
        "source_title": note_item.get("title"),
        "item_type": item["item_type"],
        "text": item["text"],
        "date_text": item.get("date_text"),
        "time_text": item.get("time_text"),
        "confidence": item.get("confidence"),
        "calendar_ready": item.get("calendar_ready"),
        "needs_confirmation": item.get("needs_confirmation"),
        "evidence": item.get("evidence"),
        "event": {
            "title": item["text"],
            "timezone": resolved.get("timezone"),
            "start_datetime": resolved.get("start_datetime"),
            "end_datetime": resolved.get("end_datetime"),
            "duration_minutes": resolved.get("duration_minutes"),
            "resolved": resolved.get("resolved") is True,
            "resolution_note": resolved.get("reason"),
        },
        "instructions": (
            "High-confidence resolved events may be created automatically. "
            "If confirmation is required, send this candidate through Telegram."
        ),
    }


def telegram_confirmation_package(candidate: dict[str, Any]) -> dict[str, Any]:
    event = candidate.get("event", {})
    return {
        "type": "voice_notes_calendar_confirmation",
        "version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "pending_telegram",
        "source_candidate": candidate.get("candidate_path"),
        "title": candidate.get("text"),
        "start_datetime": event.get("start_datetime"),
        "end_datetime": event.get("end_datetime"),
        "timezone": event.get("timezone"),
        "source_note": candidate.get("source_note"),
        "message": render_telegram_confirmation(candidate),
        "actions": ["approve", "skip", "edit"],
    }


def render_telegram_confirmation(candidate: dict[str, Any]) -> str:
    event = candidate.get("event", {})
    when = event.get("start_datetime") or f"{candidate.get('date_text') or ''} {candidate.get('time_text') or ''}".strip()
    return "\n".join(
        [
            "Calendar confirmation needed",
            f"Title: {candidate.get('text')}",
            f"When: {when or 'unresolved'}",
            f"Confidence: {candidate.get('confidence')}",
            f"Source: {candidate.get('source_note')}",
            "",
            "Reply approve, skip, or edit with corrected details.",
        ]
    ).strip()


def create_event(candidate: dict[str, Any], provider: str, created_dir: Path) -> dict[str, Any]:
    if provider == "apple":
        return create_apple_calendar_event(candidate)
    if provider == "google":
        return create_google_calendar_event(candidate)
    if provider == "json":
        return create_json_calendar_event(candidate, created_dir)
    raise ValueError(f"unsupported calendar provider: {provider}")


def create_json_calendar_event(candidate: dict[str, Any], created_dir: Path) -> dict[str, Any]:
    created_dir.mkdir(parents=True, exist_ok=True)
    output_path = created_dir / f"{Path(str(candidate.get('source_note') or 'event')).stem}-{candidate.get('created_at', '').replace(':', '')}.json"
    payload = {
        "type": "voice_notes_created_calendar_event",
        "provider": "json",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "candidate": candidate,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"provider": "json", "event_id": str(output_path), "status": "created"}


def create_apple_calendar_event(candidate: dict[str, Any]) -> dict[str, Any]:
    event = candidate.get("event", {})
    if not event.get("start_datetime") or not event.get("end_datetime"):
        raise ValueError("candidate event is not resolved")
    start = dt.datetime.fromisoformat(str(event["start_datetime"]))
    end = dt.datetime.fromisoformat(str(event["end_datetime"]))
    calendar_name = os.environ.get("VOICE_NOTES_APPLE_CALENDAR", "Calendar")
    script = """
on run argv
  set eventTitle to item 1 of argv
  set startDate to current date
  set year of startDate to (item 2 of argv as integer)
  set month of startDate to (item 3 of argv as integer)
  set day of startDate to (item 4 of argv as integer)
  set time of startDate to (((item 5 of argv as integer) * hours) + ((item 6 of argv as integer) * minutes))
  set endDate to current date
  set year of endDate to (item 7 of argv as integer)
  set month of endDate to (item 8 of argv as integer)
  set day of endDate to (item 9 of argv as integer)
  set time of endDate to (((item 10 of argv as integer) * hours) + ((item 11 of argv as integer) * minutes))
  set notesText to item 12 of argv
  set calendarName to item 13 of argv
  tell application "Calendar"
    tell calendar calendarName
      set newEvent to make new event with properties {summary:eventTitle, start date:startDate, end date:endDate, description:notesText}
      return uid of newEvent
    end tell
  end tell
end run
"""
    result = subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            script,
            str(candidate.get("text") or "Event"),
            str(start.year),
            str(start.month),
            str(start.day),
            str(start.hour),
            str(start.minute),
            str(end.year),
            str(end.month),
            str(end.day),
            str(end.hour),
            str(end.minute),
            f"Source: {candidate.get('source_note')}\nEvidence: {candidate.get('evidence') or ''}",
            calendar_name,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return {"provider": "apple", "event_id": result.stdout.strip(), "status": "created"}
