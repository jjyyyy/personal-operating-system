# Voice Notes Routing API

Generic note routing lets another local project receive a small JSON package
when a processed note matches declared source/topic/title/summary rules.

`voice-notes` owns capture, transcription, note normalization, source archiving,
generic extracted-item classification, source archiving, and delivery. Target
projects own their own inbox processing and domain-specific interpretation.

## Registration

A target project can register itself by adding this file at its project root:

```text
voice-notes-routing.json
```

Example for `physical-therapy-assistant`:

```json
{
  "version": 1,
  "id": "physical-therapy-assistant",
  "target": "physical-therapy-assistant",
  "target_inbox": "inbox/voice-notes",
  "matches": {
    "source_any": ["voice"],
    "route_categories_any": ["health", "sports"]
  }
}
```

`target_inbox` is resolved relative to the manifest's project root. It must stay
under `/Users/jazzzz/Projects`.

`voice-notes` also supports local registrations under `routes/*.json`. In that
case `target_inbox` is resolved relative to the `voice-notes` project root:

```json
{
  "version": 1,
  "id": "physical-therapy-assistant",
  "target": "physical-therapy-assistant",
  "target_inbox": "../physical-therapy-assistant/inbox/voice-notes",
  "matches": {
    "route_categories_any": ["health", "sports"]
  }
}
```

## Match Fields

All match fields are optional. When present, every field must match.

- `source_any`: exact match against note source, such as `voice` or `xhs`.
- `route_categories_any`: exact match against extracted item route categories.
- `item_types_any`: exact match against extracted item type.
- `topics_any`: compatibility fallback against note topics.
- `title_any`: case-insensitive substring match against the title.
- `summary_any`: case-insensitive substring match against the summary.

Prefer `route_categories_any` over `topics_any`. Note topics are free-form
knowledge labels; route categories are a small stable vocabulary:

```text
calendar, health, sports, food, travel, work, projects, relationships,
finance, shopping, learning, home, system
```

Supported extracted item types:

```text
calendar_event, reminder, task, weak_intent, knowledge_note
```

Optional top-level fields:

- `enabled`: set to `false` to disable the route.
- `include_note_body`: set to `true` only when the target project needs a full
  copy of the Markdown note. The default package sends references and summary
  metadata only.

## Delivery Package

When a note has extracted items, matching items are delivered as JSON files
under the registered target inbox:

```json
{
  "type": "voice_notes_routed_item",
  "version": 1,
  "route_id": "physical-therapy-assistant",
  "target": "physical-therapy-assistant",
  "source_project": "voice-notes",
  "source_note": "daily/example.md",
  "source_file": "processed/voice/example.m4a",
  "source": "voice",
  "date": "2026-06-09",
  "title": "Example",
  "topics": ["网球"],
  "summary": "Short normalized note summary.",
  "raw_transcript_ref": "daily/example.md#Raw Transcript",
  "extracted_item": {
    "item_type": "knowledge_note",
    "text": "Tennis volley timing note",
    "date_text": null,
    "time_text": null,
    "route_categories": ["sports"],
    "calendar_ready": false,
    "needs_confirmation": false,
    "confidence": "high",
    "evidence": "tennis volley timing"
  }
}
```

Older notes without extracted items use the legacy whole-note package:

```json
{
  "type": "voice_notes_routed_note",
  "version": 1,
  "created_at": "2026-06-09T00:00:00+00:00",
  "route_id": "physical-therapy-assistant",
  "target": "physical-therapy-assistant",
  "source_project": "voice-notes",
  "source_note": "daily/example.md",
  "source_file": "processed/voice/example.m4a",
  "source": "voice",
  "date": "2026-06-09",
  "title": "Example",
  "topics": ["exercise"],
  "people": [],
  "summary": "Short normalized note summary.",
  "source_url": null,
  "source_kind": null,
  "raw_transcript_ref": "daily/example.md#Raw Transcript"
}
```

Target projects should treat this as an inbox event, not as a durable domain
record. They should create their own records, links, decisions, and follow-up
state from this package.

## Commands

List discovered registrations:

```bash
python3 src/voice_notes_ai.py list-routes
```

Route an existing tracked note:

```bash
python3 src/voice_notes_ai.py route-note daily/example.md --dry-run
python3 src/voice_notes_ai.py route-note daily/example.md
```

After `process-inbox`, `watch-inbox`, or `ingest` creates a note, matching
routes run automatically.
