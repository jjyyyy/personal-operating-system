from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import video_ingestion  # noqa: E402


class VideoIngestionTests(unittest.TestCase):
    def test_evenly_spaced_times_adapts_to_duration(self) -> None:
        self.assertEqual(video_ingestion.evenly_spaced_times(2, 16), [1.0])
        self.assertEqual(
            video_ingestion.evenly_spaced_times(12, 4),
            [1.5, 4.5, 7.5, 10.5],
        )

    def test_choose_evenly_preserves_temporal_coverage(self) -> None:
        records = [{"timestamp": value} for value in range(10)]
        selected = video_ingestion.choose_evenly(records, 3)
        self.assertEqual(
            [record["timestamp"] for record in selected],
            [0, 4, 9],
        )

    def test_video_evidence_labels_observation_and_inference(self) -> None:
        package = {
            "source_url": "https://example.test/video",
            "title": "Technique",
            "post_text": "Caption",
            "duration_seconds": 65,
            "transcript_segments": [
                {"start": 3, "end": 7, "text": "Relax the shoulder."}
            ],
            "visual_events": [
                {
                    "timestamp": 4,
                    "visible_content": "The racket is below shoulder height.",
                    "visible_text": "放松",
                    "interpretation": "This may be preparation for the swing.",
                }
            ],
            "subtitles": "",
        }
        text = video_ingestion.video_evidence_text(package, author="Coach")
        self.assertIn("[00:03-00:07] Relax the shoulder.", text)
        self.assertIn("Visible: The racket is below shoulder height.", text)
        self.assertIn("OCR/text: 放松", text)
        self.assertIn("AI interpretation:", text)
        self.assertIn("Evidence rule:", text)

    def test_content_package_requires_real_video_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "source.mp4"
            video.write_bytes(b"fixture")
            with (
                patch.object(video_ingestion, "probe_duration", return_value=10.0),
                patch.object(video_ingestion, "extract_audio", return_value=None),
                patch.object(
                    video_ingestion,
                    "extract_embedded_subtitles",
                    return_value=(None, ""),
                ),
                patch.object(video_ingestion, "extract_scene_frames", return_value=[]),
                self.assertRaisesRegex(RuntimeError, "neither a transcript nor visual"),
            ):
                video_ingestion.build_video_content_package(
                    video,
                    root,
                    "test-key",
                    analyze_frames=lambda records, key: [],
                )

    def test_content_package_is_portable_and_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "source-video.mp4"
            audio = root / "audio.mp3"
            frame = root / "frames" / "frame.jpg"
            video.write_bytes(b"video")
            audio.write_bytes(b"audio")
            frame.parent.mkdir()
            frame.write_bytes(b"image")
            with (
                patch.object(video_ingestion, "probe_duration", return_value=12.5),
                patch.object(video_ingestion, "extract_audio", return_value=audio),
                patch.object(
                    video_ingestion,
                    "extract_embedded_subtitles",
                    return_value=(None, ""),
                ),
                patch.object(
                    video_ingestion,
                    "extract_scene_frames",
                    return_value=[{"index": 1, "timestamp": 2.5, "path": frame}],
                ),
                patch.object(
                    video_ingestion,
                    "transcribe_timed",
                    return_value={
                        "text": "spoken content",
                        "segments": [
                            {"start": 1, "end": 3, "text": "spoken content"}
                        ],
                        "provider": "test",
                        "model": "test-model",
                    },
                ),
            ):
                package = video_ingestion.build_video_content_package(
                    video,
                    root,
                    "test-key",
                    analyze_frames=lambda records, key: [
                        {
                            "frame_index": 1,
                            "timestamp": 2.5,
                            "visible_content": "A demonstrated movement",
                            "visible_text": "",
                            "interpretation": "",
                        }
                    ],
                    source_url="https://example.test/video",
                )
            saved = json.loads(
                (root / "content-package.json").read_text(encoding="utf-8")
            )

        self.assertEqual(package["schema"], "voice-notes.video-content.v1")
        self.assertEqual(package["video_path"], "source-video.mp4")
        self.assertEqual(package["frames"][0]["path"], "frames/frame.jpg")
        self.assertEqual(saved["transcript_segments"][0]["start"], 1)
