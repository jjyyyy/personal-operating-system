# Deployment

## Worktrees

| Role | Path | Branch |
| --- | --- | --- |
| Production | `/Users/jazzzz/Projects/voice-notes` | `main` |
| Development | `/Users/jazzzz/Projects/voice-notes-dev` | `dev` |

Production integrations must use only the production path:

- cron: `automation/voice-notes.crontab`
- optional LaunchAgent: `automation/com.jazzzz.voice-notes.watch.plist.example`
- OpenClaw agent workspace: `/Users/jazzzz/Projects/voice-notes`
- Telegram delivery: OpenClaw main agent reads production `outbox/`
- Google Calendar OAuth: production `secrets/`

The development worktree intentionally has no production `.env`, OAuth
credentials, inbox, processed sources, notes, outbox tasks, or logs.

## Release Flow

1. Develop and test on `dev` or a short-lived branch based on `dev`.
2. Commit coherent milestones.
3. Merge the verified milestone into `main`.
4. Run relevant smoke checks from the production worktree.
5. Push `main` when publication is authorized.

Do not switch the production worktree away from `main`. Git worktrees make the
active production and development branches explicit and prevent both paths from
checking out the same branch simultaneously.
