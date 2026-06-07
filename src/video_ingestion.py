from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from transcription_service import transcribe_timed


FrameAnalyzer = Callable[[list[dict], str], list[dict]]
DEFAULT_SCENE_THRESHOLD = 0.28
DEFAULT_MAX_FRAMES = 16


def executable_path(name: str, env_name: str) -> Path:
    configured = os.environ.get(env_name, "").strip()
    shared_ffmpeg_candidates = [
        Path.home()
        / "Projects/xiaohongshu-profile-monitor-python-migration"
        / "node_modules/ffmpeg-static/ffmpeg",
        Path.home()
        / "Projects/xiaohongshu-profile-monitor"
        / "node_modules/ffmpeg-static/ffmpeg",
    ]
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path(found) if (found := shutil.which(name)) else None,
        *(shared_ffmpeg_candidates if name == "ffmpeg" else []),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError(
        f"{name} is required for video ingestion. Install it or set {env_name}."
    )


def run_ffmpeg(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    ffmpeg = executable_path("ffmpeg", "VOICE_NOTES_FFMPEG_PATH")
    return subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "info", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def probe_duration(video_path: Path) -> float:
    try:
        result = run_ffmpeg(["-i", str(video_path)])
        output = result.stderr
    except subprocess.CalledProcessError as exc:
        output = exc.stderr or ""
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not match:
        raise RuntimeError(f"Could not determine video duration: {video_path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def extract_audio(video_path: Path, destination_dir: Path) -> Path | None:
    audio_path = destination_dir / "audio.mp3"
    try:
        run_ffmpeg(
            [
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "48k",
                str(audio_path),
            ]
        )
    except subprocess.CalledProcessError:
        return None
    return audio_path


def extract_embedded_subtitles(
    video_path: Path,
    destination_dir: Path,
) -> tuple[Path | None, str]:
    subtitle_path = destination_dir / "subtitles.vtt"
    try:
        run_ffmpeg(
            [
                "-y",
                "-i",
                str(video_path),
                "-map",
                "0:s:0",
                "-c:s",
                "webvtt",
                str(subtitle_path),
            ]
        )
    except subprocess.CalledProcessError:
        return None, ""
    return subtitle_path, subtitle_path.read_text(encoding="utf-8").strip()


def evenly_spaced_times(duration: float, count: int) -> list[float]:
    if duration <= 0:
        return [0.0]
    frame_count = max(1, min(count, max(1, int(duration // 3) + 1)))
    return [
        round(duration * (index + 0.5) / frame_count, 3)
        for index in range(frame_count)
    ]


def choose_evenly(items: list[dict], limit: int) -> list[dict]:
    if len(items) <= limit:
        return items
    if limit <= 1:
        return [items[len(items) // 2]]
    indexes = {
        round(index * (len(items) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [items[index] for index in sorted(indexes)]


def extract_scene_frames(
    video_path: Path,
    destination_dir: Path,
    duration_seconds: float,
    threshold: float = DEFAULT_SCENE_THRESHOLD,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> list[dict]:
    frames_dir = destination_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    filter_value = f"select='gt(scene,{threshold})',showinfo"
    scene_timestamps: list[float] = []
    try:
        result = run_ffmpeg(
            [
                "-y",
                "-i",
                str(video_path),
                "-an",
                "-vf",
                filter_value,
                "-f",
                "null",
                "-",
            ]
        )
        scene_timestamps = [
            float(value)
            for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr)
        ]
    except subprocess.CalledProcessError:
        scene_timestamps = []

    anchor_times = [min(0.5, duration_seconds / 2)]
    if duration_seconds > 1:
        anchor_times.append(max(0, duration_seconds - 0.5))
    candidate_times = sorted({*scene_timestamps, *anchor_times})
    if len(candidate_times) < min(3, max_frames):
        candidate_times = evenly_spaced_times(duration_seconds, max_frames)
    selected_times = [
        record["timestamp"]
        for record in choose_evenly(
            [{"timestamp": timestamp} for timestamp in candidate_times],
            max_frames,
        )
    ]
    selected = extract_frames_at_times(video_path, frames_dir, selected_times)
    for index, record in enumerate(selected, start=1):
        destination = frames_dir / f"frame-{index:03d}-{record['timestamp']:.3f}s.jpg"
        if record["path"] != destination:
            record["path"].replace(destination)
        record["path"] = destination
        record["index"] = index
    return selected


def extract_frames_at_times(
    video_path: Path,
    frames_dir: Path,
    timestamps: list[float],
) -> list[dict]:
    records = []
    for index, timestamp in enumerate(timestamps, start=1):
        path = frames_dir / f"fallback-{index:03d}.jpg"
        try:
            run_ffmpeg(
                [
                    "-y",
                    "-ss",
                    str(timestamp),
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(path),
                ]
            )
        except subprocess.CalledProcessError:
            continue
        records.append({"timestamp": timestamp, "path": path})
    return records


def relative_frame_records(records: list[dict], root: Path) -> list[dict]:
    return [
        {
            "index": record["index"],
            "timestamp": record["timestamp"],
            "path": str(record["path"].relative_to(root)),
        }
        for record in records
    ]


def build_video_content_package(
    video_path: Path,
    destination_dir: Path,
    api_key: str,
    analyze_frames: FrameAnalyzer,
    title: str = "",
    post_text: str = "",
    page_subtitles: str = "",
    source_url: str = "",
) -> dict:
    destination_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video_path)
    audio_path = extract_audio(video_path, destination_dir)
    subtitle_path, embedded_subtitles = extract_embedded_subtitles(
        video_path,
        destination_dir,
    )
    frame_records = extract_scene_frames(
        video_path,
        destination_dir,
        duration,
        threshold=float(
            os.environ.get("VOICE_NOTES_VIDEO_SCENE_THRESHOLD", DEFAULT_SCENE_THRESHOLD)
        ),
        max_frames=max(
            1,
            int(os.environ.get("VOICE_NOTES_VIDEO_MAX_FRAMES", DEFAULT_MAX_FRAMES)),
        ),
    )

    transcription = {
        "text": "",
        "segments": [],
        "provider": None,
        "model": None,
        "error": "No audio track was extracted.",
    }
    if audio_path:
        try:
            transcription = transcribe_timed(audio_path, api_key)
            transcription["error"] = None
        except Exception as exc:
            transcription["error"] = f"{type(exc).__name__}: {exc}"

    visual_events: list[dict] = []
    visual_error = None
    if frame_records:
        try:
            visual_events = analyze_frames(frame_records, api_key)
        except Exception as exc:
            visual_error = f"{type(exc).__name__}: {exc}"

    if not transcription.get("text") and not visual_events:
        raise RuntimeError(
            "Video evidence extraction produced neither a transcript nor visual "
            f"events. Transcription: {transcription.get('error')}; "
            f"vision: {visual_error or 'no frames extracted'}"
        )

    package = {
        "schema": "voice-notes.video-content.v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_url": source_url,
        "title": title.strip(),
        "post_text": post_text.strip(),
        "duration_seconds": round(duration, 3),
        "video_path": video_path.name,
        "audio_path": audio_path.name if audio_path else None,
        "subtitle_path": subtitle_path.name if subtitle_path else None,
        "subtitles": "\n".join(
            part.strip()
            for part in [page_subtitles, embedded_subtitles]
            if part.strip()
        ),
        "transcript": transcription.get("text", ""),
        "transcript_segments": transcription.get("segments", []),
        "transcript_provider": transcription.get("provider"),
        "transcript_model": transcription.get("model"),
        "transcription_error": transcription.get("error"),
        "frames": relative_frame_records(frame_records, destination_dir),
        "visual_events": visual_events,
        "visual_analysis_error": visual_error,
    }
    package_path = destination_dir / "content-package.json"
    package_path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return package


def format_timestamp(seconds: float) -> str:
    rounded = max(0, int(round(seconds)))
    return f"{rounded // 60:02d}:{rounded % 60:02d}"


def video_evidence_text(package: dict, author: str = "") -> str:
    lines = [
        f"Source URL: {package.get('source_url', '')}",
        "Content kind: XHS video",
    ]
    if package.get("title"):
        lines.append(f"Original title: {package['title']}")
    if author:
        lines.append(f"Author: {author}")
    lines.extend(
        [
            f"Duration: {format_timestamp(package.get('duration_seconds', 0))}",
            "",
            "## Creator Caption",
            package.get("post_text") or "(none)",
            "",
            "## Timestamped Transcript",
        ]
    )
    segments = package.get("transcript_segments") or []
    if segments:
        for segment in segments:
            start = format_timestamp(float(segment.get("start", 0)))
            end = format_timestamp(float(segment.get("end", 0)))
            lines.append(f"- [{start}-{end}] {segment.get('text', '').strip()}")
    else:
        lines.append(package.get("transcript") or "(unavailable)")

    lines.extend(["", "## Visual Evidence Timeline"])
    for event in package.get("visual_events", []):
        timestamp = format_timestamp(float(event.get("timestamp", 0)))
        lines.append(f"- [{timestamp}] Visible: {event.get('visible_content', '')}")
        if event.get("visible_text"):
            lines.append(f"  OCR/text: {event['visible_text']}")
        if event.get("interpretation"):
            lines.append(f"  AI interpretation: {event['interpretation']}")
    if not package.get("visual_events"):
        lines.append("- (visual analysis unavailable)")

    if package.get("subtitles"):
        lines.extend(["", "## Embedded/Page Subtitles", package["subtitles"]])
    lines.extend(
        [
            "",
            "Evidence rule: transcript is creator speech; visible content and OCR "
            "are observed frame evidence; AI interpretation is inference.",
        ]
    )
    return "\n".join(lines).strip()
