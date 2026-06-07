from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import transcription_service  # noqa: E402
from transcription_service import transcribe  # noqa: E402


class TranscriptionServiceTests(unittest.TestCase):
    def test_local_provider_precedes_openai(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "audio.mp3"
            audio_path.write_bytes(b"not-read-by-fake-provider")
            with patch.dict(
                os.environ,
                {
                    "VOICE_NOTES_LOCAL_TRANSCRIBE_COMMAND": (
                        "/bin/echo shared-local-transcript {audio}"
                    ),
                    "OPENAI_API_KEY": "unused",
                },
                clear=False,
            ):
                result = transcribe(audio_path)
        self.assertEqual(result["provider"], "local-command")
        self.assertIn("shared-local-transcript", result["text"])

    def test_missing_file_is_rejected_before_provider_call(self) -> None:
        with self.assertRaises(FileNotFoundError):
            transcribe(Path("/tmp/voice-notes-missing-audio.mp3"))

    def test_failed_local_provider_falls_back_to_openai(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "audio.mp3"
            audio_path.write_bytes(b"test")
            with (
                patch.dict(
                    os.environ,
                    {
                        "VOICE_NOTES_LOCAL_TRANSCRIBE_COMMAND": "/usr/bin/false",
                        "OPENAI_API_KEY": "test-key",
                    },
                    clear=False,
                ),
                patch(
                    "transcription_service.transcribe_with_openai",
                    return_value={
                        "text": "openai fallback",
                        "provider": "openai",
                        "model": "test",
                    },
                ),
            ):
                result = transcribe(audio_path)
        self.assertEqual(result["provider"], "openai")
        self.assertEqual(result["text"], "openai fallback")

    def test_timestamped_openai_request_uses_segment_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "audio.mp3"
            audio.write_bytes(b"audio")
            response = {
                "text": "hello",
                "segments": [{"start": 0.0, "end": 1.2, "text": "hello"}],
            }
            with patch.object(
                transcription_service,
                "api_post_multipart",
                return_value=response,
            ) as request:
                result = transcription_service.transcribe_with_openai_timed(
                    audio,
                    "test-key",
                )

        fields = request.call_args.kwargs["fields"]
        self.assertEqual(fields["response_format"], "verbose_json")
        self.assertEqual(fields["timestamp_granularities[]"], ["segment"])
        self.assertEqual(result["segments"][0]["end"], 1.2)


if __name__ == "__main__":
    unittest.main()
