# Personal Operating System

Human-facing entry point for this personal knowledge base.

The goal is not to pile up recordings in a searchable archive. The goal is to turn everyday captures into reusable knowledge pages, decision records, action items, and long-term themes.

## Quick Links

- [[index|AI Index]]
- [[AGENTS|Agent Guide]]
- [[catalog|Catalog]]
- [[log|Log]]
- [[docs/action-button-flow|Action Button Flow]]
- [[docs/openclaw-integration|OpenClaw Integration]]
- [[docs/proposals/2026-06-07-ai-annotations-and-agent-briefing|AI Annotations & Agent Briefing Proposal]]
- [[docs/proposals/2026-06-07-unified-inbox-reminders-xhs|Why the Unified Inbox Platform Was Reduced]]
- [[01-methodology|Methodology]]
- [[02-operating-system|Operating System]]
- [[topics/career|Career]]
- [[topics/health|Health]]
- [[topics/system-design|System Design]]
- [[topics/ai-development|AI Development]]
- [[topics/ideas|Ideas]]
- [[topics/sports-technique|Sports Technique]]
- [[topics/网球|网球]]

## Knowledge Layers

```text
raw audio
-> transcript
-> daily voice note
-> weekly snippet
-> topic note
-> durable personal wiki
```

## Directory Map

- `inbox/`: unprocessed recordings or transcripts
- `processed/`: archived source files grouped by voice, XHS, or bot
- `daily/`: personal voice notes and reflections
- `xhs/`: imported XHS knowledge
- `snippets/`: weekly/monthly synthesis snippets
- `reviews/`: lint and maintenance reports
- `topics/`: long-term topic notes
- `docs/`: setup notes
- `automation/`: optional background watcher template
- `catalog.md`: generated broad content catalog
- `log.md`: chronological operation log
- `AGENTS.md`: AI assistant operating rules
- `templates/`: note templates
- `prompts/`: prompts for AI assistants
- `AGENTS.md`: agent-facing rules
- `CLAUDE.md`: Claude/Claudian entry point

## Weekly Maintenance

1. Process this week's recordings into `daily/` notes.
2. Create one weekly snippet in `snippets/`.
3. Extract durable themes from the weekly snippet and update `topics/`.
4. Move concrete action items into the real task/calendar system.
5. Run a wiki lint pass periodically.
6. Remove duplicate, stale, or low-value temporary content.

## Useful Questions

- What themes have I repeated recently?
- Which action items from the last month are still unresolved?
- How has my understanding of system design changed?
- Which ideas have appeared multiple times and may be worth pursuing?
- Which people are mentioned often, and in what context?
