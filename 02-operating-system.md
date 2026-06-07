# Personal Operating System

## Per Voice Note

1. Put audio files or transcripts into `inbox/`.
2. Run the ingest script to create a daily note.
3. Quickly check title, topics, and action items.
4. If the note is important, add or update the relevant topic note.

Recommended command:

```bash
python3 src/voice_notes_ai.py ingest inbox/your-note.m4a
```

For an existing transcript:

```bash
python3 src/voice_notes_ai.py ingest inbox/your-note.txt
```

Set the original recording date:

```bash
python3 src/voice_notes_ai.py ingest inbox/your-note.m4a --date 2026-06-06
```

Process the whole inbox:

```bash
python3 src/voice_notes_ai.py process-inbox
```

Watch for synced Action Button captures:

```bash
python3 src/voice_notes_ai.py watch-inbox --interval 30 --settle-seconds 20
```

Use `docs/action-button-flow.md` to set up the iPhone Shortcut and optional LaunchAgent.

Cancel the newest accidental inbox recording before it is processed:

```bash
python3 src/voice_notes_ai.py discard-inbox --latest
```

## Daily

Keep daily maintenance light:

- Check that new note topics are not obviously wrong.
- Move concrete action items into the real task system.
- Do not over-classify on the same day.
- If using Action Button capture, glance at `log.md` to confirm the watcher parsed the note.

Quick search:

```bash
python3 src/voice_notes_ai.py search 网球
```

For broad discovery, regenerate and read the catalog:

```bash
python3 src/voice_notes_ai.py rebuild-catalog
```

## Weekly

Create a weekly synthesis:

```bash
python3 src/voice_notes_ai.py weekly-review
```

Then ask AI to:

1. Extract repeated themes.
2. Suggest what should be promoted into `topics/`.
3. List the most important next actions.

## Monthly

Do a stronger cleanup:

- Merge duplicate topics.
- Clean stale action items.
- Identify long-term patterns.
- Update core judgments in `topics/`.
- Write a monthly review.
- Run a wiki lint pass:

```bash
python3 src/voice_notes_ai.py lint-wiki
```

## Topic Note Update Rules

Update a topic note when at least one is true:

- The same theme appears more than once.
- The note changes future decisions.
- It represents a long-term problem, goal, or risk.
- It contains reusable methods, principles, or experience.
- It relates to an important person, project, or direction.

## AI Read Priority

When asking AI a question, prefer this order:

1. Files explicitly mentioned in the question.
2. Relevant files in `topics/`.
3. Recent weekly/monthly reviews in `reviews/`.
4. Relevant dated notes or keywords in `daily/`.
5. `Raw Transcript` only when needed.

Use `catalog.md` only for broad discovery, not as mandatory context for every question. Use `log.md` when the question depends on recent operations.

## Avoid

- Do not paste every transcript into one giant document.
- Do not manually create complex categories for every note.
- Do not design a deep taxonomy too early.
- Do not make AI reread the whole vault every time.
- Do not turn topic notes into chronological logs.
