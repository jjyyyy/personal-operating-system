# Personal Operating System

A personal system for capturing thoughts, extracting actions, and building
durable knowledge into an Obsidian-friendly wiki:

1. Export audio from a recording app, or provide an existing transcript.
2. Transcribe audio with OpenAI speech-to-text.
3. Generate a structured daily note.
4. Create weekly snippets.
5. Promote repeated, durable material into `topics/`.

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
├── daily/          # personal voice notes and reflections
├── xhs/            # imported XHS knowledge
├── topics/         # long-term topic notes
├── snippets/       # weekly/monthly synthesis snippets
├── reviews/        # lint and maintenance reports
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
- write personal Markdown into `daily/` and XHS knowledge into `xhs/`
- update `index.json`
- update `catalog.md`
- append to `log.md`
- move the source into `processed/voice/`, `processed/xhs/`, or `processed/bot/`
- send a macOS notification after success or failure

Empty inbox checks return before any OpenAI call.

The project remains lightweight: no ingestion database, embeddings, or Calendar
outbox. XHS is supported by a small URL importer that writes an ordinary
`source: xhs` knowledge note.

### Import An XHS Note

Paste a copied XHS share link:

```bash
python3 src/voice_notes_ai.py capture-xhs \
  --url "https://www.xiaohongshu.com/explore/..."
```

For Share Sheet or Shortcut capture, save the shared text into the normal inbox
as `xhs-share-*.txt`. `process-inbox`, `watch-inbox`, or cron will route it
through the same XHS importer. See
[docs/xhs-share-capture.md](docs/xhs-share-capture.md).

Short `xhslink.com` links are followed automatically. If the public page is
hidden behind login or platform protection, provide the shared text explicitly:

```bash
python3 src/voice_notes_ai.py capture-xhs \
  --url "https://xhslink.com/..." \
  --text "The note text"
```

Use `--enqueue-only` to put the imported text into the normal inbox for cron.
XHS notes are stored in `xhs/`, marked `source: xhs`, and retain their original
URL and author when available.

Video posts use an evidence pipeline rather than fixed screenshots:

```text
video
-> scene-change frames plus start/end anchors
-> extracted audio and timestamped transcript
-> embedded subtitles
-> visual/OCR evidence for selected frames
-> evidence timeline
-> XHS knowledge note
```

The generated note distinguishes creator speech, visible evidence, OCR text,
and AI interpretation. Its reusable evidence bundle is archived under
`processed/xhs/xhs-video-*/content-package.json`.

When a public XHS page exposes its media URL, `capture-xhs` downloads and
processes it automatically. If login or platform protection hides the media,
export the video and use:

```bash
python3 src/voice_notes_ai.py capture-xhs \
  --url "https://xhslink.com/..." \
  --video-file "/path/to/exported-video.mp4"
```

Video ingestion requires FFmpeg. The project checks `VOICE_NOTES_FFMPEG_PATH`,
the system `PATH`, and the existing Xiaohongshu monitor's `ffmpeg-static`
installation. See `docs/xhs-video-ingestion.md` for the package contract and
quality rules.

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

Delete a generated note and its archived source:

```bash
python3 src/voice_notes_ai.py delete-note xhs/your-note.md --dry-run
python3 src/voice_notes_ai.py delete-note xhs/your-note.md
```

`delete-note` uses `index.json` to find the note's archived source, updates
`index.json`, rebuilds `catalog.md`, and appends to `log.md`. For video notes,
the archived `processed/xhs/xhs-video-*` evidence bundle is deleted too.

For scheduled processing, install:

```bash
crontab automation/voice-notes.crontab
```

The crontab runs snippet checks daily instead of relying on one exact weekly or
monthly moment. `scheduled-snippet weekly` targets the latest completed week and
skips if that snippet already exists; `scheduled-snippet monthly` does the same
for the latest completed month. This makes laptop sleep less likely to lose a
snippet run. See `docs/action-button-flow.md` for the macOS Full Disk Access
step required when cron reads an iCloud inbox.

### 2. Create A Weekly Snippet

```bash
python3 src/voice_notes_ai.py weekly-snippet
```

With an explicit date range:

```bash
python3 src/voice_notes_ai.py weekly-snippet --from 2026-06-01 --to 2026-06-07
```

Monthly and flexible period snippets:

```bash
python3 src/voice_notes_ai.py monthly-snippet
python3 src/voice_notes_ai.py review --preset yearly
python3 src/voice_notes_ai.py review --from 2026-01-01 --to 2026-03-31 \
  --label project-quarter --query "project name"
```

Snippets default to `--scope personal`; pass `--scope xhs` or `--scope all`
explicitly when imported knowledge should be included.

### 3. Search The Vault

```bash
python3 src/voice_notes_ai.py search 网球 --scope personal
python3 src/voice_notes_ai.py search 网球 --scope xhs
python3 src/voice_notes_ai.py search 网球 --scope all
```

- `personal`: personal voice/text daily notes only.
- `xhs`: imported XHS daily notes only.
- `all`: the entire vault, including topics, snippets, and reports.

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
- Run `weekly-snippet` once a week.
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
