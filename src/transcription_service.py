#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import json
import mimetypes
import os
import shlex
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TRANSIENT_API_STATUS_CODES = {429, 500, 502, 503, 504}
ICLOUD_RETRY_ERRNOS = {errno.EAGAIN, errno.EDEADLK}


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


def guess_mime_type(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    return mime_type or "application/octet-stream"


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def retry_delay(attempt: int) -> int:
    return min(2**attempt, 8)


def request_icloud_download(file_path: Path) -> None:
    brctl = Path("/usr/bin/brctl")
    if not brctl.exists():
        return
    subprocess.run(
        [str(brctl), "download", str(file_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def read_source_bytes(file_path: Path) -> bytes:
    timeout_seconds = int(os.environ.get("VOICE_NOTES_ICLOUD_TIMEOUT", "120"))
    deadline = time.monotonic() + timeout_seconds
    download_requested = False
    last_error: OSError | None = None
    while True:
        try:
            return file_path.read_bytes()
        except OSError as exc:
            if exc.errno not in ICLOUD_RETRY_ERRNOS:
                raise
            last_error = exc
        if not download_requested:
            request_icloud_download(file_path)
            download_requested = True
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"iCloud file did not become readable within {timeout_seconds}s: "
                f"{file_path} ({last_error})"
            )
        time.sleep(2)


def api_post_multipart(
    url: str,
    fields: dict[str, str | list[str]],
    file_path: Path,
    api_key: str,
) -> dict:
    boundary = "----VoiceNotesAIBoundary"
    body = bytearray()
    for key, raw_value in fields.items():
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        for value in values:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
            )
            body.extend(value.encode())
            body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{file_path.name}"\r\n'
            f"Content-Type: {guess_mime_type(file_path)}\r\n\r\n"
        ).encode()
    )
    body.extend(read_source_bytes(file_path))
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    for attempt in range(3):
        request = urllib.request.Request(
            url,
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, context=ssl_context()) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode(errors="replace")
            if exc.code in TRANSIENT_API_STATUS_CODES and attempt < 2:
                delay = retry_delay(attempt)
                print(
                    f"OpenAI transcription returned {exc.code}; "
                    f"retrying in {delay}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            raise RuntimeError(
                f"OpenAI transcription failed: {exc.code} {response_body}"
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < 2:
                delay = retry_delay(attempt)
                print(
                    f"OpenAI transcription connection failed; "
                    f"retrying in {delay}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            raise RuntimeError(
                f"Could not reach OpenAI transcription API: {exc.reason}"
            ) from exc
    raise RuntimeError("OpenAI transcription failed after retries.")


def transcribe_with_local_command(audio_path: Path) -> dict | None:
    raw_command = os.environ.get("VOICE_NOTES_LOCAL_TRANSCRIBE_COMMAND", "").strip()
    if not raw_command:
        return None
    command = [
        part.replace("{audio}", str(audio_path))
        for part in shlex.split(raw_command)
    ]
    if not any(str(audio_path) in part for part in command):
        command.append(str(audio_path))
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("VOICE_NOTES_TRANSCRIBE_TIMEOUT", "600")),
    )
    output = result.stdout.strip()
    if not output:
        raise RuntimeError("Local transcription command returned no text.")
    try:
        payload = json.loads(output)
        text = str(payload.get("text", "")).strip()
        model = payload.get("model")
        segments = payload.get("segments", [])
    except json.JSONDecodeError:
        text = output
        model = None
        segments = []
    if not text:
        raise RuntimeError("Local transcription command returned no text.")
    return {
        "text": text,
        "provider": "local-command",
        "model": model,
        "segments": segments if isinstance(segments, list) else [],
    }


def transcribe_with_openai(audio_path: Path, api_key: str) -> dict:
    model = os.environ.get(
        "OPENAI_TRANSCRIBE_MODEL",
        "gpt-4o-mini-transcribe",
    )
    response = api_post_multipart(
        "https://api.openai.com/v1/audio/transcriptions",
        fields={"model": model},
        file_path=audio_path,
        api_key=api_key,
    )
    text = str(response.get("text", "")).strip()
    if not text:
        raise RuntimeError("Transcription response did not include text.")
    return {"text": text, "provider": "openai", "model": model}


def transcribe_with_openai_timed(audio_path: Path, api_key: str) -> dict:
    model = os.environ.get("OPENAI_TIMESTAMP_TRANSCRIBE_MODEL", "whisper-1")
    response = api_post_multipart(
        "https://api.openai.com/v1/audio/transcriptions",
        fields={
            "model": model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["segment"],
        },
        file_path=audio_path,
        api_key=api_key,
    )
    text = str(response.get("text", "")).strip()
    segments = [
        {
            "start": float(segment.get("start", 0)),
            "end": float(segment.get("end", 0)),
            "text": str(segment.get("text", "")).strip(),
        }
        for segment in response.get("segments", [])
        if str(segment.get("text", "")).strip()
    ]
    if not text:
        raise RuntimeError("Timestamped transcription returned no text.")
    return {
        "text": text,
        "segments": segments,
        "provider": "openai",
        "model": model,
    }


def transcribe(audio_path: Path, api_key: str | None = None) -> dict:
    load_dotenv()
    source = audio_path.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Audio file not found: {source}")
    local_error: Exception | None = None
    try:
        local_result = transcribe_with_local_command(source)
        if local_result:
            return local_result
    except Exception as exc:
        local_error = exc
    resolved_key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
    if not resolved_key:
        if local_error:
            raise RuntimeError(
                f"Local transcription failed and OpenAI is not configured: "
                f"{local_error}"
            ) from local_error
        raise RuntimeError(
            "No transcription provider is configured. Set "
            "VOICE_NOTES_LOCAL_TRANSCRIBE_COMMAND or OPENAI_API_KEY."
        )
    try:
        return transcribe_with_openai(source, resolved_key)
    except Exception as exc:
        if local_error:
            raise RuntimeError(
                f"Local transcription failed: {local_error}; "
                f"OpenAI transcription failed: {exc}"
            ) from exc
        raise


def transcribe_timed(audio_path: Path, api_key: str | None = None) -> dict:
    load_dotenv()
    source = audio_path.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Audio file not found: {source}")

    local_error: Exception | None = None
    try:
        local_result = transcribe_with_local_command(source)
        if local_result:
            return {
                **local_result,
                "segments": local_result.get("segments", []),
            }
    except Exception as exc:
        local_error = exc

    resolved_key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
    if not resolved_key:
        if local_error:
            raise RuntimeError(
                "Local timestamped transcription failed and OpenAI is not "
                f"configured: {local_error}"
            ) from local_error
        raise RuntimeError(
            "Timestamped transcription requires OPENAI_API_KEY or a local "
            "transcriber that returns segments."
        )
    try:
        return transcribe_with_openai_timed(source, resolved_key)
    except Exception as exc:
        if local_error:
            raise RuntimeError(
                f"Local timestamped transcription failed: {local_error}; "
                f"OpenAI timestamped transcription failed: {exc}"
            ) from exc
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shared media transcription service")
    subparsers = parser.add_subparsers(dest="command", required=True)
    transcribe_parser = subparsers.add_parser(
        "transcribe-json",
        help="Transcribe one audio/video file and print JSON",
    )
    transcribe_parser.add_argument("source", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = transcribe(args.source)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": f"{type(exc).__name__}: {exc}",
                    "provider": None,
                    "text": "",
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
