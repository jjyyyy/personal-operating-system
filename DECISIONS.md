# Decisions

## 2026-06-10: Separate Production And Development Worktrees

Keep `/Users/jazzzz/Projects/voice-notes` checked out on `main`. Cron, OpenClaw,
Telegram task outboxes, OAuth credentials, and private vault data use this
production worktree.

Develop on the `dev` branch in `/Users/jazzzz/Projects/voice-notes-dev`. Merge
verified milestones into `main`; do not point production integrations at the
development worktree.

This avoids branch switches changing live automation while preserving one Git
history. Runtime data and secrets remain local to the production worktree.

## 2026-06-11: Retrospectively Merge Only The Daily-Note Layer

Process and archive every voice capture immediately. A later daily note may
fold into the previous voice note when one of three signals is high-confidence:
explicit continuation, unresolved reference to the earlier note, or completion
of the same specific event or train of thought. Elapsed time is not a merge
criterion.

Keep source archives and downstream route packages independent. The surviving
daily note records all source paths and labels transcript sections with capture
times. This avoids delaying ingestion or coupling calendar/project routing to
personal-note presentation.

Voice captures before 04:00 belong to the previous personal day by default.
`VOICE_NOTES_DAY_ROLLOVER_HOUR` can change the boundary, and explicit CLI dates
override it.
