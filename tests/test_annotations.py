from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import voice_notes_ai  # noqa: E402


def sample_note(annotations: list[dict]) -> dict:
    return {
        "date": "2026-06-07",
        "title": "Test Note",
        "source": "voice",
        "topics": ["testing"],
        "summary": "A short summary.",
        "action_items": [],
        "people": [],
        "annotations": annotations,
        "raw_transcript": "A short transcript.",
    }


class AnnotationTests(unittest.TestCase):
    def test_empty_annotations_omit_comment_section(self) -> None:
        markdown = voice_notes_ai.note_markdown(sample_note([]))
        self.assertNotIn("## AI Comments", markdown)
        self.assertNotIn("[!ai-comment]", markdown)

    def test_annotation_renders_as_review_style_callout(self) -> None:
        markdown = voice_notes_ai.note_markdown(
            sample_note(
                [
                    {
                        "title": "A useful distinction",
                        "type": "clarification",
                        "anchor_quote": "the original thought",
                        "body": "This adds concise context.",
                        "confidence": "high",
                        "basis": "established-knowledge",
                    }
                ]
            )
        )
        self.assertIn("## AI Comments", markdown)
        self.assertIn("[!ai-comment]+ AI Comment · Clarification", markdown)
        self.assertIn("“the original thought”", markdown)
        self.assertIn("Confidence: High · Basis: Established Knowledge", markdown)

    def test_summary_schema_allows_zero_annotations(self) -> None:
        response = {
            "output_text": json.dumps(
                sample_note([]),
                ensure_ascii=False,
            )
        }
        with patch.object(voice_notes_ai, "api_post_json", return_value=response) as post:
            result = voice_notes_ai.summarize_transcript(
                "Ordinary note with no knowledge gap.",
                "2026-06-07",
                "test-key",
            )

        self.assertEqual(result["annotations"], [])
        payload = post.call_args.kwargs["payload"]
        annotation_schema = payload["text"]["format"]["schema"]["properties"]["annotations"]
        self.assertEqual(annotation_schema["maxItems"], 3)


if __name__ == "__main__":
    unittest.main()
