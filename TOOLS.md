# Personal Operating System Tools

## Project

- Workspace: `/Users/jazzzz/Projects/voice-notes`
- AI entry point: `index.md`
- Operating rules: `AGENTS.md`
- Broad catalog: `catalog.md`
- Operation history: `log.md`

## Safe Read Commands

```bash
python3 src/voice_notes_ai.py search QUERY
python3 src/voice_notes_ai.py rebuild-catalog
python3 src/voice_notes_ai.py lint-wiki
```

## Mutating Commands

Run these only when the user's request requires them:

```bash
python3 src/voice_notes_ai.py process-inbox --settle-seconds 60
python3 src/voice_notes_ai.py discard-inbox --latest
python3 src/voice_notes_ai.py weekly-review
```

## Security

- Never print or expose `.env`, API keys, OpenClaw tokens, or credentials.
- Do not send vault content to messaging channels unless the user explicitly requests delivery.
- Do not modify files outside this workspace.
- Do not process or delete audio merely because it exists; follow the documented inbox workflow.
