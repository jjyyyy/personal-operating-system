from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import voice_notes_ai  # noqa: E402


class LightweightCompatibilityTests(unittest.TestCase):
    @contextmanager
    def patch_vault_paths(self, root: Path):
        patches = [
            patch.object(voice_notes_ai, "VOICE_ROOT", root),
            patch.object(voice_notes_ai, "INBOX_DIR", root / "inbox"),
            patch.object(voice_notes_ai, "PROCESSED_DIR", root / "processed"),
            patch.object(voice_notes_ai, "DISCARDED_DIR", root / "discarded"),
            patch.object(voice_notes_ai, "DAILY_DIR", root / "daily"),
            patch.object(voice_notes_ai, "XHS_DIR", root / "xhs"),
            patch.object(voice_notes_ai, "TOPICS_DIR", root / "topics"),
            patch.object(voice_notes_ai, "REVIEWS_DIR", root / "reviews"),
            patch.object(voice_notes_ai, "SNIPPETS_DIR", root / "snippets"),
            patch.object(voice_notes_ai, "TEMPLATES_DIR", root / "templates"),
            patch.object(voice_notes_ai, "LOGS_DIR", root / "logs"),
            patch.object(voice_notes_ai, "INDEX_FILE", root / "index.json"),
            patch.object(voice_notes_ai, "CATALOG_FILE", root / "catalog.md"),
            patch.object(voice_notes_ai, "LOG_FILE", root / "log.md"),
        ]
        exits = [item.__enter__() for item in patches]
        try:
            yield exits
        finally:
            for item in reversed(patches):
                item.__exit__(None, None, None)

    def test_text_manifest_becomes_regular_inbox_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inbox = Path(directory) / "inbox"
            manifest = Path(directory) / "capture.json"
            manifest.write_text(
                json.dumps(
                    {
                        "url": "https://example.com/note",
                        "text": "A useful shared note.",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(voice_notes_ai, "INBOX_DIR", inbox):
                output, source_type = voice_notes_ai.capture_manifest_as_regular_source(manifest)

            content = output.read_text(encoding="utf-8")

        self.assertEqual(output.parent, inbox)
        self.assertEqual(source_type, "bot")
        self.assertIn("Source: https://example.com/note", content)
        self.assertIn("A useful shared note.", content)

    def test_inbox_sources_include_source_subfolders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            (inbox / "root.txt").write_text("root", encoding="utf-8")
            (inbox / "xhs").mkdir()
            (inbox / "xhs" / "xhs-share-test.txt").write_text(
                "http://xhslink.com/o/example",
                encoding="utf-8",
            )
            (inbox / "voice").mkdir()
            (inbox / "voice" / "voice-note.txt").write_text("voice", encoding="utf-8")
            (inbox / "random").mkdir()
            (inbox / "random" / "ignored.txt").write_text("ignored", encoding="utf-8")
            with (
                patch.object(voice_notes_ai, "VOICE_ROOT", root),
                patch.object(voice_notes_ai, "INBOX_DIR", inbox),
                patch.object(voice_notes_ai, "PROCESSED_DIR", root / "processed"),
                patch.object(voice_notes_ai, "DISCARDED_DIR", root / "discarded"),
                patch.object(voice_notes_ai, "DAILY_DIR", root / "daily"),
                patch.object(voice_notes_ai, "XHS_DIR", root / "xhs"),
                patch.object(voice_notes_ai, "TOPICS_DIR", root / "topics"),
                patch.object(voice_notes_ai, "REVIEWS_DIR", root / "reviews"),
                patch.object(voice_notes_ai, "SNIPPETS_DIR", root / "snippets"),
                patch.object(voice_notes_ai, "TEMPLATES_DIR", root / "templates"),
                patch.object(voice_notes_ai, "LOGS_DIR", root / "logs"),
                patch.object(voice_notes_ai, "INDEX_FILE", root / "index.json"),
                patch.object(voice_notes_ai, "LOG_FILE", root / "log.md"),
            ):
                sources = voice_notes_ai.inbox_sources()

        self.assertEqual(
            {path.name for path in sources},
            {"root.txt", "xhs-share-test.txt", "voice-note.txt"},
        )

    def test_nested_inbox_folder_infers_source_type(self) -> None:
        source = Path("/tmp/inbox/xhs/xhs-share-test.txt")
        self.assertEqual(voice_notes_ai.infer_source_type(source), "xhs")

    def test_delete_note_removes_note_source_index_and_rebuilds_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "xhs" / "note.md"
            source = root / "processed" / "xhs" / "source.txt"
            note.parent.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            note.write_text("---\nsource: xhs\n---\n", encoding="utf-8")
            source.write_text("Source URL: https://xhslink.com/example\n", encoding="utf-8")
            index = [
                {
                    "date": "2026-06-07",
                    "title": "XHS Note",
                    "topics": ["xhs"],
                    "people": [],
                    "summary": "summary",
                    "source": "xhs",
                    "source_file": "processed/xhs/source.txt",
                    "note_file": "xhs/note.md",
                }
            ]
            (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
            with self.patch_vault_paths(root):
                voice_notes_ai.delete_note(Path("xhs/note.md"))
                remaining_index = json.loads((root / "index.json").read_text(encoding="utf-8"))

            self.assertFalse(note.exists())
            self.assertFalse(source.exists())
            self.assertEqual(remaining_index, [])
            self.assertTrue((root / "catalog.md").exists())
            self.assertIn("delete | XHS Note", (root / "log.md").read_text(encoding="utf-8"))

    def test_delete_note_removes_video_source_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "xhs" / "video.md"
            source = root / "processed" / "xhs" / "xhs-video-test"
            note.parent.mkdir(parents=True)
            source.mkdir(parents=True)
            note.write_text("---\nsource: xhs\nsource_kind: video\n---\n", encoding="utf-8")
            (source / "content-package.json").write_text("{}", encoding="utf-8")
            index = [
                {
                    "date": "2026-06-07",
                    "title": "Video Note",
                    "topics": ["xhs"],
                    "people": [],
                    "summary": "summary",
                    "source": "xhs",
                    "source_kind": "video",
                    "source_file": "processed/xhs/xhs-video-test",
                    "note_file": "xhs/video.md",
                }
            ]
            (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
            with self.patch_vault_paths(root):
                voice_notes_ai.delete_note(Path("xhs/video.md"))

            self.assertFalse(note.exists())
            self.assertFalse(source.exists())

    def test_delete_note_dry_run_does_not_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "daily" / "note.md"
            source = root / "processed" / "voice" / "source.txt"
            note.parent.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            note.write_text("---\nsource: voice\n---\n", encoding="utf-8")
            source.write_text("voice", encoding="utf-8")
            index = [
                {
                    "date": "2026-06-07",
                    "title": "Voice Note",
                    "topics": ["voice"],
                    "people": [],
                    "summary": "summary",
                    "source": "voice",
                    "source_file": "processed/voice/source.txt",
                    "note_file": "daily/note.md",
                }
            ]
            (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
            with self.patch_vault_paths(root):
                voice_notes_ai.delete_note(Path("daily/note.md"), dry_run=True)
                remaining_index = json.loads((root / "index.json").read_text(encoding="utf-8"))

            self.assertTrue(note.exists())
            self.assertTrue(source.exists())
            self.assertEqual(remaining_index, index)

    def test_delete_note_requires_index_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "daily" / "note.md"
            note.parent.mkdir(parents=True)
            note.write_text("orphan", encoding="utf-8")
            (root / "index.json").write_text("[]", encoding="utf-8")
            with self.patch_vault_paths(root), self.assertRaisesRegex(SystemExit, "not tracked"):
                voice_notes_ai.delete_note(Path("daily/note.md"))

    def test_search_scope_separates_personal_and_xhs_notes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            daily = Path(directory) / "daily"
            xhs_dir = Path(directory) / "xhs"
            daily.mkdir()
            xhs_dir.mkdir()
            personal = daily / "personal.md"
            xhs = xhs_dir / "xhs.md"
            personal.write_text(
                "---\nsource: voice\n---\n我的网球想法\n",
                encoding="utf-8",
            )
            xhs.write_text(
                "---\nsource: xhs\n---\n小红书网球知识\n",
                encoding="utf-8",
            )
            with (
                patch.object(voice_notes_ai, "DAILY_DIR", daily),
                patch.object(voice_notes_ai, "XHS_DIR", xhs_dir),
                patch.object(voice_notes_ai, "TOPICS_DIR", Path(directory) / "topics"),
                patch.object(voice_notes_ai, "REVIEWS_DIR", Path(directory) / "reviews"),
                patch.object(voice_notes_ai, "SNIPPETS_DIR", Path(directory) / "snippets"),
                patch.object(voice_notes_ai, "VOICE_ROOT", Path(directory)),
                patch.object(voice_notes_ai, "ensure_dirs"),
            ):
                personal_results = voice_notes_ai.search_notes("网球", "personal")
                xhs_results = voice_notes_ai.search_notes("网球", "xhs")

        self.assertEqual({path.name for path, _, _ in personal_results}, {"personal.md"})
        self.assertEqual({path.name for path, _, _ in xhs_results}, {"xhs.md"})

    def test_review_presets_resolve_completed_periods(self) -> None:
        today = voice_notes_ai.dt.date(2026, 6, 7)
        self.assertEqual(
            voice_notes_ai.resolve_review_range("weekly", None, None, today),
            (voice_notes_ai.dt.date(2026, 6, 1), voice_notes_ai.dt.date(2026, 6, 7)),
        )
        self.assertEqual(
            voice_notes_ai.resolve_review_range("monthly", None, None, today),
            (voice_notes_ai.dt.date(2026, 5, 1), voice_notes_ai.dt.date(2026, 5, 31)),
        )
        self.assertEqual(
            voice_notes_ai.resolve_review_range("yearly", None, None, today),
            (voice_notes_ai.dt.date(2025, 1, 1), voice_notes_ai.dt.date(2025, 12, 31)),
        )

    def test_range_loader_keeps_personal_and_xhs_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            daily = root / "daily"
            xhs = root / "xhs"
            daily.mkdir()
            xhs.mkdir()
            (daily / "2026-06-07-personal.md").write_text("personal tennis", encoding="utf-8")
            (xhs / "2026-06-07-import.md").write_text("imported tennis", encoding="utf-8")
            with (
                patch.object(voice_notes_ai, "DAILY_DIR", daily),
                patch.object(voice_notes_ai, "XHS_DIR", xhs),
            ):
                personal = voice_notes_ai.load_note_files_in_range(
                    voice_notes_ai.dt.date(2026, 6, 7),
                    voice_notes_ai.dt.date(2026, 6, 7),
                    "personal",
                )
                imported = voice_notes_ai.load_note_files_in_range(
                    voice_notes_ai.dt.date(2026, 6, 7),
                    voice_notes_ai.dt.date(2026, 6, 7),
                    "xhs",
                )

        self.assertEqual([path.parent.name for path in personal], ["daily"])
        self.assertEqual([path.parent.name for path in imported], ["xhs"])

    def test_period_review_writes_snippet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            daily = root / "daily"
            snippets = root / "snippets"
            daily.mkdir()
            (daily / "2026-06-07-personal.md").write_text(
                "---\nsource: voice\n---\nA useful weekly note.",
                encoding="utf-8",
            )
            response = {
                "output": [
                    {
                        "content": [
                            {"text": "# Weekly Snippet\n\nA concise synthesis."}
                        ]
                    }
                ]
            }
            with (
                self.patch_vault_paths(root),
                patch.object(voice_notes_ai, "require_api_key", return_value="test-key"),
                patch.object(voice_notes_ai, "api_post_json", return_value=response),
            ):
                output = voice_notes_ai.weekly_review(
                    voice_notes_ai.dt.date(2026, 6, 1),
                    voice_notes_ai.dt.date(2026, 6, 7),
                )

        self.assertEqual(output.parent, snippets)
        self.assertEqual(output.name, "2026-06-01_to_2026-06-07_weekly_snippet.md")
