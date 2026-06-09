from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROUTE_MANIFEST_NAME = "voice-notes-routing.json"


@dataclass(frozen=True)
class RouteRegistration:
    route_id: str
    target: str
    target_inbox: Path
    matches: dict[str, Any]
    manifest_path: Path
    include_note_body: bool = False


def slugify(value: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", value.lower()).strip("-")
    return slug or "route"


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid route manifest JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"route manifest must be a JSON object: {path}")
    return payload


def resolve_target_inbox(raw_path: str, base_dir: Path, projects_root: Path) -> Path:
    inbox = Path(raw_path).expanduser()
    if not inbox.is_absolute():
        inbox = base_dir / inbox
    resolved = inbox.resolve()
    try:
        resolved.relative_to(projects_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"route target_inbox must stay under {projects_root}: {raw_path}"
        ) from exc
    return resolved


def registration_from_manifest(
    manifest_path: Path,
    *,
    base_dir: Path,
    projects_root: Path,
) -> RouteRegistration | None:
    payload = read_json(manifest_path)
    if payload.get("enabled", True) is False:
        return None
    version = payload.get("version")
    if version != 1:
        raise ValueError(f"route manifest version must be 1: {manifest_path}")
    route_id = str(payload.get("id") or "").strip()
    target = str(payload.get("target") or "").strip()
    target_inbox = str(payload.get("target_inbox") or "").strip()
    matches = payload.get("matches", {})
    if not route_id:
        raise ValueError(f"route manifest missing id: {manifest_path}")
    if not target:
        raise ValueError(f"route manifest missing target: {manifest_path}")
    if not target_inbox:
        raise ValueError(f"route manifest missing target_inbox: {manifest_path}")
    if not isinstance(matches, dict):
        raise ValueError(f"route manifest matches must be an object: {manifest_path}")
    return RouteRegistration(
        route_id=route_id,
        target=target,
        target_inbox=resolve_target_inbox(target_inbox, base_dir, projects_root),
        matches=matches,
        manifest_path=manifest_path,
        include_note_body=bool(payload.get("include_note_body", False)),
    )


def load_route_registrations(voice_root: Path, routes_dir: Path) -> list[RouteRegistration]:
    projects_root = voice_root.resolve().parent
    registrations: list[RouteRegistration] = []
    seen: set[str] = set()
    manifest_specs: list[tuple[Path, Path]] = []

    if routes_dir.exists():
        manifest_specs.extend((path, voice_root) for path in sorted(routes_dir.glob("*.json")))

    for project_manifest in sorted(projects_root.glob(f"*/{ROUTE_MANIFEST_NAME}")):
        if project_manifest.parent.resolve() == voice_root.resolve():
            continue
        manifest_specs.append((project_manifest, project_manifest.parent))

    for manifest_path, base_dir in manifest_specs:
        registration = registration_from_manifest(
            manifest_path,
            base_dir=base_dir,
            projects_root=projects_root,
        )
        if registration is None:
            continue
        if registration.route_id in seen:
            raise ValueError(f"duplicate route id: {registration.route_id}")
        seen.add(registration.route_id)
        registrations.append(registration)
    return registrations


def lower_values(values: object) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values.casefold()]
    if isinstance(values, list):
        return [str(value).casefold() for value in values]
    raise ValueError("route match values must be strings or string arrays")


def any_exact_match(actual_values: list[str], expected_values: object) -> bool:
    expected = set(lower_values(expected_values))
    if not expected:
        return True
    actual = {value.casefold() for value in actual_values}
    return bool(actual & expected)


def any_substring_match(actual_text: str, expected_values: object) -> bool:
    expected = lower_values(expected_values)
    if not expected:
        return True
    text = actual_text.casefold()
    return any(value in text for value in expected)


def note_matches_route(note_item: dict[str, Any], registration: RouteRegistration) -> bool:
    matches = registration.matches
    if not any_exact_match([str(note_item.get("source", ""))], matches.get("source_any")):
        return False
    if not any_exact_match(
        [str(topic) for topic in note_item.get("topics", [])],
        matches.get("topics_any"),
    ):
        return False
    if not any_substring_match(str(note_item.get("title", "")), matches.get("title_any")):
        return False
    if not any_substring_match(str(note_item.get("summary", "")), matches.get("summary_any")):
        return False
    return True


def raw_section_ref(note_file: str, source: str) -> str:
    heading = "Imported Content" if source == "xhs" else "Raw Transcript"
    return f"{note_file}#{heading}"


def route_package(
    note_item: dict[str, Any],
    registration: RouteRegistration,
    *,
    note_text: str | None = None,
) -> dict[str, Any]:
    note_file = str(note_item.get("note_file", ""))
    source = str(note_item.get("source", "voice"))
    package = {
        "type": "voice_notes_routed_note",
        "version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "route_id": registration.route_id,
        "target": registration.target,
        "source_project": "voice-notes",
        "source_note": note_file,
        "source_file": note_item.get("source_file"),
        "source": source,
        "date": note_item.get("date"),
        "title": note_item.get("title"),
        "topics": note_item.get("topics", []),
        "people": note_item.get("people", []),
        "summary": note_item.get("summary"),
        "source_url": note_item.get("source_url"),
        "source_kind": note_item.get("source_kind"),
        "raw_transcript_ref": raw_section_ref(note_file, source),
    }
    if registration.include_note_body and note_text is not None:
        package["note_body"] = note_text
    return package


def unique_package_path(target_inbox: Path, route_id: str, note_file: str) -> Path:
    note_stem = Path(note_file).stem
    base_name = f"{slugify(route_id)}-{slugify(note_stem)}"
    destination = target_inbox / f"{base_name}.json"
    counter = 1
    while destination.exists():
        destination = target_inbox / f"{base_name}-{counter}.json"
        counter += 1
    return destination


def deliver_route_package(
    note_item: dict[str, Any],
    note_path: Path,
    registration: RouteRegistration,
    *,
    dry_run: bool = False,
) -> Path:
    note_text = note_path.read_text(encoding="utf-8") if registration.include_note_body else None
    package = route_package(note_item, registration, note_text=note_text)
    destination = unique_package_path(
        registration.target_inbox,
        registration.route_id,
        str(note_item.get("note_file", "")),
    )
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(package, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return destination


def matching_registrations(
    note_item: dict[str, Any],
    registrations: list[RouteRegistration],
) -> list[RouteRegistration]:
    return [
        registration
        for registration in registrations
        if note_matches_route(note_item, registration)
    ]
