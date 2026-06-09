from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


@dataclass(frozen=True)
class GoogleCalendarConfig:
    calendar_id: str
    credentials_path: Path
    token_path: Path
    send_updates: str


def google_calendar_config() -> GoogleCalendarConfig:
    return GoogleCalendarConfig(
        calendar_id=os.environ.get("VOICE_NOTES_GOOGLE_CALENDAR_ID", "primary"),
        credentials_path=Path(
            os.environ.get(
                "VOICE_NOTES_GOOGLE_CALENDAR_CREDENTIALS",
                "secrets/google-calendar-credentials.json",
            )
        ).expanduser(),
        token_path=Path(
            os.environ.get(
                "VOICE_NOTES_GOOGLE_CALENDAR_TOKEN",
                "secrets/google-calendar-token.json",
            )
        ).expanduser(),
        send_updates=os.environ.get("VOICE_NOTES_GOOGLE_CALENDAR_SEND_UPDATES", "none"),
    )


def google_dependency_error(exc: ImportError) -> RuntimeError:
    error = RuntimeError(
        "Google Calendar provider requires google-api-python-client, "
        "google-auth-httplib2, and google-auth-oauthlib. Install project "
        "dependencies, then run the provider again."
    )
    error.__cause__ = exc
    return error


def google_event_body(candidate: dict[str, Any]) -> dict[str, Any]:
    event = candidate.get("event", {})
    start = event.get("start_datetime")
    end = event.get("end_datetime")
    timezone = event.get("timezone")
    if not start or not end or not timezone:
        raise ValueError("candidate event is not resolved")
    return {
        "summary": event.get("title") or candidate.get("text") or "Event",
        "description": "\n".join(
            [
                f"Source: {candidate.get('source_note') or ''}",
                f"Evidence: {candidate.get('evidence') or ''}",
            ]
        ).strip(),
        "start": {
            "dateTime": start,
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end,
            "timeZone": timezone,
        },
        "extendedProperties": {
            "private": {
                "source_project": "voice-notes",
                "source_note": str(candidate.get("source_note") or ""),
                "candidate_type": str(candidate.get("type") or ""),
            }
        },
    }


def load_google_credentials(config: GoogleCalendarConfig):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise google_dependency_error(exc)

    creds = None
    if config.token_path.exists():
        creds = Credentials.from_authorized_user_file(
            str(config.token_path),
            [GOOGLE_CALENDAR_SCOPE],
        )
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not config.credentials_path.exists():
                raise FileNotFoundError(
                    f"Google Calendar credentials not found: {config.credentials_path}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.credentials_path),
                [GOOGLE_CALENDAR_SCOPE],
            )
            creds = flow.run_local_server(port=0)
        config.token_path.parent.mkdir(parents=True, exist_ok=True)
        config.token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def create_google_calendar_event(
    candidate: dict[str, Any],
    config: GoogleCalendarConfig | None = None,
) -> dict[str, Any]:
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise google_dependency_error(exc)

    resolved_config = config or google_calendar_config()
    creds = load_google_credentials(resolved_config)
    service = build("calendar", "v3", credentials=creds)
    event = (
        service.events()
        .insert(
            calendarId=resolved_config.calendar_id,
            body=google_event_body(candidate),
            sendUpdates=resolved_config.send_updates,
        )
        .execute()
    )
    return {
        "provider": "google",
        "event_id": event.get("id"),
        "html_link": event.get("htmlLink"),
        "calendar_id": resolved_config.calendar_id,
        "status": "created",
    }
