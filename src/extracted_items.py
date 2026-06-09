from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


ITEM_TYPES = (
    "calendar_event",
    "reminder",
    "task",
    "weak_intent",
    "knowledge_note",
)
ROUTE_CATEGORIES = (
    "calendar",
    "health",
    "sports",
    "food",
    "travel",
    "work",
    "projects",
    "relationships",
    "finance",
    "shopping",
    "learning",
    "home",
    "system",
)
CONFIDENCE_LEVELS = ("low", "medium", "high")


def extracted_item_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "item_type": {"type": "string", "enum": list(ITEM_TYPES)},
            "text": {"type": "string"},
            "date_text": {"type": ["string", "null"]},
            "time_text": {"type": ["string", "null"]},
            "route_categories": {
                "type": "array",
                "items": {"type": "string", "enum": list(ROUTE_CATEGORIES)},
            },
            "calendar_ready": {"type": "boolean"},
            "needs_confirmation": {"type": "boolean"},
            "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
            "evidence": {"type": "string"},
        },
        "required": [
            "item_type",
            "text",
            "date_text",
            "time_text",
            "route_categories",
            "calendar_ready",
            "needs_confirmation",
            "confidence",
            "evidence",
        ],
    }


def normalize_extracted_items(items: object) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        item_type = str(raw_item.get("item_type") or "").strip()
        text = str(raw_item.get("text") or "").strip()
        confidence = str(raw_item.get("confidence") or "").strip()
        if item_type not in ITEM_TYPES or confidence not in CONFIDENCE_LEVELS or not text:
            continue
        route_categories = [
            str(category)
            for category in raw_item.get("route_categories", [])
            if str(category) in ROUTE_CATEGORIES
        ]
        normalized.append(
            {
                "item_type": item_type,
                "text": text,
                "date_text": nullable_text(raw_item.get("date_text")),
                "time_text": nullable_text(raw_item.get("time_text")),
                "route_categories": route_categories,
                "calendar_ready": bool(raw_item.get("calendar_ready", False)),
                "needs_confirmation": bool(raw_item.get("needs_confirmation", True)),
                "confidence": confidence,
                "evidence": str(raw_item.get("evidence") or "").strip(),
            }
        )
    return normalized


def nullable_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def extracted_items_markdown(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = ["## Extracted Items", ""]
    for index, item in enumerate(items, start=1):
        categories = ", ".join(item.get("route_categories", [])) or "none"
        lines.extend(
            [
                f"### {index}. {item['item_type'].replace('_', ' ').title()}",
                "",
                f"- Text: {item['text']}",
                f"- Categories: {categories}",
                f"- Date text: {item.get('date_text') or 'none'}",
                f"- Time text: {item.get('time_text') or 'none'}",
                f"- Calendar ready: {str(bool(item.get('calendar_ready'))).lower()}",
                f"- Needs confirmation: {str(bool(item.get('needs_confirmation'))).lower()}",
                f"- Confidence: {item.get('confidence', 'low')}",
            ]
        )
        if item.get("evidence"):
            lines.append(f"- Evidence: {item['evidence']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n\n"


def calendar_outbox_package(
    item: dict[str, Any],
    source_note: str,
    source_file: str | None,
    note_title: str,
) -> dict[str, Any]:
    return {
        "type": "voice_notes_calendar_candidate",
        "version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "needs_review",
        "source_project": "voice-notes",
        "source_note": source_note,
        "source_file": source_file,
        "source_title": note_title,
        "item_type": item["item_type"],
        "text": item["text"],
        "date_text": item.get("date_text"),
        "time_text": item.get("time_text"),
        "confidence": item.get("confidence"),
        "evidence": item.get("evidence"),
        "instructions": (
            "Review this candidate before creating a Google Calendar event. "
            "Only schedule it after confirming the intended date, time, and title."
        ),
    }


def calendar_outbox_candidates(note_item: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for item in normalize_extracted_items(note_item.get("extracted_items", [])):
        if (
            item.get("item_type") == "calendar_event"
            and item.get("calendar_ready") is True
            and item.get("needs_confirmation") is False
            and item.get("confidence") == "high"
        ):
            candidates.append(item)
    return candidates


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
