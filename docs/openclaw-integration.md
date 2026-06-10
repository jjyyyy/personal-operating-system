# OpenClaw Integration

The project is connected to OpenClaw as an isolated agent:

```text
Agent ID: voice-notes
Workspace: /Users/jazzzz/Projects/voice-notes
Model: openai/gpt-5.5
Heartbeat: disabled
Channel bindings: none
```

This workspace is the `main` production worktree. OpenClaw and Telegram task
delivery must not point at `/Users/jazzzz/Projects/voice-notes-dev`; see
[deployment.md](deployment.md).

## Context

OpenClaw injects these workspace files at the beginning of a session:

- `AGENTS.md`
- `SOUL.md`
- `TOOLS.md`
- `IDENTITY.md`
- `USER.md`
- `HEARTBEAT.md`

`AGENTS.md` remains the operating source of truth. `index.md` is the vault entry point.

## Telegram Boundary

The OpenClaw main agent owns Telegram delivery. This vault should not add a
second Telegram bot or store Telegram credentials.

For Google Maps saves, `voice-notes` emits task files:

```bash
python3 src/voice_notes_ai.py google-maps-task xhs/your-note.md --city Barcelona
```

Tasks are written under `outbox/google-maps/` as private JSON. The main agent can
read a task, send each candidate to Telegram, and write any result back through a
separate bot/inbox file if needed.

## Use

Open the local Dashboard:

```text
http://127.0.0.1:18789/
```

Select the `voice-notes` agent before asking questions about this vault.

CLI:

```bash
openclaw agent --agent voice-notes --message "Read index.md and summarize the current vault."
```

## Security

The `voice-notes` agent has a per-agent exec policy:

```text
security: allowlist
ask: on-miss
strictInlineEval: true
```

It is intentionally not bound to Telegram, WhatsApp, or another external channel.
Use the OpenClaw main agent's existing Telegram binding for external delivery.

Calendar candidates that need confirmation are written under
`outbox/calendar-telegram/` as private JSON tasks. OpenClaw should send those
through Telegram and write the user's approve/skip/edit result back to the task
or a future result file. High-confidence resolved calendar candidates can be
created by `calendar-dispatch` without Telegram confirmation.

Heartbeat is disabled, so the agent does not make periodic model calls by itself.
