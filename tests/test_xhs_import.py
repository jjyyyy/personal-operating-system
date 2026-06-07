from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from email.message import Message
from pathlib import Path
from unittest.mock import patch


SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import xhs_import  # noqa: E402
import voice_notes_ai  # noqa: E402


class FakeResponse:
    def __init__(self, body: str, final_url: str):
        self.body = body.encode()
        self.final_url = final_url
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body

    def geturl(self) -> str:
        return self.final_url


class XHSImportTests(unittest.TestCase):
    def test_parses_open_graph_note(self) -> None:
        page = """
        <html><head>
        <meta charset="utf-8">
        <meta property="og:title" content="网球发球练习">
        <meta property="og:description" content="先放松肩膀，再稳定抛球。">
        <meta property="article:author" content="练球的人">
        </head></html>
        """
        parsed = xhs_import.parse_xhs_html(page)
        self.assertEqual(parsed["title"], "网球发球练习")
        self.assertEqual(parsed["text"], "先放松肩膀，再稳定抛球。")
        self.assertEqual(parsed["author"], "练球的人")
        self.assertEqual(parsed["kind"], "article")

    def test_embedded_note_body_beats_platform_boilerplate(self) -> None:
        page = """
        <meta property="og:description" content="3 亿人的生活经验，都在小红书">
        <script>
        window.__INITIAL_STATE__ = {
          "title":"巴塞罗那吃吃喝喝合集",
          "desc":"p1 marmot\\n三明治很好吃，分量很大。",
          "nickname":"一只雯雯"
        };
        </script>
        """
        parsed = xhs_import.parse_xhs_html(page)
        self.assertEqual(parsed["text"], "p1 marmot\n三明治很好吃，分量很大。")

    def test_detects_embedded_video_url(self) -> None:
        page = r'''
        <meta property="og:title" content="发球教学">
        <script>
        window.__INITIAL_STATE__ = {
          "desc":"先看抛球动作",
          "masterUrl":"https:\/\/sns-video.example.com\/clip.mp4"
        };
        </script>
        '''
        parsed = xhs_import.parse_xhs_html(page)
        self.assertEqual(parsed["kind"], "video")
        self.assertEqual(
            parsed["video_url"],
            "https://sns-video.example.com/clip.mp4",
        )

    def test_follows_share_redirect_and_returns_content(self) -> None:
        response = FakeResponse(
            '<meta property="og:description" content="Useful content">',
            "https://www.xiaohongshu.com/explore/note-id",
        )
        with patch.object(xhs_import.urllib.request, "urlopen", return_value=response):
            result = xhs_import.fetch_xhs_note("https://xhslink.com/example")
        self.assertEqual(result["url"], "https://www.xiaohongshu.com/explore/note-id")
        self.assertEqual(result["text"], "Useful content")

    def test_rejects_non_xhs_url(self) -> None:
        with self.assertRaises(ValueError):
            xhs_import.validate_xhs_url("https://example.com/not-xhs")

    def test_rejects_private_media_destination(self) -> None:
        with (
            patch.object(
                xhs_import.socket,
                "getaddrinfo",
                return_value=[(None, None, None, None, ("127.0.0.1", 443))],
            ),
            self.assertRaisesRegex(RuntimeError, "non-public"),
        ):
            xhs_import.validate_media_url("https://media.example/video.mp4")

    def test_canonical_url_drops_share_tokens(self) -> None:
        url = (
            "https://www.xiaohongshu.com/discovery/item/note-id"
            "?xsec_token=secret&share_id=private"
        )
        self.assertEqual(
            xhs_import.canonicalize_xhs_url(url),
            "https://www.xiaohongshu.com/discovery/item/note-id",
        )

    def test_login_wall_without_note_text_fails_clearly(self) -> None:
        response = FakeResponse(
            "<html><title>登录小红书</title></html>",
            "https://www.xiaohongshu.com/explore/note-id",
        )
        with (
            patch.object(xhs_import.urllib.request, "urlopen", return_value=response),
            self.assertRaisesRegex(RuntimeError, "neither note text nor"),
        ):
            xhs_import.fetch_xhs_note("https://www.xiaohongshu.com/explore/note-id")

    def test_xhs_link_becomes_separate_knowledge_note(self) -> None:
        structured = {
            "date": "2026-06-07",
            "title": "网球发球知识",
            "source": "xhs",
            "topics": ["网球"],
            "summary": "一条关于发球的外部知识。",
            "action_items": [],
            "people": [],
            "annotations": [],
            "raw_transcript": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "VOICE_ROOT": root,
                "INBOX_DIR": root / "inbox",
                "PROCESSED_DIR": root / "processed",
                "DISCARDED_DIR": root / "discarded",
                "DAILY_DIR": root / "daily",
                "XHS_DIR": root / "xhs",
                "TOPICS_DIR": root / "topics",
                "REVIEWS_DIR": root / "reviews",
                "SNIPPETS_DIR": root / "snippets",
                "TEMPLATES_DIR": root / "templates",
                "LOGS_DIR": root / "logs",
                "INDEX_FILE": root / "index.json",
                "CATALOG_FILE": root / "catalog.md",
                "LOG_FILE": root / "log.md",
            }
            with ExitStack() as stack:
                for name, value in paths.items():
                    stack.enter_context(patch.object(voice_notes_ai, name, value))
                stack.enter_context(
                    patch.object(
                    voice_notes_ai,
                    "fetch_xhs_note",
                    return_value={
                        "url": "https://www.xiaohongshu.com/explore/note-id",
                        "title": "原始标题",
                        "author": "作者",
                        "text": "先放松肩膀，再稳定抛球。",
                    },
                    )
                )
                stack.enter_context(
                    patch.object(
                        voice_notes_ai,
                        "require_api_key",
                        return_value="test-key",
                    )
                )
                stack.enter_context(
                    patch.object(
                        voice_notes_ai,
                        "summarize_capture",
                        return_value=structured,
                    )
                )
                stack.enter_context(patch.object(voice_notes_ai, "send_notification"))
                note_path = voice_notes_ai.ingest_xhs(
                    "https://xhslink.com/example"
                )
                markdown = note_path.read_text(encoding="utf-8")
                index = json.loads(paths["INDEX_FILE"].read_text(encoding="utf-8"))

        self.assertEqual(note_path.parent.name, "xhs")
        self.assertIn("source: xhs", markdown)
        self.assertIn("source_author: \"作者\"", markdown)
        self.assertIn("https://www.xiaohongshu.com/explore/note-id", markdown)
        self.assertEqual(index[0]["source"], "xhs")
        self.assertTrue(index[0]["source_file"].startswith("processed/xhs/"))

    def test_xhs_share_file_routes_through_xhs_import(self) -> None:
        structured = {
            "date": "2026-06-07",
            "title": "分享来的网球知识",
            "source": "xhs",
            "topics": ["网球"],
            "summary": "从分享链接导入的小红书知识。",
            "action_items": [],
            "people": [],
            "annotations": [],
            "raw_transcript": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            share = inbox / "xhs-share-20260607-120000.txt"
            share.write_text(
                "77 Jazzzz发布了一篇小红书笔记，快来看吧 http://xhslink.com/o/abc123",
                encoding="utf-8",
            )
            paths = {
                "VOICE_ROOT": root,
                "INBOX_DIR": inbox,
                "PROCESSED_DIR": root / "processed",
                "DISCARDED_DIR": root / "discarded",
                "DAILY_DIR": root / "daily",
                "XHS_DIR": root / "xhs",
                "TOPICS_DIR": root / "topics",
                "REVIEWS_DIR": root / "reviews",
                "SNIPPETS_DIR": root / "snippets",
                "TEMPLATES_DIR": root / "templates",
                "LOGS_DIR": root / "logs",
                "INDEX_FILE": root / "index.json",
                "CATALOG_FILE": root / "catalog.md",
                "LOG_FILE": root / "log.md",
            }
            with ExitStack() as stack:
                for name, value in paths.items():
                    stack.enter_context(patch.object(voice_notes_ai, name, value))
                stack.enter_context(
                    patch.object(
                        voice_notes_ai,
                        "fetch_xhs_note",
                        return_value={
                            "url": "https://www.xiaohongshu.com/explore/note-id",
                            "title": "原始标题",
                            "author": "作者",
                            "text": "先放松肩膀，再稳定抛球。",
                            "kind": "article",
                        },
                    )
                )
                stack.enter_context(
                    patch.object(voice_notes_ai, "require_api_key", return_value="test-key")
                )
                stack.enter_context(
                    patch.object(voice_notes_ai, "summarize_capture", return_value=structured)
                )
                stack.enter_context(patch.object(voice_notes_ai, "send_notification"))
                ok = voice_notes_ai.process_source_safely(share)

            processed = paths["PROCESSED_DIR"] / "xhs" / share.name
            markdown_files = list((root / "xhs").glob("*.md"))
            processed_exists = processed.exists()
            markdown_count = len(markdown_files)
            markdown_text = markdown_files[0].read_text(encoding="utf-8")
            processed_text = processed.read_text(encoding="utf-8")

            self.assertTrue(ok)
            self.assertTrue(processed_exists)
            self.assertEqual(markdown_count, 1)
            self.assertIn("source: xhs", markdown_text)
            self.assertIn("https://www.xiaohongshu.com/explore/note-id", processed_text)

    def test_video_share_file_is_copied_into_evidence_bundle(self) -> None:
        structured = {
            "date": "2026-06-07",
            "title": "分享来的视频知识",
            "source": "xhs",
            "topics": ["网球"],
            "summary": "从分享链接导入的小红书视频知识。",
            "action_items": [],
            "people": [],
            "annotations": [],
            "raw_transcript": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            share = inbox / "xhs-share-20260607-120001.txt"
            share.write_text(
                "复制打开小红书 http://xhslink.com/o/video123",
                encoding="utf-8",
            )
            paths = {
                "VOICE_ROOT": root,
                "INBOX_DIR": inbox,
                "PROCESSED_DIR": root / "processed",
                "DISCARDED_DIR": root / "discarded",
                "DAILY_DIR": root / "daily",
                "XHS_DIR": root / "xhs",
                "TOPICS_DIR": root / "topics",
                "REVIEWS_DIR": root / "reviews",
                "SNIPPETS_DIR": root / "snippets",
                "TEMPLATES_DIR": root / "templates",
                "LOGS_DIR": root / "logs",
                "INDEX_FILE": root / "index.json",
                "CATALOG_FILE": root / "catalog.md",
                "LOG_FILE": root / "log.md",
            }

            def fake_download(_url: str, destination: Path, referer: str = "") -> None:
                destination.write_bytes(b"video")

            def fake_build(**kwargs: object) -> dict:
                destination = Path(kwargs["destination_dir"])
                package = {
                    "source_url": "https://www.xiaohongshu.com/explore/video-id",
                    "title": "视频",
                    "post_text": "看动作",
                    "duration_seconds": 12,
                    "transcript": "先放松肩膀",
                    "transcript_segments": [
                        {"start": 1, "end": 3, "text": "先放松肩膀"}
                    ],
                    "visual_events": [],
                    "subtitles": "",
                }
                (destination / "content-package.json").write_text(
                    json.dumps(package),
                    encoding="utf-8",
                )
                return package

            with ExitStack() as stack:
                for name, value in paths.items():
                    stack.enter_context(patch.object(voice_notes_ai, name, value))
                stack.enter_context(
                    patch.object(
                        voice_notes_ai,
                        "fetch_xhs_note",
                        return_value={
                            "url": "https://www.xiaohongshu.com/explore/video-id",
                            "title": "视频",
                            "author": "作者",
                            "text": "看动作",
                            "kind": "video",
                            "video_url": "https://sns-video.example/video.mp4",
                        },
                    )
                )
                stack.enter_context(
                    patch.object(voice_notes_ai, "download_xhs_video", side_effect=fake_download)
                )
                stack.enter_context(
                    patch.object(voice_notes_ai, "build_video_content_package", side_effect=fake_build)
                )
                stack.enter_context(
                    patch.object(voice_notes_ai, "require_api_key", return_value="test-key")
                )
                stack.enter_context(
                    patch.object(voice_notes_ai, "summarize_capture", return_value=structured)
                )
                stack.enter_context(patch.object(voice_notes_ai, "send_notification"))
                ok = voice_notes_ai.process_source_safely(share)

            archived_bundles = list((paths["PROCESSED_DIR"] / "xhs").glob("xhs-video-*"))
            share_exists = share.exists()
            bundle_count = len(archived_bundles)
            share_copy_exists = (archived_bundles[0] / "share.txt").exists()
            package_exists = (archived_bundles[0] / "content-package.json").exists()

            self.assertTrue(ok)
            self.assertFalse(share_exists)
            self.assertEqual(bundle_count, 1)
            self.assertTrue(share_copy_exists)
            self.assertTrue(package_exists)

    def test_local_xhs_video_archives_portable_evidence_bundle(self) -> None:
        structured = {
            "date": "2026-06-07",
            "title": "发球视频拆解",
            "source": "xhs",
            "topics": ["网球"],
            "summary": "按时间线整理的外部视频知识。",
            "action_items": [],
            "people": [],
            "annotations": [],
            "raw_transcript": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_video = root / "export.mp4"
            local_video.write_bytes(b"video")
            paths = {
                "VOICE_ROOT": root,
                "INBOX_DIR": root / "inbox",
                "PROCESSED_DIR": root / "processed",
                "DISCARDED_DIR": root / "discarded",
                "DAILY_DIR": root / "daily",
                "XHS_DIR": root / "xhs",
                "TOPICS_DIR": root / "topics",
                "REVIEWS_DIR": root / "reviews",
                "SNIPPETS_DIR": root / "snippets",
                "TEMPLATES_DIR": root / "templates",
                "LOGS_DIR": root / "logs",
                "INDEX_FILE": root / "index.json",
                "CATALOG_FILE": root / "catalog.md",
                "LOG_FILE": root / "log.md",
            }

            def fake_build(**kwargs: object) -> dict:
                destination = Path(kwargs["destination_dir"])
                package = {
                    "source_url": "https://xhslink.com/video",
                    "title": "发球教学",
                    "post_text": "看动作",
                    "duration_seconds": 12,
                    "transcript": "先放松肩膀",
                    "transcript_segments": [
                        {"start": 1, "end": 3, "text": "先放松肩膀"}
                    ],
                    "visual_events": [],
                    "subtitles": "",
                }
                (destination / "content-package.json").write_text(
                    json.dumps(package),
                    encoding="utf-8",
                )
                return package

            with ExitStack() as stack:
                for name, value in paths.items():
                    stack.enter_context(patch.object(voice_notes_ai, name, value))
                stack.enter_context(
                    patch.object(voice_notes_ai, "require_api_key", return_value="key")
                )
                stack.enter_context(
                    patch.object(
                        voice_notes_ai,
                        "build_video_content_package",
                        side_effect=fake_build,
                    )
                )
                stack.enter_context(
                    patch.object(
                        voice_notes_ai,
                        "summarize_capture",
                        return_value=structured,
                    )
                )
                stack.enter_context(patch.object(voice_notes_ai, "send_notification"))
                note_path = voice_notes_ai.ingest_xhs_video(
                    {
                        "url": "https://xhslink.com/video",
                        "title": "发球教学",
                        "author": "教练",
                        "text": "看动作",
                        "kind": "video",
                        "video_url": "",
                    },
                    local_video,
                )
                index = json.loads(paths["INDEX_FILE"].read_text(encoding="utf-8"))
                markdown = note_path.read_text(encoding="utf-8")

        self.assertEqual(note_path.parent.name, "xhs")
        self.assertEqual(index[0]["source_kind"], "video")
        self.assertIn("processed/xhs/xhs-video-", index[0]["source_file"])
        self.assertIn("Evidence package:", markdown)
