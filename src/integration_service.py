from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from calendar_flow import build_calendar_candidate, create_event, telegram_confirmation_package
from extracted_items import (
    calendar_outbox_candidates,
    normalize_extracted_items,
    write_json as write_extracted_json,
)
from google_maps_flow import build_maps_candidates, maps_task_payload, render_maps_save_markdown, render_telegram_preview
from note_router import (
    deliver_item_route_package, deliver_route_package, item_matches_route,
    load_route_registrations, matching_registrations,
)
from voice_notes_config import (
    CALENDAR_CREATED_DIR, CALENDAR_OUTBOX_DIR, CALENDAR_TELEGRAM_DIR,
    MAPS_DIR, OUTBOX_DIR, ROUTES_DIR, VOICE_ROOT, ensure_dirs,
)
from vault_service import (
    append_log, find_index_item_for_note, obsidian_link, path_for_index,
    read_index, slugify, vault_path,
)


def read_json_file(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def google_maps_save_queue(
    note_path: Path,
    city: str = "",
    output_path: Path | None = None,
    dry_run: bool = False,
) -> Path:
    ensure_dirs()
    resolved_note = vault_path(note_path)
    note_text = resolved_note.read_text(encoding="utf-8")
    candidates = build_maps_candidates(note_text, city)
    if output_path:
        resolved_output = output_path.expanduser()
        if not resolved_output.is_absolute():
            resolved_output = MAPS_DIR / resolved_output
    else:
        resolved_output = MAPS_DIR / f"{resolved_note.stem}-google-maps-save-queue.md"

    rendered = render_maps_save_markdown(
        source_note=resolved_note,
        source_link=obsidian_link(resolved_note),
        city=city,
        candidates=candidates,
    )
    if dry_run:
        print(rendered)
        return resolved_output

    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(rendered, encoding="utf-8")
    append_log(
        "maps",
        f"Google Maps save queue for {resolved_note.stem}",
        [
            f"- Source note: {obsidian_link(resolved_note)}",
            f"- Output: {path_for_index(resolved_output)}",
            f"- Candidates: {len(candidates)}",
        ],
    )
    print(f"Saved Google Maps queue: {resolved_output}")
    print(f"Candidates: {len(candidates)}")
    return resolved_output


def google_maps_task(
    note_path: Path,
    city: str = "",
    output_path: Path | None = None,
    telegram_preview: bool = False,
) -> Path:
    ensure_dirs()
    resolved_note = vault_path(note_path)
    note_text = resolved_note.read_text(encoding="utf-8")
    candidates = build_maps_candidates(note_text, city)
    if output_path:
        resolved_output = output_path.expanduser()
        if not resolved_output.is_absolute():
            resolved_output = OUTBOX_DIR / "google-maps" / resolved_output
    else:
        resolved_output = OUTBOX_DIR / "google-maps" / f"{resolved_note.stem}-google-maps-task.json"

    payload = maps_task_payload(
        source_note=resolved_note,
        source_path=path_for_index(resolved_note),
        city=city,
        candidates=candidates,
    )
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    append_log(
        "maps-task",
        f"Google Maps task for {resolved_note.stem}",
        [
            f"- Source note: {obsidian_link(resolved_note)}",
            f"- Output: {path_for_index(resolved_output)}",
            f"- Candidates: {len(candidates)}",
        ],
    )
    print(f"Saved Google Maps task: {resolved_output}")
    print(f"Candidates: {len(candidates)}")
    if telegram_preview:
        print(render_telegram_preview(payload))
    return resolved_output


def route_registrations():
    return load_route_registrations(VOICE_ROOT, ROUTES_DIR)


def route_note(
    note_path: Path,
    dry_run: bool = False,
    *,
    strict: bool = True,
    verbose: bool = True,
) -> list[Path]:
    try:
        resolved_note = vault_path(note_path)
        note_item, _ = find_index_item_for_note(resolved_note)
        registrations = route_registrations()
        outputs: list[Path] = []
        extracted_items = normalize_extracted_items(note_item.get("extracted_items", []))
        if extracted_items:
            for item_index, item in enumerate(extracted_items, start=1):
                for registration in registrations:
                    if not item_matches_route(item, note_item, registration):
                        continue
                    output_path = deliver_item_route_package(
                        note_item,
                        resolved_note,
                        registration,
                        item,
                        item_index,
                        dry_run=dry_run,
                    )
                    outputs.append(output_path)
                    if verbose:
                        action = "Would route" if dry_run else "Routed"
                        print(
                            f"{action} item {item_index} from "
                            f"{path_for_index(resolved_note)} -> {output_path}"
                        )
                    if not dry_run:
                        append_log(
                            "route",
                            str(note_item.get("title") or resolved_note.stem),
                            [
                                f"- Source note: {obsidian_link(resolved_note)}",
                                f"- Item: {item.get('item_type')} | {item.get('text')}",
                                f"- Route: {registration.route_id}",
                                f"- Target: {registration.target}",
                                f"- Package: {output_path}",
                            ],
                        )
        else:
            matches = matching_registrations(note_item, registrations)
            for registration in matches:
                output_path = deliver_route_package(
                    note_item,
                    resolved_note,
                    registration,
                    dry_run=dry_run,
                )
                outputs.append(output_path)
                if verbose:
                    action = "Would route" if dry_run else "Routed"
                    print(f"{action} {path_for_index(resolved_note)} -> {output_path}")
                if not dry_run:
                    append_log(
                        "route",
                        str(note_item.get("title") or resolved_note.stem),
                        [
                            f"- Source note: {obsidian_link(resolved_note)}",
                            f"- Route: {registration.route_id}",
                            f"- Target: {registration.target}",
                            f"- Package: {output_path}",
                        ],
                    )
        if verbose and not outputs:
            print(f"No route matched: {path_for_index(resolved_note)}")
        return outputs
    except Exception as exc:
        if strict:
            raise SystemExit(str(exc)) from exc
        append_log(
            "error",
            f"route {note_path}",
            [
                f"- Note: {note_path}",
                f"- Error: {type(exc).__name__}: {exc}",
            ],
        )
        return []


def list_routes() -> list:
    try:
        registrations = route_registrations()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not registrations:
        print("No route registrations found.")
        return registrations
    for registration in registrations:
        print(f"{registration.route_id} -> {registration.target_inbox}")
        print(f"  target: {registration.target}")
        print(f"  manifest: {registration.manifest_path}")
    return registrations


def calendar_candidate_path(note_item: dict, item: dict) -> Path:
    note_stem = slugify(Path(str(note_item.get("note_file", "note"))).stem)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "source_note": note_item.get("note_file"),
                "text": item.get("text"),
                "date_text": item.get("date_text"),
                "time_text": item.get("time_text"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return CALENDAR_OUTBOX_DIR / f"{note_stem}-{fingerprint}.json"


def calendar_outbox(limit: int = 20, dry_run: bool = False) -> list[Path]:
    ensure_dirs()
    if limit <= 0:
        raise SystemExit("--limit must be at least 1.")
    outputs: list[Path] = []
    for note_item in read_index():
        for item in calendar_outbox_candidates(note_item):
            output_path = calendar_candidate_path(note_item, item)
            if output_path.exists() and not dry_run:
                existing = read_json_file(output_path, {})
                if existing.get("version") == 2:
                    continue
            outputs.append(output_path)
            if not dry_run:
                package = build_calendar_candidate(item, note_item)
                write_extracted_json(output_path, package)
                append_log(
                    "calendar-outbox",
                    str(note_item.get("title") or output_path.stem),
                    [
                        f"- Source note: {note_item.get('note_file')}",
                        f"- Candidate: {item.get('text')}",
                        f"- Output: {path_for_index(output_path)}",
                    ],
                )
            if len(outputs) >= limit:
                break
        if len(outputs) >= limit:
            break

    if outputs:
        action = "Would write" if dry_run else "Wrote"
        for output_path in outputs:
            print(f"{action} calendar candidate: {output_path}")
    else:
        print("No calendar-ready extracted items found.")
    return outputs


def calendar_telegram_path(candidate_path: Path) -> Path:
    return CALENDAR_TELEGRAM_DIR / f"{candidate_path.stem}-telegram.json"


def update_candidate(path: Path, candidate: dict) -> None:
    write_extracted_json(path, candidate)


def calendar_dispatch(
    limit: int = 20,
    dry_run: bool = False,
    provider: str | None = None,
) -> list[Path]:
    ensure_dirs()
    if limit <= 0:
        raise SystemExit("--limit must be at least 1.")
    selected_provider = provider or os.environ.get("VOICE_NOTES_CALENDAR_PROVIDER", "json")
    handled: list[Path] = []
    for candidate_path in sorted(CALENDAR_OUTBOX_DIR.glob("*.json")):
        candidate = read_json_file(candidate_path, {})
        status = str(candidate.get("status") or "")
        if status == "needs_telegram_confirmation":
            telegram_path = calendar_telegram_path(candidate_path)
            handled.append(telegram_path)
            if not dry_run and not telegram_path.exists():
                candidate["candidate_path"] = path_for_index(candidate_path)
                write_extracted_json(telegram_path, telegram_confirmation_package(candidate))
                candidate["status"] = "telegram_confirmation_sent"
                candidate["telegram_task"] = path_for_index(telegram_path)
                update_candidate(candidate_path, candidate)
                append_log(
                    "calendar-telegram",
                    str(candidate.get("text") or candidate_path.stem),
                    [
                        f"- Candidate: {path_for_index(candidate_path)}",
                        f"- Telegram task: {path_for_index(telegram_path)}",
                    ],
                )
            action = "Would send Telegram confirmation" if dry_run else "Telegram confirmation task"
            print(f"{action}: {telegram_path}")
        elif status == "ready_to_create":
            handled.append(candidate_path)
            if not dry_run:
                result = create_event(candidate, selected_provider, CALENDAR_CREATED_DIR)
                candidate["status"] = "created"
                candidate["created_with_provider"] = result
                update_candidate(candidate_path, candidate)
                append_log(
                    "calendar-create",
                    str(candidate.get("text") or candidate_path.stem),
                    [
                        f"- Candidate: {path_for_index(candidate_path)}",
                        f"- Provider: {selected_provider}",
                        f"- Event: {result.get('event_id')}",
                    ],
                )
            action = "Would create calendar event" if dry_run else "Created calendar event"
            print(f"{action}: {candidate_path}")
        if len(handled) >= limit:
            break
    if not handled:
        print("No pending calendar candidates to dispatch.")
    return handled
