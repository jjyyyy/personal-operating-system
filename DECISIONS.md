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

## 2026-06-11: Merge Interrupted Voice Captures Before Ingest

Nearby voice recordings are candidates for one capture session, not automatic
matches. Explicit continuation language merges directly; ambiguous pairs require
a high-confidence semantic decision. Unrelated nearby recordings remain
separate.

The decision happens before note generation and routing. A merged note archives
all original recordings in one source bundle, preventing duplicate downstream
routes and corrections.
