from __future__ import annotations

import json
import errno
import os
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
            patch.object(voice_notes_ai, "DEFERRED_DIR", root / "deferred"),
            patch.object(voice_notes_ai, "DAILY_DIR", root / "daily"),
            patch.object(voice_notes_ai, "XHS_DIR", root / "xhs"),
            patch.object(voice_notes_ai, "TOPICS_DIR", root / "topics"),
            patch.object(voice_notes_ai, "REVIEWS_DIR", root / "reviews"),
            patch.object(voice_notes_ai, "SNIPPETS_DIR", root / "snippets"),
            patch.object(voice_notes_ai, "TEMPLATES_DIR", root / "templates"),
            patch.object(voice_notes_ai, "LOGS_DIR", root / "logs"),
            patch.object(voice_notes_ai, "STATE_DIR", root / "state"),
            patch.object(voice_notes_ai, "MAPS_DIR", root / "maps"),
            patch.object(voice_notes_ai, "OUTBOX_DIR", root / "outbox"),
            patch.object(voice_notes_ai, "CALENDAR_OUTBOX_DIR", root / "outbox" / "calendar"),
            patch.object(voice_notes_ai, "ROUTES_DIR", root / "routes"),
            patch.object(voice_notes_ai, "INDEX_FILE", root / "index.json"),
            patch.object(voice_notes_ai, "CATALOG_FILE", root / "catalog.md"),
            patch.object(voice_notes_ai, "LOG_FILE", root / "log.md"),
            patch.object(
                voice_notes_ai,
                "XHS_AUTO_STATE_FILE",
                root / "state" / "xhs-auto-imports.json",
            ),
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
                patch.object(voice_notes_ai, "DEFERRED_DIR", root / "deferred"),
                patch.object(voice_notes_ai, "DAILY_DIR", root / "daily"),
                patch.object(voice_notes_ai, "XHS_DIR", root / "xhs"),
                patch.object(voice_notes_ai, "TOPICS_DIR", root / "topics"),
                patch.object(voice_notes_ai, "REVIEWS_DIR", root / "reviews"),
                patch.object(voice_notes_ai, "SNIPPETS_DIR", root / "snippets"),
                patch.object(voice_notes_ai, "TEMPLATES_DIR", root / "templates"),
                patch.object(voice_notes_ai, "LOGS_DIR", root / "logs"),
                patch.object(voice_notes_ai, "STATE_DIR", root / "state"),
                patch.object(voice_notes_ai, "MAPS_DIR", root / "maps"),
                patch.object(voice_notes_ai, "OUTBOX_DIR", root / "outbox"),
                patch.object(voice_notes_ai, "CALENDAR_OUTBOX_DIR", root / "outbox" / "calendar"),
                patch.object(voice_notes_ai, "ROUTES_DIR", root / "routes"),
                patch.object(voice_notes_ai, "INDEX_FILE", root / "index.json"),
                patch.object(voice_notes_ai, "LOG_FILE", root / "log.md"),
                patch.object(
                    voice_notes_ai,
                    "XHS_AUTO_STATE_FILE",
                    root / "state" / "xhs-auto-imports.json",
                ),
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

    def test_discard_deferred_moves_source_to_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "deferred" / "xhs" / "xhs-share.txt"
            source.parent.mkdir(parents=True)
            source.write_text("http://xhslink.com/o/example", encoding="utf-8")
            with self.patch_vault_paths(root):
                discarded = voice_notes_ai.discard_deferred(
                    [Path("xhs-share.txt")],
                    source_type="xhs",
                )

            self.assertFalse(source.exists())
            self.assertEqual(discarded[0], root / "discarded" / "xhs" / "xhs-share.txt")
            self.assertTrue(discarded[0].exists())
            self.assertIn("discard | xhs-share.txt", (root / "log.md").read_text(encoding="utf-8"))

    def test_move_source_file_falls_back_after_icloud_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "inbox" / "xhs-share.txt"
            destination_dir = root / "deferred" / "xhs"
            source.parent.mkdir(parents=True)
            source.write_text("小红书分享 http://xhslink.com/o/example\n", encoding="utf-8")

            def fake_move(_source: str, destination: str) -> None:
                Path(destination).write_bytes(b"")
                raise OSError(errno.EDEADLK, os.strerror(errno.EDEADLK))

            with (
                self.patch_vault_paths(root),
                patch.object(voice_notes_ai.shutil, "move", side_effect=fake_move),
            ):
                destination = voice_notes_ai.move_source_file(source, destination_dir)

            self.assertFalse(source.exists())
            self.assertEqual(destination, destination_dir / "xhs-share.txt")
            self.assertEqual(
                destination.read_text(encoding="utf-8"),
                "小红书分享 http://xhslink.com/o/example\n",
            )

    def test_move_source_file_removes_fallback_copy_when_unlink_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "inbox" / "xhs-share.txt"
            destination_dir = root / "deferred" / "xhs"
            source.parent.mkdir(parents=True)
            source.write_text("小红书分享 http://xhslink.com/o/example\n", encoding="utf-8")

            def fake_move(_source: str, destination: str) -> None:
                Path(destination).write_bytes(b"")
                raise OSError(errno.EDEADLK, os.strerror(errno.EDEADLK))

            original_unlink = Path.unlink

            def fake_unlink(path: Path, *args: object, **kwargs: object) -> None:
                if path == source:
                    raise PermissionError("cannot remove source")
                original_unlink(path, *args, **kwargs)

            with (
                self.patch_vault_paths(root),
                patch.object(voice_notes_ai.shutil, "move", side_effect=fake_move),
                patch.object(voice_notes_ai.Path, "unlink", fake_unlink),
                self.assertRaises(PermissionError),
            ):
                voice_notes_ai.move_source_file(source, destination_dir)

            self.assertTrue(source.exists())
            self.assertFalse((destination_dir / "xhs-share.txt").exists())

    def test_move_source_file_removes_nonempty_partial_after_icloud_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "inbox" / "xhs-share.txt"
            destination_dir = root / "deferred" / "xhs"
            source.parent.mkdir(parents=True)
            source.write_text("完整的小红书分享\n", encoding="utf-8")

            def fake_move(_source: str, destination: str) -> None:
                Path(destination).write_text("partial", encoding="utf-8")
                raise OSError(errno.EDEADLK, os.strerror(errno.EDEADLK))

            with (
                self.patch_vault_paths(root),
                patch.object(voice_notes_ai.shutil, "move", side_effect=fake_move),
            ):
                destination = voice_notes_ai.move_source_file(source, destination_dir)

            self.assertFalse(source.exists())
            self.assertEqual(destination, destination_dir / "xhs-share.txt")
            self.assertEqual(destination.read_text(encoding="utf-8"), "完整的小红书分享\n")

    def test_correct_note_updates_markdown_index_catalog_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "daily" / "note.md"
            note.parent.mkdir(parents=True)
            (root / "topics").mkdir()
            note.write_text(
                "\n".join(
                    [
                        "---",
                        "date: 2026-06-07",
                        "source: voice",
                        'topics: ["volleyball"]',
                        "people: []",
                        "title: Old Title",
                        "---",
                        "",
                        "# Old Title",
                        "",
                        "## Summary",
                        "",
                        "Old summary.",
                        "",
                        "## Topics",
                        "",
                        "- volleyball",
                        "",
                        "## Action Items",
                        "",
                        "- old action",
                        "",
                        "## People",
                        "",
                        "-",
                        "",
                        "## Links",
                        "",
                        "- volleyball (unpromoted)",
                        "",
                        "## Raw Transcript",
                        "",
                        "I meant tennis volley.",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            index = [
                {
                    "date": "2026-06-07",
                    "title": "Old Title",
                    "topics": ["volleyball"],
                    "people": [],
                    "summary": "Old summary.",
                    "source": "voice",
                    "source_file": "processed/voice/source.txt",
                    "note_file": "daily/note.md",
                }
            ]
            (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
            with self.patch_vault_paths(root):
                voice_notes_ai.correct_note(
                    Path("daily/note.md"),
                    reason="volley means tennis volley, not volleyball",
                    title="Tennis Volley Note",
                    summary="This note is about tennis volley technique.",
                    topics=["网球", "volley"],
                    action_items=[],
                    people=[],
                )
                updated_index = json.loads((root / "index.json").read_text(encoding="utf-8"))

            markdown = note.read_text(encoding="utf-8")
            self.assertIn("title: Tennis Volley Note", markdown)
            self.assertIn('topics: ["网球", "volley"]', markdown)
            self.assertIn("# Tennis Volley Note", markdown)
            self.assertIn("This note is about tennis volley technique.", markdown)
            self.assertIn("## Corrections", markdown)
            self.assertIn("volley means tennis volley", markdown)
            self.assertEqual(updated_index[0]["title"], "Tennis Volley Note")
            self.assertEqual(updated_index[0]["topics"], ["网球", "volley"])
            self.assertEqual(updated_index[0]["summary"], "This note is about tennis volley technique.")
            self.assertIn("Tennis Volley Note", (root / "catalog.md").read_text(encoding="utf-8"))
            self.assertIn("correct | note", (root / "log.md").read_text(encoding="utf-8"))

    def test_google_maps_save_queue_extracts_xhs_place_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "xhs" / "barcelona-food.md"
            note.parent.mkdir(parents=True)
            note.write_text(
                "\n".join(
                    [
                        "# 巴塞罗那美食",
                        "",
                        "## Imported Content",
                        "",
                        "p1 marmot",
                        "中午有brunch套餐",
                        "",
                        "p2 myka",
                        "路过可以尝尝的酸奶冰淇淋",
                        "",
                        "p3 centric restaurant&cafe",
                        "在La Roca打折村 饭不夹生 面包也是烤的脆脆的",
                        "",
                        "p4 sandwich club",
                        "好吃但是小贵的三明治 这家冰抹茶拿铁很难喝",
                        "",
                        "p5 madeleine by ferrieres",
                        "法式甜品店 巧克力脑袋直接冲",
                        "",
                        "p6 jiancha 见茶山",
                        "25%糖的泰奶 是好喝的奶茶",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with self.patch_vault_paths(root):
                output = voice_notes_ai.google_maps_save_queue(
                    Path("xhs/barcelona-food.md"),
                    city="Barcelona",
                )

            rendered = output.read_text(encoding="utf-8")
            centric_block = rendered.split("### centric restaurant&cafe", 1)[1].split("###", 1)[0]
            sandwich_block = rendered.split("### sandwich club", 1)[1].split("###", 1)[0]
            madeleine_block = rendered.split("### madeleine by ferrieres", 1)[1].split("###", 1)[0]
            jiancha_block = rendered.split("### jiancha 见茶山", 1)[1].split("###", 1)[0]
            self.assertEqual(output.parent, root / "maps")
            self.assertIn("### marmot", rendered)
            self.assertIn("- Suggested list: Brunch", rendered)
            self.assertIn("query=marmot+Barcelona", rendered)
            self.assertIn("### myka", rendered)
            self.assertIn("- Suggested list: Gelato", rendered)
            self.assertIn("- Suggested list: 吃-Travel", centric_block)
            self.assertIn("- Suggested list: 吃-Travel", sandwich_block)
            self.assertIn("- Suggested list: Bakery", madeleine_block)
            self.assertIn("- Suggested list: 喝", jiancha_block)
            self.assertIn("maps | Google Maps save queue", (root / "log.md").read_text(encoding="utf-8"))

    def test_google_maps_task_writes_json_for_openclaw(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "xhs" / "barcelona-food.md"
            note.parent.mkdir(parents=True)
            note.write_text(
                "# 巴塞罗那美食\n\n## Imported Content\n\np1 marmot\n中午有brunch套餐\n",
                encoding="utf-8",
            )
            with self.patch_vault_paths(root):
                output = voice_notes_ai.google_maps_task(
                    Path("xhs/barcelona-food.md"),
                    city="Barcelona",
                )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(output.parent, root / "outbox" / "google-maps")
            self.assertEqual(payload["type"], "google_maps_save_queue")
            self.assertEqual(payload["source_note"], "xhs/barcelona-food.md")
            self.assertEqual(payload["candidates"][0]["name"], "marmot")
            self.assertEqual(payload["candidates"][0]["suggested_list"], "Brunch")
            self.assertIn("maps-task | Google Maps task", (root / "log.md").read_text(encoding="utf-8"))

    def test_google_maps_task_ids_include_position_to_avoid_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "xhs" / "duplicate-food.md"
            note.parent.mkdir(parents=True)
            note.write_text(
                "\n".join(
                    [
                        "# Duplicate",
                        "",
                        "## Imported Content",
                        "",
                        "p1 marmot",
                        "brunch",
                        "",
                        "p2 marmot",
                        "coffee",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with self.patch_vault_paths(root):
                output = voice_notes_ai.google_maps_task(Path("xhs/duplicate-food.md"))

            payload = json.loads(output.read_text(encoding="utf-8"))
            ids = [candidate["id"] for candidate in payload["candidates"]]
            self.assertEqual(ids, ["marmot-01", "marmot-02"])

    def test_route_note_delivers_matching_note_to_registered_inbox(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            projects_root = Path(directory)
            root = projects_root / "voice-notes"
            target = projects_root / "physical-therapy-assistant"
            note = root / "daily" / "note.md"
            routes_dir = root / "routes"
            note.parent.mkdir(parents=True)
            routes_dir.mkdir(parents=True)
            note.write_text(
                "---\nsource: voice\ntopics: [\"exercise\"]\n---\n\n# Note\n\n## Raw Transcript\n\nPain after training.\n",
                encoding="utf-8",
            )
            (root / "index.json").parent.mkdir(parents=True, exist_ok=True)
            (root / "index.json").write_text(
                json.dumps(
                    [
                        {
                            "date": "2026-06-09",
                            "title": "Training note",
                            "topics": ["exercise", "injury"],
                            "people": [],
                            "summary": "Pain after training.",
                            "source": "voice",
                            "source_file": "processed/voice/source.m4a",
                            "note_file": "daily/note.md",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (routes_dir / "pt.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "id": "pt-assistant",
                        "target": "physical-therapy-assistant",
                        "target_inbox": "../physical-therapy-assistant/inbox/voice-notes",
                        "matches": {
                            "source_any": ["voice"],
                            "topics_any": ["exercise", "injury", "diet"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.patch_vault_paths(root):
                outputs = voice_notes_ai.route_note(Path("daily/note.md"))

            self.assertEqual(len(outputs), 1)
            self.assertEqual(
                outputs[0].parent.resolve(),
                (target / "inbox" / "voice-notes").resolve(),
            )
            payload = json.loads(outputs[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["type"], "voice_notes_routed_note")
            self.assertEqual(payload["route_id"], "pt-assistant")
            self.assertEqual(payload["source_note"], "daily/note.md")
            self.assertEqual(payload["topics"], ["exercise", "injury"])
            self.assertNotIn("note_body", payload)
            self.assertIn("route | Training note", (root / "log.md").read_text(encoding="utf-8"))

    def test_route_note_can_discover_target_project_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            projects_root = Path(directory)
            root = projects_root / "voice-notes"
            target = projects_root / "physical-therapy-assistant"
            note = root / "daily" / "food.md"
            note.parent.mkdir(parents=True)
            target.mkdir(parents=True)
            note.write_text("---\nsource: voice\n---\n", encoding="utf-8")
            (root / "index.json").parent.mkdir(parents=True, exist_ok=True)
            (root / "index.json").write_text(
                json.dumps(
                    [
                        {
                            "date": "2026-06-09",
                            "title": "Diet note",
                            "topics": ["diet"],
                            "people": [],
                            "summary": "Protein and training.",
                            "source": "voice",
                            "source_file": "processed/voice/source.m4a",
                            "note_file": "daily/food.md",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (target / "voice-notes-routing.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "id": "pt-diet",
                        "target": "physical-therapy-assistant",
                        "target_inbox": "inbox/voice-notes",
                        "matches": {"topics_any": ["diet"]},
                    }
                ),
                encoding="utf-8",
            )

            with self.patch_vault_paths(root):
                outputs = voice_notes_ai.route_note(Path("daily/food.md"))

            self.assertEqual(
                outputs[0].parent.resolve(),
                (target / "inbox" / "voice-notes").resolve(),
            )

    def test_save_note_stores_extracted_items_in_markdown_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "processed" / "voice" / "source.m4a"
            source.parent.mkdir(parents=True)
            source.write_text("audio", encoding="utf-8")
            note = {
                "date": "2026-06-09",
                "title": "Mixed memo",
                "source": "voice",
                "topics": ["tennis", "massage"],
                "summary": "A massage appointment and tennis note.",
                "action_items": ["Confirm massage appointment"],
                "people": [],
                "annotations": [],
                "extracted_items": [
                    {
                        "item_type": "calendar_event",
                        "text": "Massage appointment tomorrow at 3pm",
                        "date_text": "tomorrow",
                        "time_text": "3pm",
                        "route_categories": ["calendar", "health"],
                        "calendar_ready": True,
                        "needs_confirmation": False,
                        "confidence": "high",
                        "evidence": "massage appointment tomorrow at 3pm",
                    },
                    {
                        "item_type": "knowledge_note",
                        "text": "Tennis volley timing note",
                        "date_text": None,
                        "time_text": None,
                        "route_categories": ["sports"],
                        "calendar_ready": False,
                        "needs_confirmation": False,
                        "confidence": "high",
                        "evidence": "tennis volley timing",
                    },
                ],
                "raw_transcript": "Massage appointment tomorrow at 3pm. Tennis volley timing.",
            }
            with self.patch_vault_paths(root):
                output = voice_notes_ai.save_note(note, source)
                index = json.loads((root / "index.json").read_text(encoding="utf-8"))

            markdown = output.read_text(encoding="utf-8")
            self.assertIn("extracted_items:", markdown)
            self.assertIn("## Extracted Items", markdown)
            self.assertIn("Massage appointment tomorrow at 3pm", markdown)
            self.assertEqual(index[0]["extracted_items"][0]["item_type"], "calendar_event")
            self.assertEqual(index[0]["extracted_items"][1]["route_categories"], ["sports"])

    def test_route_note_routes_extracted_items_by_route_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            projects_root = Path(directory)
            root = projects_root / "voice-notes"
            target = projects_root / "physical-therapy-assistant"
            note = root / "daily" / "mixed.md"
            routes_dir = root / "routes"
            note.parent.mkdir(parents=True)
            routes_dir.mkdir(parents=True)
            note.write_text("---\nsource: voice\n---\n", encoding="utf-8")
            (root / "index.json").parent.mkdir(parents=True, exist_ok=True)
            (root / "index.json").write_text(
                json.dumps(
                    [
                        {
                            "date": "2026-06-09",
                            "title": "Mixed memo",
                            "topics": ["tennis", "massage"],
                            "extracted_items": [
                                {
                                    "item_type": "calendar_event",
                                    "text": "Massage appointment tomorrow at 3pm",
                                    "date_text": "tomorrow",
                                    "time_text": "3pm",
                                    "route_categories": ["calendar", "health"],
                                    "calendar_ready": True,
                                    "needs_confirmation": False,
                                    "confidence": "high",
                                    "evidence": "massage appointment tomorrow at 3pm",
                                },
                                {
                                    "item_type": "knowledge_note",
                                    "text": "Tennis technique note",
                                    "date_text": None,
                                    "time_text": None,
                                    "route_categories": ["sports"],
                                    "calendar_ready": False,
                                    "needs_confirmation": False,
                                    "confidence": "high",
                                    "evidence": "tennis technique",
                                },
                            ],
                            "people": [],
                            "summary": "Mixed memo.",
                            "source": "voice",
                            "source_file": "processed/voice/source.m4a",
                            "note_file": "daily/mixed.md",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (routes_dir / "pt.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "id": "pt-assistant",
                        "target": "physical-therapy-assistant",
                        "target_inbox": "../physical-therapy-assistant/inbox/voice-notes",
                        "matches": {"route_categories_any": ["sports", "health"]},
                    }
                ),
                encoding="utf-8",
            )

            with self.patch_vault_paths(root):
                outputs = voice_notes_ai.route_note(Path("daily/mixed.md"))

            self.assertEqual(len(outputs), 2)
            payloads = [json.loads(path.read_text(encoding="utf-8")) for path in outputs]
            self.assertEqual({payload["type"] for payload in payloads}, {"voice_notes_routed_item"})
            self.assertEqual(
                {payload["extracted_item"]["text"] for payload in payloads},
                {"Massage appointment tomorrow at 3pm", "Tennis technique note"},
            )
            self.assertTrue(
                all(
                    path.parent.resolve() == (target / "inbox" / "voice-notes").resolve()
                    for path in outputs
                )
            )

    def test_calendar_outbox_writes_only_calendar_ready_high_confidence_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.json").write_text(
                json.dumps(
                    [
                        {
                            "date": "2026-06-09",
                            "title": "Mixed memo",
                            "topics": ["massage"],
                            "people": [],
                            "summary": "Mixed memo.",
                            "source": "voice",
                            "source_file": "processed/voice/source.m4a",
                            "note_file": "daily/mixed.md",
                            "extracted_items": [
                                {
                                    "item_type": "calendar_event",
                                    "text": "Massage appointment tomorrow at 3pm",
                                    "date_text": "tomorrow",
                                    "time_text": "3pm",
                                    "route_categories": ["calendar", "health"],
                                    "calendar_ready": True,
                                    "needs_confirmation": False,
                                    "confidence": "high",
                                    "evidence": "massage appointment tomorrow at 3pm",
                                },
                                {
                                    "item_type": "reminder",
                                    "text": "Maybe book another massage",
                                    "date_text": None,
                                    "time_text": None,
                                    "route_categories": ["calendar", "health"],
                                    "calendar_ready": False,
                                    "needs_confirmation": True,
                                    "confidence": "medium",
                                    "evidence": "maybe book another massage",
                                },
                            ],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            with self.patch_vault_paths(root):
                outputs = voice_notes_ai.calendar_outbox()
                second_run = voice_notes_ai.calendar_outbox()

            self.assertEqual(len(outputs), 1)
            self.assertEqual(second_run, [])
            payload = json.loads(outputs[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["type"], "voice_notes_calendar_candidate")
            self.assertEqual(payload["status"], "needs_review")
            self.assertEqual(payload["text"], "Massage appointment tomorrow at 3pm")

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

    def test_scheduled_weekly_uses_latest_completed_week(self) -> None:
        self.assertEqual(
            voice_notes_ai.resolve_scheduled_snippet_range(
                "weekly",
                voice_notes_ai.dt.date(2026, 6, 8),
            ),
            (voice_notes_ai.dt.date(2026, 6, 1), voice_notes_ai.dt.date(2026, 6, 7)),
        )
        self.assertEqual(
            voice_notes_ai.resolve_scheduled_snippet_range(
                "weekly",
                voice_notes_ai.dt.date(2026, 6, 7),
            ),
            (voice_notes_ai.dt.date(2026, 5, 25), voice_notes_ai.dt.date(2026, 5, 31)),
        )

    def test_scheduled_snippet_skips_existing_completed_week_without_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snippet = root / "snippets" / "2026-06-01_to_2026-06-07_weekly_snippet.md"
            snippet.parent.mkdir(parents=True)
            snippet.write_text("# Existing\n", encoding="utf-8")
            with (
                self.patch_vault_paths(root),
                patch.object(
                    voice_notes_ai,
                    "require_api_key",
                    side_effect=AssertionError("should not call OpenAI"),
                ),
            ):
                output = voice_notes_ai.scheduled_snippet(
                    "weekly",
                    today=voice_notes_ai.dt.date(2026, 6, 8),
                )

        self.assertEqual(output, snippet)

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
