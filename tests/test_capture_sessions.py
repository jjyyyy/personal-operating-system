from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from capture_sessions import (  # noqa: E402
    combined_transcript,
    group_nearby_voice_sources,
    has_explicit_continuation,
    model_continuation_decision,
    source_recorded_at,
)


class CaptureSessionTests(unittest.TestCase):
    def test_reads_recording_time_from_shortcut_filename(self) -> None:
        path = Path("Voice Note - 2026-06-11-125317.m4a")

        recorded_at = source_recorded_at(path)

        self.assertEqual(recorded_at, dt.datetime(2026, 6, 11, 12, 53, 17))

    def test_groups_recordings_within_continuation_window(self) -> None:
        sources = [
            Path("Voice Note - 2026-06-11-124842.m4a"),
            Path("Voice Note - 2026-06-11-125317.m4a"),
            Path("Voice Note - 2026-06-11-131500.m4a"),
        ]

        groups = group_nearby_voice_sources(sources, max_gap_seconds=600)

        self.assertEqual(groups, [sources[:2], sources[2:]])

    def test_recognizes_explicit_mandarin_continuation(self) -> None:
        self.assertTrue(has_explicit_continuation("继续说今天早上的网球课，还有一个就是反手"))
        self.assertTrue(has_explicit_continuation("再补充一下刚才的发球动作"))
        self.assertFalse(has_explicit_continuation("今天要去采购蔬菜和肉"))

    def test_combined_transcript_keeps_recording_boundaries(self) -> None:
        combined = combined_transcript(["第一段", "继续说第二段"])

        self.assertIn("[Recording 1]\n第一段", combined)
        self.assertIn("[Recording 2]\n继续说第二段", combined)

    def test_semantic_continuation_requires_high_confidence(self) -> None:
        def response(*args, **kwargs):
            return {
                "output_text": '{"is_continuation": true, "confidence": "medium"}'
            }

        decision = model_continuation_decision(
            "第一段网球课",
            "第二段发球动作",
            api_key="test",
            model="test-model",
            api_post_json=response,
        )

        self.assertFalse(decision)


if __name__ == "__main__":
    unittest.main()
