# Google Calendar Provider Investigation

Last checked: 2026-06-09

## Conclusion

Google Calendar supports the provider shape needed by `calendar-dispatch`.
The provider is implemented in `src/google_calendar_provider.py` behind the
existing `calendar_flow.create_event` boundary.

The current flow should stay:

```text
voice memo
-> extracted_items
-> outbox/calendar/*.json candidate
-> calendar-dispatch
-> provider.create_event(candidate)
```

The Google provider should only replace the final provider call.

## Relevant Google API Facts

- Event creation uses `events.insert`:
  `POST https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events`.
- `calendarId=primary` targets the authenticated user's primary calendar.
- Event creation requires authorization.
- A timed event uses `start.dateTime`, `start.timeZone`, `end.dateTime`, and
  `end.timeZone`.
- For this app, the narrow useful OAuth scope is
  `https://www.googleapis.com/auth/calendar.events`, which can view and edit
  events on calendars the user can access. Broader
  `https://www.googleapis.com/auth/calendar` is not necessary for the first
  implementation.
- Google's Python quickstart uses a desktop OAuth client, `credentials.json`,
  `token.json`, `InstalledAppFlow`, and `googleapiclient.discovery.build`.

Official docs:

- https://developers.google.com/workspace/calendar/api/v3/reference/events/insert
- https://developers.google.com/workspace/calendar/api/guides/create-events
- https://developers.google.com/workspace/calendar/api/quickstart/python
- https://developers.google.com/workspace/calendar/api/auth

## Implemented Module

`src/google_calendar_provider.py` exposes:

```python
def create_google_calendar_event(candidate: dict, config: GoogleCalendarConfig) -> dict:
    ...
```

Return shape should match the current provider contract:

```json
{
  "provider": "google",
  "event_id": "...",
  "html_link": "...",
  "calendar_id": "primary",
  "status": "created"
}
```

`src/calendar_flow.py` dispatches to it with:

```python
if provider == "google":
    return create_google_calendar_event(candidate, google_calendar_config())
```

## Config

Use env vars:

```env
VOICE_NOTES_CALENDAR_PROVIDER=google
VOICE_NOTES_GOOGLE_CALENDAR_ID=primary
VOICE_NOTES_GOOGLE_CALENDAR_CREDENTIALS=secrets/google-calendar-credentials.json
VOICE_NOTES_GOOGLE_CALENDAR_TOKEN=secrets/google-calendar-token.json
VOICE_NOTES_GOOGLE_CALENDAR_SEND_UPDATES=none
```

Keep credentials and tokens ignored by Git. Do not store them in `outbox/`.

## Event Body

Map a resolved candidate to:

```json
{
  "summary": "按摩预约",
  "description": "Source: daily/...\nEvidence: 明天下午三点有一个按摩的appointment",
  "start": {
    "dateTime": "2026-06-10T15:00:00+02:00",
    "timeZone": "Europe/Madrid"
  },
  "end": {
    "dateTime": "2026-06-10T16:00:00+02:00",
    "timeZone": "Europe/Madrid"
  },
  "extendedProperties": {
    "private": {
      "source_project": "voice-notes",
      "source_note": "daily/...",
      "candidate_type": "voice_notes_calendar_candidate"
    }
  }
}
```

Call:

```python
service.events().insert(
    calendarId=calendar_id,
    body=event_body,
    sendUpdates=send_updates,
).execute()
```

Default `sendUpdates` should be `none` because these are personal reminders
without attendees.

## Approval Behavior

Do not route high-confidence resolved events through Telegram by default.
`calendar-dispatch` may create them directly.

Only write Telegram confirmation tasks for:

- low or medium confidence;
- `needs_confirmation: true`;
- unresolved date/time;
- any candidate with attendees, location ambiguity, or provider error.

Telegram approval belongs to OpenClaw. `voice-notes` should only write/read JSON
task artifacts.

## Setup Steps

1. Create an OAuth desktop client in Google Cloud and download credentials.
2. Save credentials at `secrets/google-calendar-credentials.json`.
3. Install dependencies from `pyproject.toml`.
4. Authorize without creating an event:

   ```bash
   python3 src/voice_notes_ai.py calendar-auth-google
   ```

5. The command opens a local browser OAuth flow and writes
   `secrets/google-calendar-token.json`.
6. To test command wiring without creating an event:

   ```bash
   python3 src/voice_notes_ai.py calendar-dispatch --dry-run --provider google
   ```
7. Run a real dispatch with:

   ```bash
   VOICE_NOTES_CALENDAR_PROVIDER=google python3 src/voice_notes_ai.py calendar-dispatch
   ```

8. Keep `json` provider as the default until the OAuth token is stable.

## Risks

- OAuth setup adds credential/token lifecycle complexity.
- Direct Google API is more explicit than Apple Calendar sync, but requires
  dependency installation and user consent.
- Duplicate creation should be prevented by marking candidates `created` after
  successful `events.insert`; for extra safety, use
  `extendedProperties.private.source_note` and candidate fingerprint.
