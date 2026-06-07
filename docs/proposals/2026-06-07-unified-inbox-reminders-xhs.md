# Unified Inbox, Reminders, and XHS Ingestion

Status: archived and reduced on 2026-06-07

## Decision

Do not turn this repository into a unified multi-source ingestion platform.
Its primary job is a lightweight personal Operating System:

```text
capture
-> transcript
-> daily note
-> weekly review
-> topic promotion
```

The earlier proposal introduced source envelopes, typed inboxes, SQLite job
state, embeddings, specialist modules, and a Google Calendar outbox. Those
components added more maintenance and failure modes than the current personal
workflow needs.

## Keep

- Audio and transcript capture through the existing inbox.
- Shared transcription service.
- One structured summary call.
- Daily Markdown notes, catalog, log, weekly reviews, and topic promotion.
- Optional AI comments inside the same summary call. Zero comments remains the
  normal result.
- `USER.md` as a small prompt hint for self aliases.
- Existing command names, with lightweight compatibility behavior where needed.

## Downgrade

- XHS capture uses one small URL importer and saves the result as an ordinary
  `source: xhs` note under `xhs/`. No state machine or specialist layer.
- Reminder requests remain action items in the daily note.
- Ambiguous identity references should be marked `unsure`; no rule engine should
  infer a person aggressively.

## Defer

- Automatic Google Calendar creation.
- Embeddings and vector storage.
- Bot channel bindings and delivery workflows.
- Authenticated XHS fetching. The importer reads only content exposed by a
  public share page and otherwise asks for explicit shared text.
- Cross-source deduplication and ingestion status tracking.

Revisit one of these only after repeated real usage demonstrates a concrete
problem that cannot be solved by Obsidian search, `catalog.md`, `log.md`, or a
small local helper.

## Delete

- `src/unified/` platform layer.
- SQLite ingestion/outbox/vector state.
- Typed `voice/`, `xhs/`, and `bot/` inbox hierarchy. Small source-specific
  subfolders under `processed/` and `discarded/` remain for basic hygiene.
- Platform-specific tests and configuration.

## Minimal Architecture

```text
iPhone Action Button or transcript
-> inbox/
-> src/transcription_service.py when audio
-> one OpenAI structured summary request
-> daily/
-> processed/voice/
-> index.json + catalog.md + log.md
-> weekly-review
-> topics/
```

XHS remains a lightweight parallel path: `capture-xhs -> xhs/ +
processed/xhs/`. It is not included in personal reviews unless explicitly
requested.

This proposal is retained only as an architectural decision record explaining
why the platform direction was rejected.
