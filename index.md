# Personal Operating System Index

Primary context file for any AI assistant working in this vault.

## Context Check

If asked whether you have read the vault context, answer with:

```text
VOICE_NOTES_INDEX_VERSION: 2026-06-06-context-v1
Required first files: index.md, AGENTS.md
Current promoted topics: sports-technique, 网球
Preferred inbox command: python3 src/voice_notes_ai.py process-inbox
```

If you cannot answer with this marker, read `index.md` before proceeding.

## Goal

Turn captures and transcripts into a durable Obsidian-style knowledge system. Do not treat transcripts as the final artifact. Convert them into daily notes, then promote repeated ideas, actions, people, decisions, and long-term patterns into topic notes.

## Read Order

When answering or modifying the vault, read in this order:

1. `index.md`: current AI entry point.
2. `AGENTS.md`: operating rules and schema.
3. `00-home.md`: human-facing vault map.
4. Relevant `topics/` files: durable topic memory.
5. Recent `snippets/` files: weekly/monthly synthesis.
6. Recent `reviews/` files: lint and maintenance reports.
7. Relevant `daily/` files: personal notes and reflections.
8. Relevant `xhs/` files: imported external knowledge.
9. `Raw Transcript` only when details are needed.

Use `catalog.md` only when broad discovery is needed. It is intentionally separate from this file so `index.md` stays small enough for simple queries.

## Directory Map

- `inbox/`: unprocessed audio files or transcripts.
- `processed/`: archived source files grouped under `voice/`, `xhs/`, and `bot/`.
- `discarded/`: accidental inbox recordings moved out of processing.
- `daily/`: structured personal voice notes and reflections.
- `xhs/`: imported XHS knowledge, separate from personal input.
- `snippets/`: weekly/monthly synthesis snippets.
- `reviews/`: lint and maintenance reports.
- `topics/`: long-term topic notes. Prefer updating these over creating many new files.
- `templates/`: Markdown templates.
- `prompts/`: reusable AI prompts.
- `docs/action-button-flow.md`: Action Button to parsed note setup.
- `docs/xhs-share-capture.md`: Share Sheet / Shortcut flow for XHS links.
- `docs/openclaw-integration.md`: OpenClaw agent connection and security notes.
- `docs/proposals/`: detailed proposals that are not yet implemented.
- `docs/proposals/2026-06-07-unified-inbox-reminders-xhs.md`: archived decision record explaining why the multi-source platform direction was reduced.
- `automation/`: optional LaunchAgent template for `watch-inbox`.
- `src/voice_notes_ai.py`: local processing script.
- `index.json`: machine-readable daily-note index.
- `catalog.md`: generated content catalog for broad discovery.
- `log.md`: append-only operation timeline.
- `AGENTS.md`: tool-native agent schema and working rules.
- `CLAUDE.md`: thin Claude/Claudian entry point that delegates to `index.md` and `AGENTS.md`.

## Current Topic Notes

- [[topics/career|Career]]
- [[topics/health|Health]]
- [[topics/ideas|Ideas]]
- [[topics/system-design|System Design]]
- [[topics/sports-technique|Sports Technique]]
- [[topics/网球|网球]]

## Operating Commands

Process the whole inbox:

```bash
python3 src/voice_notes_ai.py process-inbox
```

Watch the inbox for Action Button captures:

```bash
python3 src/voice_notes_ai.py watch-inbox --interval 30 --settle-seconds 20
```

Discard the newest accidental inbox capture:

```bash
python3 src/voice_notes_ai.py discard-inbox --latest
```

Delete a generated note and its archived source:

```bash
python3 src/voice_notes_ai.py delete-note xhs/your-note.md --dry-run
python3 src/voice_notes_ai.py delete-note xhs/your-note.md
```

Process one file:

```bash
python3 src/voice_notes_ai.py ingest inbox/your-note.m4a
python3 src/voice_notes_ai.py ingest inbox/your-note.txt
```

Set the original recording date:

```bash
python3 src/voice_notes_ai.py ingest inbox/your-note.m4a --date 2026-06-06
```

Search the vault:

```bash
python3 src/voice_notes_ai.py search 网球 --scope personal
python3 src/voice_notes_ai.py search 网球 --scope xhs
python3 src/voice_notes_ai.py search 网球 --scope all
```

Import a copied XHS share link:

```bash
python3 src/voice_notes_ai.py capture-xhs --url "https://xhslink.com/..."
```

Or save shared XHS text into the inbox or `inbox/xhs/` as `xhs-share-*.txt`; see
`docs/xhs-share-capture.md`.

If a protected video cannot be downloaded directly:

```bash
python3 src/voice_notes_ai.py capture-xhs --url "https://xhslink.com/..." --video-file "/path/to/video.mp4"
```

Create a weekly snippet:

```bash
python3 src/voice_notes_ai.py weekly-snippet
```

Create monthly or custom snippets:

```bash
python3 src/voice_notes_ai.py monthly-snippet
python3 src/voice_notes_ai.py review --from 2026-01-01 --to 2026-03-31 --label project-quarter --query "project name"
```

Regenerate the broad catalog:

```bash
python3 src/voice_notes_ai.py rebuild-catalog
```

Create a wiki health-check report:

```bash
python3 src/voice_notes_ai.py lint-wiki
```

Test macOS notifications without calling OpenAI:

```bash
python3 src/voice_notes_ai.py test-notification
```

## AI Behavior Rules

- Keep 1-5 topics per voice note.
- Prefer existing topic notes. Do not create a new file for every keyword.
- Create or update a topic note only when the content repeats, affects long-term decisions, represents an ongoing project/goal/risk, or contains reusable principles.
- Preserve existing topic-note judgments. Add only new evidence, patterns, actions, or questions.
- Action items must be concrete and executable. Do not turn vague ideas into tasks.
- Mark uncertain classification as `unsure`.
- Keep personal captures (`source: voice`) distinguishable from imported XHS
  knowledge (`source: xhs`). Use scoped search when the distinction matters.
- When answering questions, start with the conclusion, cite relevant notes, and distinguish evidence from inference.

## Current State

Working pipeline:

```text
iPhone Voice Memo
-> inbox/
-> process-inbox / watch-inbox / ingest
-> daily/
-> processed/voice/
-> catalog.md / log.md
-> topics/
-> Obsidian search and AI Q&A
```

XHS imports follow the parallel external-knowledge path:

```text
XHS share link -> xhs/ + processed/xhs/
```

Current promoted topics:

- `topics/sports-technique.md`: cross-sport technique patterns.
- `topics/网球.md`: tennis forehand/backhand notes.

## Next Good Steps

- Keep processing new recordings.
- Generate a weekly snippet once enough notes accumulate.
- Use weekly snippets to update or create topic notes.
- Run `lint-wiki` periodically to catch missing links, stale claims, and promotion candidates.
- If tennis notes keep growing, continue expanding `topics/网球.md` or create a separate `topics/tennis.md`.
