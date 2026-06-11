from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from google_calendar_provider import authorize_google_calendar
from ingestion_service import (
    discard_deferred, discard_inbox, ingest, ingest_xhs_video, prepare_xhs_source,
    process_deferred_xhs, process_inbox, watch_inbox,
)
from integration_service import (
    calendar_dispatch, calendar_outbox, google_maps_save_queue, google_maps_task,
    list_routes, route_note,
)
from knowledge_service import (
    capture_manifest_as_regular_source, init_topics, lint_wiki, period_review,
    resolve_review_range, resolve_scheduled_snippet_range, scheduled_snippet,
    search_notes, weekly_review,
)
from note_corrections import parse_cli_list
from vault_service import (
    append_log, correct_note, delete_note, obsidian_link, path_for_index,
    rebuild_catalog, send_notification,
)
from voice_notes_config import SOURCE_TYPES
from xhs_import import fetch_xhs_note

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Voice notes AI workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Transcribe or organize one source file")
    ingest_parser.add_argument("source_files", nargs="+", type=Path)
    ingest_parser.add_argument("--date", dest="note_date", type=str, default=None)

    inbox_parser = subparsers.add_parser("process-inbox", help="Process every supported file in inbox")
    inbox_parser.add_argument("--date", dest="note_date", type=str, default=None)
    inbox_parser.add_argument("--settle-seconds", dest="settle_seconds", type=int, default=0)

    watch_parser = subparsers.add_parser("watch-inbox", help="Poll inbox and process files once they finish syncing")
    watch_parser.add_argument("--date", dest="note_date", type=str, default=None)
    watch_parser.add_argument("--interval", dest="interval_seconds", type=int, default=30)
    watch_parser.add_argument("--settle-seconds", dest="settle_seconds", type=int, default=20)
    watch_parser.add_argument("--once", action="store_true", help="Check once and exit")

    discard_parser = subparsers.add_parser("discard-inbox", help="Move accidental inbox recordings to discarded/")
    discard_parser.add_argument("source_files", nargs="*", type=Path)
    discard_parser.add_argument("--latest", action="store_true", help="Discard the newest supported inbox file")

    discard_deferred_parser = subparsers.add_parser(
        "discard-deferred",
        help="Move deferred sources that should not be retried to discarded/",
    )
    discard_deferred_parser.add_argument("source_files", nargs="+", type=Path)
    discard_deferred_parser.add_argument(
        "--source-type",
        choices=SOURCE_TYPES,
        default=None,
        help="Resolve filenames under a specific deferred subfolder",
    )
    discard_deferred_parser.add_argument("--dry-run", action="store_true")

    deferred_xhs_parser = subparsers.add_parser(
        "process-deferred-xhs",
        help="Process a limited number of deferred XHS shares when safety gates allow it",
    )
    deferred_xhs_parser.add_argument("--limit", type=int, default=1)

    delete_parser = subparsers.add_parser("delete-note", help="Delete an indexed note and its archived source")
    delete_parser.add_argument("note_file", type=Path)
    delete_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")

    correct_parser = subparsers.add_parser(
        "correct-note",
        help="Apply a semantic correction to an indexed note",
    )
    correct_parser.add_argument("note_file", type=Path)
    correct_parser.add_argument("--reason", required=True)
    correct_parser.add_argument("--title", default=None)
    correct_parser.add_argument("--summary", default=None)
    correct_parser.add_argument(
        "--topic",
        dest="topics",
        action="append",
        default=None,
        help="Correct topics; pass multiple times or comma-separate",
    )
    correct_parser.add_argument(
        "--action-item",
        dest="action_items",
        action="append",
        default=None,
        help="Correct action items; pass multiple times or comma-separate",
    )
    correct_parser.add_argument(
        "--people",
        action="append",
        default=None,
        help="Correct people; pass multiple times or comma-separate",
    )
    correct_parser.add_argument("--dry-run", action="store_true")

    maps_parser = subparsers.add_parser(
        "google-maps-save-queue",
        help="Create a manual Google Maps save queue from an XHS note",
    )
    maps_parser.add_argument("note_file", type=Path)
    maps_parser.add_argument("--city", default="", help="Add a city to each Maps search query")
    maps_parser.add_argument("--output", type=Path, default=None)
    maps_parser.add_argument("--dry-run", action="store_true")

    maps_task_parser = subparsers.add_parser(
        "google-maps-task",
        help="Create a JSON Google Maps save task for OpenClaw/Telegram",
    )
    maps_task_parser.add_argument("note_file", type=Path)
    maps_task_parser.add_argument("--city", default="", help="Add a city to each Maps search query")
    maps_task_parser.add_argument("--output", type=Path, default=None)
    maps_task_parser.add_argument(
        "--telegram-preview",
        action="store_true",
        help="Print a compact Telegram-ready preview after writing the task",
    )

    subparsers.add_parser(
        "list-routes",
        help="List generic note route registrations",
    )

    route_parser = subparsers.add_parser(
        "route-note",
        help="Route a tracked note to matching registered project inboxes",
    )
    route_parser.add_argument("note_file", type=Path)
    route_parser.add_argument("--dry-run", action="store_true")

    review_parser = subparsers.add_parser("weekly-review", help="Legacy alias for weekly-snippet")
    review_parser.add_argument("--from", dest="date_from", type=str, default=None)
    review_parser.add_argument("--to", dest="date_to", type=str, default=None)
    add_review_options(review_parser)

    weekly_snippet_parser = subparsers.add_parser("weekly-snippet", help="Create a weekly personal snippet")
    weekly_snippet_parser.add_argument("--from", dest="date_from", type=str, default=None)
    weekly_snippet_parser.add_argument("--to", dest="date_to", type=str, default=None)
    add_review_options(weekly_snippet_parser)

    monthly_parser = subparsers.add_parser(
        "monthly-review",
        help="Legacy alias for monthly-snippet",
    )
    add_review_options(monthly_parser)

    monthly_snippet_parser = subparsers.add_parser(
        "monthly-snippet",
        help="Create a snippet for the previous calendar month",
    )
    add_review_options(monthly_snippet_parser)

    scheduled_snippet_parser = subparsers.add_parser(
        "scheduled-snippet",
        help="Run a scheduled snippet with cron-friendly logging",
    )
    scheduled_snippet_parser.add_argument("period", choices=["weekly", "monthly"])

    period_parser = subparsers.add_parser(
        "review",
        help="Review a preset or custom time range",
    )
    period_parser.add_argument(
        "--preset",
        choices=["weekly", "monthly", "yearly"],
        default=None,
    )
    period_parser.add_argument("--from", dest="date_from", type=str, default=None)
    period_parser.add_argument("--to", dest="date_to", type=str, default=None)
    period_parser.add_argument("--label", default=None)
    add_review_options(period_parser)

    search_parser = subparsers.add_parser("search", help="Search topic, review, and daily notes")
    search_parser.add_argument("query", type=str)
    search_parser.add_argument(
        "--scope",
        choices=["personal", "xhs", "all"],
        default="all",
        help="Search personal captures, XHS imports, or the whole vault",
    )

    capture_parser = subparsers.add_parser(
        "capture",
        help="Compatibility: convert a text/media manifest into the regular inbox",
    )
    capture_parser.add_argument("--manifest", required=True, type=Path)

    xhs_parser = subparsers.add_parser(
        "capture-xhs",
        help="Fetch an XHS share link and convert it into a knowledge note",
    )
    xhs_parser.add_argument("--url", required=True)
    xhs_parser.add_argument("--text", default=None)
    xhs_parser.add_argument("--text-file", type=Path, default=None)
    xhs_parser.add_argument("--title", default=None)
    xhs_parser.add_argument("--author", default=None)
    xhs_parser.add_argument(
        "--video-file",
        type=Path,
        default=None,
        help="Use an exported local video when XHS does not expose the media URL",
    )
    xhs_parser.add_argument("--note-id", default=None)
    xhs_parser.add_argument("--enqueue-only", action="store_true")

    status_parser = subparsers.add_parser("status", help="Compatibility command; platform state is deferred")
    status_parser.add_argument("capture_id")

    cancel_parser = subparsers.add_parser(
        "cancel",
        help="Compatibility command; use discard-inbox for pending files",
    )
    cancel_parser.add_argument("capture_id")

    calendar_parser = subparsers.add_parser(
        "calendar-outbox",
        help="Write reviewable calendar candidate JSON from extracted items",
    )
    calendar_parser.add_argument("--limit", type=int, default=20)
    calendar_parser.add_argument("--dry-run", action="store_true")

    calendar_dispatch_parser = subparsers.add_parser(
        "calendar-dispatch",
        help="Create ready calendar events or write Telegram confirmation tasks",
    )
    calendar_dispatch_parser.add_argument("--limit", type=int, default=20)
    calendar_dispatch_parser.add_argument("--dry-run", action="store_true")
    calendar_dispatch_parser.add_argument(
        "--provider",
        choices=["json", "apple", "google"],
        default=None,
        help="Calendar provider; defaults to VOICE_NOTES_CALENDAR_PROVIDER or json",
    )

    subparsers.add_parser(
        "calendar-auth-google",
        help="Authorize Google Calendar without creating an event",
    )

    subparsers.add_parser("rebuild-catalog", help="Regenerate catalog.md from vault files")
    subparsers.add_parser("lint-wiki", help="Create a wiki health-check report")
    subparsers.add_parser("test-notification", help="Send a macOS notification without calling OpenAI")
    subparsers.add_parser("init-topics", help="Create default topic note files")
    return parser.parse_args()


def add_review_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scope",
        choices=["personal", "xhs", "all"],
        default="personal",
    )
    parser.add_argument("--query", default=None, help="Only include notes matching this text")
    parser.add_argument("--force", action="store_true", help="Replace an existing snippet")


def resolve_date_range(raw_from: str | None, raw_to: str | None) -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    if raw_from:
        date_from = dt.date.fromisoformat(raw_from)
    else:
        date_from = today - dt.timedelta(days=today.weekday())

    if raw_to:
        date_to = dt.date.fromisoformat(raw_to)
    else:
        date_to = date_from + dt.timedelta(days=6)
    return date_from, date_to


def resolve_note_date(raw_date: str | None) -> dt.date | None:
    if not raw_date:
        return None
    return dt.date.fromisoformat(raw_date)


def dispatch(args: argparse.Namespace) -> None:
    if args.command == "ingest":
        note_date = resolve_note_date(args.note_date)
        for source_file in args.source_files:
            ingest(source_file, note_date)
        return

    if args.command == "process-inbox":
        process_inbox(resolve_note_date(args.note_date), args.settle_seconds)
        return

    if args.command == "watch-inbox":
        watch_inbox(
            note_date=resolve_note_date(args.note_date),
            interval_seconds=args.interval_seconds,
            settle_seconds=args.settle_seconds,
            once=args.once,
        )
        return

    if args.command == "discard-inbox":
        discard_inbox(args.source_files, args.latest)
        return

    if args.command == "discard-deferred":
        discard_deferred(args.source_files, args.source_type, args.dry_run)
        return

    if args.command == "process-deferred-xhs":
        process_deferred_xhs(args.limit)
        return

    if args.command == "delete-note":
        delete_note(args.note_file, args.dry_run)
        return

    if args.command == "correct-note":
        correct_note(
            args.note_file,
            reason=args.reason,
            title=args.title,
            summary=args.summary,
            topics=parse_cli_list(args.topics),
            action_items=parse_cli_list(args.action_items),
            people=parse_cli_list(args.people),
            dry_run=args.dry_run,
        )
        return

    if args.command == "google-maps-save-queue":
        google_maps_save_queue(args.note_file, args.city, args.output, args.dry_run)
        return

    if args.command == "google-maps-task":
        google_maps_task(
            args.note_file,
            city=args.city,
            output_path=args.output,
            telegram_preview=args.telegram_preview,
        )
        return

    if args.command == "list-routes":
        list_routes()
        return

    if args.command == "route-note":
        route_note(args.note_file, dry_run=args.dry_run)
        return

    if args.command in {"weekly-review", "weekly-snippet"}:
        date_from, date_to = resolve_date_range(args.date_from, args.date_to)
        output_path = weekly_review(
            date_from,
            date_to,
            args.scope,
            args.query,
            args.force,
        )
        print(f"Saved snippet: {output_path}")
        return

    if args.command in {"monthly-review", "monthly-snippet"}:
        date_from, date_to = resolve_review_range("monthly", None, None)
        output_path = period_review(
            date_from,
            date_to,
            "monthly",
            args.scope,
            args.query,
            args.force,
        )
        print(f"Saved snippet: {output_path}")
        return

    if args.command == "scheduled-snippet":
        scheduled_snippet(args.period)
        return

    if args.command == "review":
        date_from, date_to = resolve_review_range(
            args.preset,
            args.date_from,
            args.date_to,
        )
        label = args.label or args.preset or "custom"
        output_path = period_review(
            date_from,
            date_to,
            label,
            args.scope,
            args.query,
            args.force,
        )
        print(f"Saved snippet: {output_path}")
        return

    if args.command == "search":
        results = search_notes(args.query, args.scope)
        if not results:
            print(f"No matches found for: {args.query}")
            return
        for path, line_number, line in results:
                print(f"{path_for_index(path)}:{line_number}: {line}")
        return

    if args.command == "capture":
        source_path, source_type = capture_manifest_as_regular_source(args.manifest)
        ingest(source_path, source_type=source_type)
        return

    if args.command == "capture-xhs":
        text = args.text
        if args.text_file:
            text = args.text_file.read_text(encoding="utf-8").strip()
        if args.video_file:
            imported = {
                "url": args.url,
                "title": args.title or "",
                "author": args.author or "",
                "text": text or "",
                "kind": "video",
                "video_url": "",
            }
        elif text:
            imported = {
                "url": args.url,
                "title": args.title or "",
                "author": args.author or "",
                "text": text,
                "kind": "article",
                "video_url": "",
            }
        else:
            print("Fetching XHS note...")
            imported = fetch_xhs_note(args.url)

        if imported.get("kind") == "video":
            if args.enqueue_only:
                raise SystemExit(
                    "--enqueue-only is not supported for video captures because "
                    "the evidence bundle must be built atomically."
                )
            ingest_xhs_video(imported, args.video_file)
        else:
            capture_path = prepare_xhs_source(
                args.url,
                text,
                title=args.title,
                author=args.author,
                imported=imported,
            )
            if args.enqueue_only:
                print(f"Queued XHS capture: {capture_path}")
            else:
                ingest(capture_path, source_type="xhs")
        return

    if args.command == "status":
        print(
            "Capture state tracking is deferred in lightweight mode. "
            "Check inbox/, processed/, daily/, xhs/, and log.md."
        )
        return

    if args.command == "cancel":
        print(
            "Capture IDs are not tracked in lightweight mode. "
            "Use discard-inbox --latest or pass the pending inbox filename."
        )
        return

    if args.command == "calendar-outbox":
        calendar_outbox(args.limit, args.dry_run)
        return

    if args.command == "calendar-dispatch":
        calendar_dispatch(args.limit, args.dry_run, args.provider)
        return

    if args.command == "calendar-auth-google":
        result = authorize_google_calendar()
        print(f"Google Calendar authorized for: {result['calendar_id']}")
        print(f"Token saved: {result['token_path']}")
        return

    if args.command == "rebuild-catalog":
        output_path = rebuild_catalog()
        append_log("catalog", "Rebuilt content catalog", [f"- Catalog: {obsidian_link(output_path)}"])
        print(f"Saved catalog: {output_path}")
        return

    if args.command == "lint-wiki":
        output_path = lint_wiki()
        print(f"Saved lint report: {output_path}")
        return

    if args.command == "test-notification":
        if send_notification("Notifications are working.", "Personal Operating System"):
            print("Notification test sent.")
        else:
            raise SystemExit("Notification test failed.")
        return

    if args.command == "init-topics":
        created = init_topics()
        if created:
            print("Created:")
            for path in created:
                print(f"- {path}")
        else:
            print("Topic files already exist.")
        return

    raise SystemExit(f"Unknown command: {args.command}")


def main() -> None:
    dispatch(parse_args())
