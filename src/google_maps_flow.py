from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GOOGLE_MAPS_LISTS = (
    "Brunch",
    "Bakery",
    "吃-Travel",
    "coffee",
    "Shops",
    "旅行",
    "Gelato",
    "Travel plans",
    "喝",
)


@dataclass
class MapsCandidate:
    name: str
    description: str
    list_name: str
    tag: str
    query_url: str


def imported_content(text: str) -> str:
    for heading in ("## Imported Content", "## Raw Transcript"):
        marker = f"{heading}\n\n"
        if marker in text:
            return text.split(marker, 1)[1].strip()
    return text.strip()


def extract_numbered_places(text: str) -> list[tuple[str, str]]:
    content = imported_content(text)
    entries: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    current_lines: list[str] = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^p\d+(?:-\d+)?\s+(.+)$", line, re.IGNORECASE)
        if match:
            if current_name:
                entries.append((current_name, current_lines))
            current_name = match.group(1).strip()
            current_lines = []
            continue
        if current_name:
            current_lines.append(line)

    if current_name:
        entries.append((current_name, current_lines))
    return [(name, " ".join(lines).strip()) for name, lines in entries]


def classify_place(name: str, description: str) -> tuple[str, str]:
    name_text = name.lower()
    description_text = description.lower()
    text = f"{name_text} {description_text}"
    restaurant_terms = ("restaurant", "tapas", "thai", "自助餐", "海鲜饭", "pad thai")
    if any(token in text for token in ("gelato", "ice cream", "冰淇淋", "酸奶冰淇淋")):
        return "Gelato", "冰淇淋"
    if (
        "bakery" in name_text
        or any(token in text for token in ("croissant", "可颂", "甜品", "巧克力", "榛果", "糯米糍", "pastry"))
        or ("面包" in text and not any(token in text for token in restaurant_terms))
    ):
        return "Bakery", "烘焙"
    if any(token in text for token in ("brunch", "breakfast", "早午餐")):
        return "Brunch", "brunch"
    if any(token in text for token in restaurant_terms):
        return "吃-Travel", "餐厅"
    if any(token in text for token in ("sandwich", "三明治")):
        return "吃-Travel", "餐厅"
    if any(token in text for token in ("coffee", "cafe", "café", "latte", "拿铁", "咖啡")) and "难喝" not in text:
        return "coffee", "咖啡"
    if any(token in text for token in ("奶茶", "茶", "thai tea", "drink", "饮品")):
        return "喝", "饮品"
    if any(token in text for token in ("shop", "store", "买", "购物")):
        return "Shops", "店"
    return "吃-Travel", "餐厅"


def maps_search_url(name: str, city: str = "") -> str:
    query = f"{name} {city}".strip()
    encoded = urllib.parse.quote_plus(query)
    return f"https://www.google.com/maps/search/?api=1&query={encoded}"


def build_maps_candidates(note_text: str, city: str = "") -> list[MapsCandidate]:
    candidates: list[MapsCandidate] = []
    for name, description in extract_numbered_places(note_text):
        list_name, tag = classify_place(name, description)
        candidates.append(
            MapsCandidate(
                name=name,
                description=description,
                list_name=list_name,
                tag=tag,
                query_url=maps_search_url(name, city),
            )
        )
    return candidates


def render_maps_save_markdown(
    source_note: Path,
    source_link: str,
    city: str,
    candidates: list[MapsCandidate],
) -> str:
    lines = [
        f"# Google Maps Save Queue: {source_note.stem}",
        "",
        f"- Source note: {source_link}",
        f"- City/search suffix: {city or 'none'}",
        "- Workflow: open each Google Maps link, verify the place, save to the suggested list, then mark it done.",
        "",
        "## Google Maps Lists",
        "",
    ]
    for list_name in GOOGLE_MAPS_LISTS:
        lines.append(f"- {list_name}")

    lines.extend(["", "## Candidates", ""])
    if not candidates:
        lines.append("- No numbered XHS place candidates found.")
    for candidate in candidates:
        description = candidate.description or "No description captured."
        lines.extend(
            [
                f"### {candidate.name}",
                "",
                "- Status: pending",
                f"- Google Maps: [{candidate.name}]({candidate.query_url})",
                f"- Suggested list: {candidate.list_name}",
                f"- Suggested tag: {candidate.tag}",
                f"- Source note: {source_link}",
                f"- XHS context: {description}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def candidate_id(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", name.lower()).strip("-")
    return cleaned or "place"


def maps_task_payload(
    source_note: Path,
    source_path: str,
    city: str,
    candidates: list[MapsCandidate],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "type": "google_maps_save_queue",
        "version": 1,
        "created_at": now,
        "source_note": source_path,
        "city": city,
        "status": "pending",
        "instructions": (
            "Send these candidates through the OpenClaw main agent's Telegram "
            "channel. The user opens Maps manually, saves the place manually, "
            "then marks each candidate saved or skipped."
        ),
        "candidates": [
            {
                "id": f"{candidate_id(candidate.name)}-{index:02d}",
                "status": "pending",
                "name": candidate.name,
                "maps_url": candidate.query_url,
                "suggested_list": candidate.list_name,
                "suggested_tag": candidate.tag,
                "context": candidate.description,
                "source_note": source_path,
            }
            for index, candidate in enumerate(candidates, start=1)
        ],
        "source_title": source_note.stem,
    }


def render_telegram_preview(payload: dict[str, Any], limit: int = 5) -> str:
    candidates = payload.get("candidates", [])
    lines = [
        f"Google Maps 保存候选 · {payload.get('city') or 'no city'}",
        f"来源: {payload.get('source_note')}",
        f"候选: {len(candidates)}",
        "",
    ]
    for index, candidate in enumerate(candidates[:limit], start=1):
        lines.extend(
            [
                f"{index}. {candidate['name']}",
                f"List: {candidate['suggested_list']} · Tag: {candidate['suggested_tag']}",
                candidate["maps_url"],
                "",
            ]
        )
    if len(candidates) > limit:
        lines.append(f"...还有 {len(candidates) - limit} 个候选")
    return "\n".join(lines).strip()
