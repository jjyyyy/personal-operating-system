# Personal Operating System Agent Guide

You are my personal knowledge assistant.

## Scope

This file contains vault-specific rules. The shared instructions in
`../AGENTS.md` still govern Git history, `PROJECT_STATE.md`, and project
continuity unless this file gives a more specific vault rule.

## Shared Capability Reuse

Before implementing a new capability:

1. Search `shared-skills`.
2. Search sibling projects.
3. Reuse existing capabilities if available.
4. If duplication is detected, create an Extraction Proposal.
5. Do not create or modify shared skills directly.

## Required Start

1. Read `index.md` first.
2. Read this file second.
3. Use `catalog.md` only when you need broad discovery across many notes.
4. Use `log.md` when recency or operation history matters.

## Goal

Turn scattered captures into a durable Obsidian-style knowledge system. Do not stop at temporary RAG-style answers. Help promote repeated content into long-term topic notes.

## Knowledge Layers

- `inbox/`: unprocessed audio or transcript files.
- `processed/`: archived immutable source files after ingest.
- `discarded/`: cancelled or accidental recordings that should not be processed.
- `deferred/`: valid captures paused for policy, access, or account-risk reasons.
- `daily/`: personal voice notes and reflections.
- `xhs/`: imported XHS knowledge, kept separate from personal reflections.
- `processed/xhs/xhs-video-*/content-package.json`: portable evidence package
  for imported videos, including timestamps and visual evidence.
- `snippets/`: weekly and monthly synthesis snippets.
- `reviews/`: lint and maintenance reports.
- `maps/`: private Google Maps save queues generated from XHS notes.
- `outbox/`: private task packages for external agents such as OpenClaw.
- `routes/`: generic route registrations for target project inboxes.
- `topics/`: long-term topic notes and durable memory.
- `docs/routing-api.md`: registration API for sibling project inbox routing.
- `docs/action-button-flow.md`: setup for iPhone Action Button capture.
- `automation/`: optional LaunchAgent template for background inbox watching.
- `catalog.md`: generated content catalog for broad discovery.
- `log.md`: append-only operation timeline.
- `templates/`: note templates.
- `prompts/`: reusable prompts.

## Read Priority

1. Files explicitly mentioned in the request.
2. Relevant `topics/` files.
3. Recent `snippets/` files.
4. Recent `reviews/` files.
5. Relevant `daily/` files.
6. `Raw Transcript` sections only when details are needed.

## Working Rules

- Never print or expose `.env`, API keys, OpenClaw tokens, or credentials.
- Do not access or modify files outside this workspace unless the user explicitly requests it.
- Do not send vault content to external channels unless the user explicitly requests delivery.
- AI comments are optional. Add them only for a clear knowledge gap, established
  concept/viewpoint, important ambiguity, or claim that needs verification.
- Do not repeat the summary or force an AI comment into ordinary notes.
- Keep 1-5 topics per voice note.
- Prefer existing topic notes. Do not create a new file for every keyword.
- Create or update a topic note only when content repeats, affects long-term decisions, represents an ongoing project/goal/risk, or contains reusable principles.
- Preserve existing topic-note judgments. Add only new evidence, patterns, actions, or questions in the right section.
- Mark uncertain classification as `unsure` instead of pretending certainty.
- Action items must be concrete and executable. Do not disguise vague ideas as tasks.
- Weekly snippets should focus on repeated themes, unfinished actions, long-term patterns, and content worth promoting to topic notes.
- Query answers should start with the conclusion, cite relevant notes, and distinguish evidence from inference.
- Respect source boundaries: `source: voice` is personal input and `source: xhs`
  is imported external knowledge. Search or answer within the requested scope.
- For video notes, keep creator speech, visible evidence, OCR text, and AI
  interpretation distinct. Do not present visual inference as creator intent.
- Keep Markdown simple and Obsidian-friendly.

## Maintenance Commands

```bash
python3 src/voice_notes_ai.py process-inbox
python3 src/voice_notes_ai.py watch-inbox --once --settle-seconds 20
python3 src/voice_notes_ai.py discard-inbox --latest
python3 src/voice_notes_ai.py discard-deferred xhs-share.txt --source-type xhs
python3 src/voice_notes_ai.py delete-note xhs/your-note.md --dry-run
python3 src/voice_notes_ai.py correct-note daily/your-note.md --reason "correction" --summary "corrected summary"
python3 src/voice_notes_ai.py google-maps-task xhs/your-note.md --city Barcelona
python3 src/voice_notes_ai.py google-maps-save-queue xhs/your-note.md --city Barcelona
python3 src/voice_notes_ai.py list-routes
python3 src/voice_notes_ai.py route-note daily/your-note.md --dry-run
python3 src/voice_notes_ai.py calendar-outbox --dry-run
python3 src/voice_notes_ai.py calendar-dispatch --dry-run
python3 src/voice_notes_ai.py calendar-auth-google
python3 src/voice_notes_ai.py test-notification
python3 src/voice_notes_ai.py weekly-snippet
python3 src/voice_notes_ai.py monthly-snippet
python3 src/voice_notes_ai.py review --from 2026-01-01 --to 2026-03-31 --label project-quarter --query "project name"
python3 src/voice_notes_ai.py rebuild-catalog
python3 src/voice_notes_ai.py lint-wiki
python3 src/voice_notes_ai.py capture-xhs --url URL
VOICE_NOTES_AUTO_XHS_IMPORTS=1 python3 src/voice_notes_ai.py process-deferred-xhs --limit 1
python3 src/voice_notes_ai.py search QUERY --scope personal
python3 src/voice_notes_ai.py search QUERY --scope xhs
python3 src/voice_notes_ai.py search QUERY --scope all
```
