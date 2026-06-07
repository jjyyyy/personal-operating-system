# OpenClaw Integration

The project is connected to OpenClaw as an isolated agent:

```text
Agent ID: voice-notes
Workspace: /Users/jazzzz/Projects/voice-notes
Model: openai/gpt-5.5
Heartbeat: disabled
Channel bindings: none
```

## Context

OpenClaw injects these workspace files at the beginning of a session:

- `AGENTS.md`
- `SOUL.md`
- `TOOLS.md`
- `IDENTITY.md`
- `USER.md`
- `HEARTBEAT.md`

`AGENTS.md` remains the operating source of truth. `index.md` is the vault entry point.

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

It is intentionally not bound to Telegram, WhatsApp, or another external channel. Add a dedicated channel/account binding only when external chat access is explicitly desired.

Heartbeat is disabled, so the agent does not make periodic model calls by itself.
