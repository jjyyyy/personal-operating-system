from __future__ import annotations

import datetime as dt
import json
import re
import textwrap
from pathlib import Path
from typing import Callable


VOICE_NOTE_TIMESTAMP_RE = re.compile(
    r"Voice Note - (?P<date>\d{4}-\d{2}-\d{2})-(?P<time>\d{6})",
    re.IGNORECASE,
)
CONTINUATION_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"继续(?:说|讲|录|刚才|上一个)?|"
    r"接着(?:说|讲|刚才)?|"
    r"刚才(?:说|讲|提到)的?|"
    r"还有一个|"
    r"再补充(?:一下)?|"
    r"continue|continuing|to continue|one more thing"
    r")",
    re.IGNORECASE,
)


def source_recorded_at(path: Path) -> dt.datetime:
    match = VOICE_NOTE_TIMESTAMP_RE.search(path.stem)
    if match:
        return dt.datetime.strptime(
            f"{match.group('date')} {match.group('time')}",
            "%Y-%m-%d %H%M%S",
        )
    return dt.datetime.fromtimestamp(path.stat().st_mtime)


def group_nearby_voice_sources(
    sources: list[Path],
    *,
    max_gap_seconds: int,
) -> list[list[Path]]:
    if not sources:
        return []
    ordered = sorted(sources, key=source_recorded_at)
    groups: list[list[Path]] = [[ordered[0]]]
    for source in ordered[1:]:
        previous = groups[-1][-1]
        gap = (source_recorded_at(source) - source_recorded_at(previous)).total_seconds()
        if 0 <= gap <= max_gap_seconds:
            groups[-1].append(source)
        else:
            groups.append([source])
    return groups


def has_explicit_continuation(transcript: str) -> bool:
    return CONTINUATION_PREFIX_RE.search(transcript) is not None


def combined_transcript(transcripts: list[str]) -> str:
    if len(transcripts) == 1:
        return transcripts[0].strip()
    sections = []
    for index, transcript in enumerate(transcripts, start=1):
        sections.append(f"[Recording {index}]\n{transcript.strip()}")
    return "\n\n".join(sections)


def model_continuation_decision(
    previous_transcript: str,
    next_transcript: str,
    *,
    api_key: str,
    model: str,
    api_post_json: Callable[..., dict],
) -> bool:
    prompt = textwrap.dedent(
        f"""
        Decide whether recording 2 is a continuation of the same thought,
        event, conversation, or activity described in recording 1.

        Return true only when they should become one personal daily note.
        A short time gap alone is not enough. Strong signals include explicit
        continuation language, the same specific event, or recording 2
        completing an unfinished explanation. Keep unrelated topics separate.

        Recording 1:
        {previous_transcript}

        Recording 2:
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
                    "name": "capture_continuation",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "is_continuation": {"type": "boolean"},
                            "confidence": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
                        },
                        "required": ["is_continuation", "confidence"],
                    },
                }
            },
        },
        api_key=api_key,
    )
    try:
        output_text = response.get("output_text") or response["output"][0]["content"][0]["text"]
        decision = json.loads(output_text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError("Could not parse capture continuation response.") from exc
    return (
        decision.get("is_continuation") is True
        and decision.get("confidence") == "high"
    )


def split_capture_sessions(
    source_paths: list[Path],
    transcripts: list[str],
    *,
    should_merge: Callable[[str, str], bool],
) -> list[tuple[list[Path], list[str]]]:
    sessions: list[tuple[list[Path], list[str]]] = []
    current_paths = [source_paths[0]]
    current_transcripts = [transcripts[0]]
    for source_path, transcript in zip(source_paths[1:], transcripts[1:]):
        if should_merge(combined_transcript(current_transcripts), transcript):
            current_paths.append(source_path)
            current_transcripts.append(transcript)
        else:
            sessions.append((current_paths, current_transcripts))
            current_paths = [source_path]
            current_transcripts = [transcript]
    sessions.append((current_paths, current_transcripts))
    return sessions


def archive_capture_session(
    source_paths: list[Path],
    *,
    processed_voice_dir: Path,
    move_source_file: Callable[[Path, Path], Path],
) -> Path:
    first_recorded_at = source_recorded_at(source_paths[0])
    base_name = f"voice-session-{first_recorded_at.strftime('%Y%m%d-%H%M%S')}"
    bundle_dir = processed_voice_dir / base_name
    counter = 1
    while bundle_dir.exists():
        bundle_dir = processed_voice_dir / f"{base_name}-{counter}"
        counter += 1
    bundle_dir.mkdir(parents=True)
    archived_sources = [
        move_source_file(source_path, bundle_dir) for source_path in source_paths
    ]
    manifest = {
        "type": "voice_notes_capture_session",
        "version": 1,
        "source_count": len(archived_sources),
        "sources": [path.name for path in archived_sources],
    }
    (bundle_dir / "session.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return bundle_dir


def read_capture_transcript(
    source_path: Path,
    *,
    api_key: str,
    is_transcript_file: Callable[[Path], bool],
    read_source_text: Callable[[Path], str],
    transcribe: Callable[[Path, str], dict],
) -> str:
    if is_transcript_file(source_path):
        transcript = read_source_text(source_path)
        if not transcript:
            raise ValueError(f"Transcript file is empty: {source_path}")
        return transcript
    return transcribe(source_path, api_key)["text"]


def inbox_capture_groups(
    sources: list[Path],
    *,
    max_gap_seconds: int,
    is_voice_source: Callable[[Path], bool],
) -> list[list[Path]]:
    voice_sources = [path for path in sources if is_voice_source(path)]
    voice_source_set = set(voice_sources)
    groups = group_nearby_voice_sources(
        voice_sources,
        max_gap_seconds=max_gap_seconds,
    )
    groups.extend([[path] for path in sources if path not in voice_source_set])
    return sorted(groups, key=lambda group: source_recorded_at(group[0]))
