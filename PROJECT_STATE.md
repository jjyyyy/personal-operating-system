# Project State

Last reviewed: 2026-06-07

For project intro, commands, and agent rules, read `index.md`, `AGENTS.md`, and
`README.md`. This file is only a handoff note for someone returning to the work.

## Current Direction

- Keep the repo lightweight and file-first.
- Do not restart the unified ingestion platform direction; that decision is in
  `docs/proposals/2026-06-07-unified-inbox-reminders-xhs.md`.
- Keep `src/voice_notes_ai.py` as the main CLI for now.
- When a nearby change makes it natural, extract stable pieces from
  `voice_notes_ai.py` into focused modules.
- Good future module boundaries: note rendering/path helpers, snippets/reports,
  catalog/lint, and CLI parsing.

## Recently Landed

- Implementation milestone committed: lightweight XHS/share/video ingestion,
  snippets, scoped search, `delete-note`, and updated docs/tests.
- Voice/transcript ingest, inbox watching, discard, notifications, catalog,
  log, snippet, search, and lint flows are present.
- `delete-note` removes an indexed note plus its archived source, then updates
  `index.json`, `catalog.md`, and `log.md`.
- Optional AI annotations are implemented; Agent Briefing is still proposal-only.
- XHS text import writes separate `source: xhs` notes under `xhs/`.
- XHS share files named `xhs-share-*.txt` in the inbox now route through the
  same importer used by `capture-xhs`.
- XHS video ingestion now builds archived evidence packages that separate
  speech, visible evidence, OCR/visible text, and AI interpretation.
- iCloud placeholder hydration and transient OpenAI retry handling were added
  after real ingestion failures.
- Weekly/monthly personal synthesis now lands in `snippets/`; `reviews/` is for
  lint and maintenance reports.
- Latest weekly snippet was corrected to a more personal Mandarin style, and
  the 2026-06-06 tennis serve/volley notes were corrected after badminton and
  volleyball were over-promoted from analogy/ASR ambiguity.

## Current Risks

- `python3 -m unittest discover -s tests` passed on 2026-06-07.
- Latest lint flagged seed topic notes without source links:
  `topics/ai-development.md`, `topics/career.md`, `topics/health.md`,
  `topics/ideas.md`, and `topics/system-design.md`.
- Protected XHS media still needs a manual `--video-file`.
- Cron may need macOS Full Disk Access for iCloud inbox folders. Snippet cron is
  intentionally daily catch-up because this is a laptop and may sleep through a
  single weekly/monthly time.
- Private generated vault outputs remain intentionally ignored by Git.

## Next Tasks

1. Add source links or seed-note explanations for lint-flagged topic notes.
2. Add a short development/troubleshooting doc for Python, FFmpeg, cron, iCloud,
   notifications, and protected XHS media.
3. Keep tightening daily-note prompts and correction workflow so analogies,
   ASR ambiguity, and primary topics stay separate.
4. Preserve the `daily/` vs `xhs/` source boundary in snippets, search, and
   answers.
