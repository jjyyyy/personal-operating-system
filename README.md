# Voice Notes AI Starter

A local workflow for turning voice notes into an Obsidian-friendly LLM wiki:

1. Export audio from a recording app, or provide an existing transcript.
2. Transcribe audio with OpenAI speech-to-text.
3. Generate structured summaries with OpenAI.
4. Write Obsidian-friendly Markdown into `daily/`.
5. Keep `catalog.md` and `log.md` current.
6. Create weekly reviews and promote durable content into `topics/`.

The streamlined capture path is:

```text
iPhone Action Button
-> Shortcut saves audio/text into inbox
-> watch-inbox processes it on the Mac
-> parsed Markdown appears in daily/
```

## Structure

```text
voice-notes project root
├── inbox/          # unprocessed audio/transcripts
├── processed/      # archived source files
├── discarded/      # cancelled inbox files
├── daily/          # individual voice notes
├── topics/         # long-term topic notes
├── reviews/        # weekly/monthly reviews
├── docs/           # setup notes, including Action Button flow
├── automation/     # optional launchd template
├── catalog.md      # generated broad content catalog
├── log.md          # append-only operation log
├── AGENTS.md       # AI assistant operating rules
└── templates/      # Markdown templates
```

## Setup

Requirements:

- Python 3.11+
- `OPENAI_API_KEY`
- Optional: `uv`

Copy the environment template:

```bash
cp .env.example .env
```

Fill `.env`:

```env
OPENAI_API_KEY=your_key_here
OPENAI_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
OPENAI_SUMMARY_MODEL=gpt-4.1-mini
VOICE_NOTES_INBOX=/Users/jazzzz/Projects/voice-notes/inbox
VOICE_NOTES_NOTIFICATIONS=1
```

## Shared Transcription Component

The reusable transcription boundary is:

```bash
python3 src/transcription_service.py transcribe-json /path/to/audio.m4a
```

It prints:

```json
{"text":"...","provider":"openai","model":"gpt-4o-mini-transcribe"}
```

Python projects can import `transcribe` from `src/transcription_service.py`.
Provider order is:

1. `VOICE_NOTES_LOCAL_TRANSCRIBE_COMMAND`, when configured;
2. the existing OpenAI transcription implementation using
   `OPENAI_TRANSCRIBE_MODEL`.

This component performs transcription only. Media ingestion projects remain
responsible for extracting audio before calling it.

## Usage

### 1. Process One Voice Note Or Transcript

Put an audio file into `inbox/`, then run:

```bash
python3 src/voice_notes_ai.py ingest inbox/your-note.m4a
```

If you already have a transcript, put a `.txt` or `.md` file into `inbox/`:

```bash
python3 src/voice_notes_ai.py ingest inbox/your-note.txt
```

By default, the note date is today. To set the original recording date:

```bash
python3 src/voice_notes_ai.py ingest inbox/your-note.m4a --date 2026-06-06
```

To process every supported file in `inbox/`:

```bash
python3 src/voice_notes_ai.py process-inbox
```

To watch the inbox and process synced files automatically:

```bash
python3 src/voice_notes_ai.py watch-inbox --interval 30 --settle-seconds 20
```

One-shot watcher test:

```bash
python3 src/voice_notes_ai.py watch-inbox --once --settle-seconds 20
```

With `uv`:

```bash
uv run python src/voice_notes_ai.py process-inbox
```

The script will:

- transcribe audio, or read `.txt` / `.md` transcripts directly
- generate structured note content
- add zero to three contextual AI comments only when a real knowledge gap,
  established concept, ambiguity, or verification need warrants one
- write Markdown into `daily/`
- update `index.json`
- update `catalog.md`
- append to `log.md`
- move the source file into `processed/`
- send a macOS notification after success or failure

Test notifications without calling OpenAI:

```bash
python3 src/voice_notes_ai.py test-notification
```

Set `VOICE_NOTES_NOTIFICATIONS=0` in `.env` to disable notifications.

AI comments use the Obsidian `ai-comment` callout style. Their font can be
adjusted in `.obsidian/snippets/ai-comments.css` through:

```css
--ai-comment-font-family
--ai-comment-font-size
```

### Action Button Capture

Use [docs/action-button-flow.md](docs/action-button-flow.md) to connect the iPhone Action Button to this workflow.

The short version:

1. iPhone Shortcut records audio.
2. Shortcut asks whether to save or discard.
3. Shortcut saves kept files into an iCloud Drive inbox.
4. `.env` sets `VOICE_NOTES_INBOX` to the synced Mac path.
5. `watch-inbox` or cron processes new files after they finish syncing.

Discard the newest unprocessed inbox file:

```bash
python3 src/voice_notes_ai.py discard-inbox --latest
```

For scheduled processing, install:

```bash
crontab automation/voice-notes.crontab
```

See `docs/action-button-flow.md` for the macOS Full Disk Access step required when cron reads an iCloud inbox.

### 2. Create A Weekly Review

```bash
python3 src/voice_notes_ai.py weekly-review
```

With an explicit date range:

```bash
python3 src/voice_notes_ai.py weekly-review --from 2026-06-01 --to 2026-06-07
```

### 3. Search The Vault

```bash
python3 src/voice_notes_ai.py search 网球
python3 src/voice_notes_ai.py search 手腕
```

### 4. Initialize Default Topics

```bash
python3 src/voice_notes_ai.py init-topics
```

### 5. Maintain The Wiki

Regenerate the broad content catalog:

```bash
python3 src/voice_notes_ai.py rebuild-catalog
```

Create a wiki health-check report:

```bash
python3 src/voice_notes_ai.py lint-wiki
```

## Obsidian Workflow

Open `/Users/jazzzz/Projects/voice-notes/` as an Obsidian vault.

Recommended flow:

- Drop new recordings into `inbox/`.
- Run `process-inbox`, `watch-inbox`, or `ingest`.
- Browse by date, topic, people, and action items.
- Run `weekly-review` once a week.
- Promote important content into `topics/`.

## LLM Wiki Files

- `index.md`: AI entry point.
- `00-home.md`: human-facing Obsidian home page.
- `01-methodology.md`: voice-notes LLM wiki method.
- `02-operating-system.md`: daily/weekly/monthly workflow.
- `AGENTS.md`: rules for AI assistants.
- `catalog.md`: generated broad content catalog. Read only when needed.
- `log.md`: chronological operation log.
- `docs/action-button-flow.md`: iPhone Action Button to parsed note setup.
- `prompts/`: reusable prompts for note processing and synthesis.

Start in Obsidian from `00-home.md`. Ask AI assistants to read `index.md` first, then `AGENTS.md`.

## Possible Upgrades

- Install the optional LaunchAgent from `automation/`.
- Suggest topic-note updates automatically.
- Add SQLite or vector search.
- Add a Telegram or iPhone Shortcut capture entry.
