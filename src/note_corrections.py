from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class CorrectionResult:
    text: str
    changed_fields: list[str]
    index_updates: dict


def parse_cli_list(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    parsed: list[str] = []
    for value in values:
        parsed.extend(item.strip() for item in value.split(",") if item.strip())
    return parsed


def list_markdown(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "-"


def replace_frontmatter_value(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            break
        if lines[index].startswith(f"{key}:"):
            lines[index] = f"{key}: {value}"
            return "\n".join(lines) + "\n"
    return text


def replace_heading_block(text: str, heading: str, body: str) -> str:
    pattern = re.compile(
        rf"(^## {re.escape(heading)}\n\n)(.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    replacement = f"## {heading}\n\n{body.strip()}\n\n"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)

    raw_match = re.search(r"^## (Raw Transcript|Imported Content)\n\n", text, re.MULTILINE)
    if raw_match:
        return text[: raw_match.start()] + replacement + text[raw_match.start() :]
    return text.rstrip() + "\n\n" + replacement


def replace_title_blocks(text: str, title: str) -> str:
    updated = replace_frontmatter_value(text, "title", title)
    return re.sub(r"^# .+$", f"# {title}", updated, count=1, flags=re.MULTILINE)


def append_correction_block(
    text: str,
    reason: str,
    changed_fields: list[str],
    today: dt.date | None = None,
) -> str:
    correction_date = today or dt.date.today()
    lines = [
        f"- {correction_date.isoformat()}: {reason.strip()}",
        f"  - Updated fields: {', '.join(changed_fields)}",
    ]
    existing = re.search(
        r"(^## Corrections\n\n)(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if existing:
        body = existing.group(2).rstrip()
        new_body = body + ("\n" if body else "") + "\n".join(lines)
        return (
            text[: existing.start()]
            + "## Corrections\n\n"
            + new_body
            + "\n\n"
            + text[existing.end() :]
        )
    return replace_heading_block(text, "Corrections", "\n".join(lines))


def apply_note_correction(
    text: str,
    reason: str,
    topic_linker: Callable[[str], str],
    title: str | None = None,
    summary: str | None = None,
    topics: list[str] | None = None,
    action_items: list[str] | None = None,
    people: list[str] | None = None,
    today: dt.date | None = None,
) -> CorrectionResult:
    changed_fields: list[str] = []
    index_updates: dict = {}

    if title:
        text = replace_title_blocks(text, title)
        changed_fields.append("title")
        index_updates["title"] = title
    if summary:
        text = replace_heading_block(text, "Summary", summary)
        changed_fields.append("summary")
        index_updates["summary"] = summary
    if topics is not None:
        text = replace_frontmatter_value(text, "topics", json.dumps(topics, ensure_ascii=False))
        text = replace_heading_block(text, "Topics", list_markdown(topics))
        text = replace_heading_block(
            text,
            "Links",
            "\n".join(f"- {topic_linker(topic)}" for topic in topics) or "-",
        )
        changed_fields.append("topics")
        index_updates["topics"] = topics
    if action_items is not None:
        text = replace_heading_block(text, "Action Items", list_markdown(action_items))
        changed_fields.append("action_items")
    if people is not None:
        text = replace_frontmatter_value(text, "people", json.dumps(people, ensure_ascii=False))
        text = replace_heading_block(text, "People", list_markdown(people))
        changed_fields.append("people")
        index_updates["people"] = people

    if changed_fields:
        text = append_correction_block(text, reason, changed_fields, today)
    return CorrectionResult(text, changed_fields, index_updates)
