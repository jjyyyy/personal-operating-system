from __future__ import annotations

import datetime as dt
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


VOICE_NOTE_TIMESTAMP_RE = re.compile(
    r"Voice Note - (?P<date>\d{4}-\d{2}-\d{2})-(?P<time>\d{6})",
    re.IGNORECASE,
)
EXPLICIT_CONTINUATION_RE = re.compile(
    r"^\s*(?:\[[^\]\n]+\]\s*)?(?:"
    r"继续(?:说|讲|录)?|接着(?:说|讲)?|再补充(?:一下)?|"
    r"continue|continuing|to continue"
    r")",
    re.IGNORECASE,
)
REFERENTIAL_CONTINUATION_RE = re.compile(
    r"^\s*(?:\[[^\]\n]+\]\s*)?(?:"
    r"刚才(?:说|讲|提到)的?|前面(?:说|讲|提到)的?|"
    r"上一个|还有一个|另外一点|one more thing"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MergeDecision:
    should_merge: bool
    signal: str
    confidence: str


def source_recorded_at(path: Path) -> dt.datetime:
    match = VOICE_NOTE_TIMESTAMP_RE.search(path.stem)
    if match:
        return dt.datetime.strptime(
            f"{match.group('date')} {match.group('time')}",
            "%Y-%m-%d %H%M%S",
        )
    return dt.datetime.fromtimestamp(path.stat().st_mtime)


def note_date_for_recording(
    recorded_at: dt.datetime,
    *,
    rollover_hour: int = 4,
) -> dt.date:
    if not 0 <= rollover_hour <= 12:
        raise ValueError("rollover_hour must be between 0 and 12")
    if recorded_at.hour < rollover_hour:
        return recorded_at.date() - dt.timedelta(days=1)
    return recorded_at.date()


def local_continuation_signal(transcript: str) -> str | None:
    if EXPLICIT_CONTINUATION_RE.search(transcript):
        return "explicit_continuation"
    if REFERENTIAL_CONTINUATION_RE.search(transcript):
        return "referential_continuation"
    return None


def continuation_decision(
    previous_transcript: str,
    next_transcript: str,
    *,
    api_key: str,
    model: str,
    api_post_json: Callable[..., dict],
) -> MergeDecision:
    local_signal = local_continuation_signal(next_transcript)
    if local_signal:
        return MergeDecision(True, local_signal, "high")

    prompt = textwrap.dedent(
        f"""
        Decide whether note 2 should retrospectively merge into note 1.

        There are exactly three valid merge signals:
        1. explicit_continuation: note 2 explicitly says it continues or adds
           to the earlier recording.
        2. referential_continuation: note 2 depends on unresolved references to
           the earlier recording, such as "that point" or "the previous thing".
        3. same_specific_context: both notes clearly describe the same specific
           event, appointment, conversation, class, or train of thought, and
           note 2 completes it rather than starting a separate reflection.

        Time distance is not evidence either way. Similar broad topics are not
        enough. Return none unless the evidence is high confidence.

        Note 1:
        {previous_transcript}

        Note 2:
        {next_transcript}
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
                    "name": "note_merge_decision",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "signal": {
                                "type": "string",
                                "enum": [
                                    "explicit_continuation",
                                    "referential_continuation",
                                    "same_specific_context",
                                    "none",
                                ],
                            },
                            "confidence": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
                        },
                        "required": ["signal", "confidence"],
                    },
                }
            },
        },
        api_key=api_key,
    )
    try:
        output_text = response.get("output_text") or response["output"][0]["content"][0]["text"]
        result = json.loads(output_text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError("Could not parse note merge decision.") from exc
    signal = str(result.get("signal", "none"))
    confidence = str(result.get("confidence", "low"))
    return MergeDecision(
        signal != "none" and confidence == "high",
        signal,
        confidence,
    )


def timestamped_transcript(recordings: list[tuple[dt.datetime, str]]) -> str:
    return "\n\n".join(
        f"[{recorded_at.strftime('%Y-%m-%d %H:%M:%S')}]\n{transcript.strip()}"
        for recorded_at, transcript in recordings
    )


def raw_transcript_from_markdown(text: str) -> str:
    match = re.search(
        r"^## Raw Transcript\n\n(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body").strip() if match else ""


def previous_voice_item(current_item: dict, items: list[dict]) -> dict | None:
    current_index = items.index(current_item)
    for item in reversed(items[:current_index]):
        if item.get("source") == "voice":
            return item
    return None


def merged_recordings(
    previous_item: dict,
    current_item: dict,
    *,
    resolve_source: Callable[[str], Path],
) -> list[dict]:
    recordings = [
        *previous_item.get("recordings", []),
        *current_item.get("recordings", []),
    ]
    if recordings:
        return recordings
    fallback = []
    for item in (previous_item, current_item):
        source_file = item.get("source_file")
        if source_file:
            fallback.append(
                {
                    "recorded_at": source_recorded_at(
                        resolve_source(source_file)
                    ).isoformat(),
                    "source_file": source_file,
                }
            )
    return fallback


def merged_source_files(previous_item: dict, current_item: dict) -> list[str]:
    sources = [
        *(previous_item.get("source_files") or [previous_item.get("source_file")]),
        *(current_item.get("source_files") or [current_item.get("source_file")]),
    ]
    return list(dict.fromkeys(path for path in sources if path))
