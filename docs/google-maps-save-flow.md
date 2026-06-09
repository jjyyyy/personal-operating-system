# Google Maps Save Flow

Use this for Xiaohongshu food/travel notes that mention places worth saving in
Google Maps.

## Flow

1. Import the XHS note into `xhs/`.
2. Generate an OpenClaw task:

```bash
python3 src/voice_notes_ai.py google-maps-task xhs/your-note.md --city Barcelona
```

This writes private JSON under `outbox/google-maps/` for the OpenClaw main
agent to send through Telegram.

For Markdown fallback, generate a manual save queue:

```bash
python3 src/voice_notes_ai.py google-maps-save-queue xhs/your-note.md --city Barcelona
```

3. Open each Google Maps link from Telegram or the generated `maps/*.md` file.
4. Verify the place manually.
5. Save it to the suggested Google Maps list and optional tag.
6. Mark the entry as saved in the queue file if useful.

## Current Lists

- Brunch
- Bakery
- 吃-Travel
- coffee
- Shops
- 旅行
- Gelato
- Travel plans
- 喝

## Safety Boundary

This flow does not log into Google, call the Google Maps API, or automate saving
places. `voice-notes` only creates search links and list suggestions. OpenClaw
owns Telegram delivery.
