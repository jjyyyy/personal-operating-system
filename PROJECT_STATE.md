# Project State

Last reviewed: 2026-06-08

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
- On 2026-06-08, Xiaohongshu automation was paused after an account warning:
  the profile-monitor LaunchAgent was disabled and the local MCP container was
  stopped.
- Automatic inbox XHS imports are now opt-in via
  `VOICE_NOTES_AUTO_XHS_IMPORTS=1`; paused share files move to `deferred/xhs/`.
- Safe XHS resume path is now the deferred queue:
  `VOICE_NOTES_AUTO_XHS_IMPORTS=1 python3 src/voice_notes_ai.py process-deferred-xhs --limit 1`.
  Defaults are two automatic imports per day and a six-hour cooldown.
- The duplicate deferred XHS share from 2026-06-08 was discarded on 2026-06-09;
  `deferred/` is clear except `.gitkeep` files.
- `discard-deferred` and `correct-note` exist for deferred cleanup and semantic
  note corrections. Corrections update the note, index, catalog, and log.

## Current Risks

- `python3 -m unittest discover -s tests` passed on 2026-06-07.
- Latest lint flagged seed topic notes without source links:
  `topics/ai-development.md`, `topics/career.md`, `topics/health.md`,
  `topics/ideas.md`, and `topics/system-design.md`.
- Protected XHS media still needs a manual `--video-file`.
- Do not restart Xiaohongshu monitor/MCP automation without revisiting account
  risk. Prefer one-at-a-time deferred XHS imports until this is settled.
- Cron may need macOS Full Disk Access for iCloud inbox folders. Snippet cron is
  intentionally daily catch-up because this is a laptop and may sleep through a
  single weekly/monthly time.
- Private generated vault outputs remain intentionally ignored by Git.

## Next Tasks

1. Add source links or seed-note explanations for lint-flagged topic notes.
2. Add a short development/troubleshooting doc for Python, FFmpeg, cron, iCloud,
   notifications, and protected XHS media.
3. Use `correct-note` when analogies, ASR ambiguity, or primary topics are wrong
   so corrected notes can guide future snippets.
4. Preserve the `daily/` vs `xhs/` source boundary in snippets, search, and
   answers.
5. After a few more manual XHS imports without account warnings, decide whether
   cron should run `process-deferred-xhs --limit 1` with the safety switch.
