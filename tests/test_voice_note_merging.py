from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from voice_note_merging import (  # noqa: E402
    continuation_decision,
    local_continuation_signal,
    note_date_for_recording,
    source_recorded_at,
    timestamped_transcript,
)


class VoiceNoteMergingTests(unittest.TestCase):
    def test_reads_recording_time_from_shortcut_filename(self) -> None:
        path = Path("Voice Note - 2026-06-11-125317.m4a")

        recorded_at = source_recorded_at(path)

        self.assertEqual(recorded_at, dt.datetime(2026, 6, 11, 12, 53, 17))

    def test_before_rollover_hour_belongs_to_previous_day(self) -> None:
        recorded_at = dt.datetime(2026, 6, 11, 1, 30)

        note_date = note_date_for_recording(recorded_at, rollover_hour=4)

        self.assertEqual(note_date, dt.date(2026, 6, 10))

    def test_after_rollover_hour_stays_on_calendar_day(self) -> None:
        recorded_at = dt.datetime(2026, 6, 11, 4, 0)

        note_date = note_date_for_recording(recorded_at, rollover_hour=4)

        self.assertEqual(note_date, dt.date(2026, 6, 11))

    def test_recognizes_two_local_continuation_signal_types(self) -> None:
        self.assertEqual(
            local_continuation_signal("继续说今天早上的网球课"),
            "explicit_continuation",
        )
        self.assertEqual(
            local_continuation_signal("刚才提到的反手还有一个问题"),
            "referential_continuation",
        )
        self.assertIsNone(local_continuation_signal("今天要去采购蔬菜和肉"))

    def test_model_can_identify_same_specific_context(self) -> None:
        def response(*args, **kwargs):
            return {
                "output_text": (
                    '{"signal":"same_specific_context","confidence":"high"}'
                )
            }

        decision = continuation_decision(
            "今天上午的网球课先练了正手。",
            "发球部分教练把手心方向改了。",
            api_key="test",
            model="test-model",
            api_post_json=response,
        )

        self.assertTrue(decision.should_merge)
        self.assertEqual(decision.signal, "same_specific_context")

    def test_model_signal_requires_high_confidence(self) -> None:
        def response(*args, **kwargs):
            return {
                "output_text": (
                    '{"signal":"same_specific_context","confidence":"medium"}'
                )
            }

        decision = continuation_decision(
            "第一条",
            "第二条",
            api_key="test",
            model="test-model",
            api_post_json=response,
        )

        self.assertFalse(decision.should_merge)

    def test_timestamped_transcript_keeps_recording_times(self) -> None:
        combined = timestamped_transcript(
            [
                (dt.datetime(2026, 6, 11, 12, 48, 42), "第一段"),
                (dt.datetime(2026, 6, 11, 12, 53, 17), "第二段"),
            ]
        )

        self.assertIn("[2026-06-11 12:48:42]\n第一段", combined)
        self.assertIn("[2026-06-11 12:53:17]\n第二段", combined)


if __name__ == "__main__":
    unittest.main()
