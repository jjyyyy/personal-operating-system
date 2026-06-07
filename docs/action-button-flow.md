# Action Button To Parsed Notes

This is the streamlined capture path:

```text
iPhone Action Button
-> Shortcuts records audio or captures dictated text
-> Shortcut asks whether to save or discard
-> Shortcut saves file into a synced inbox
-> Mac watcher sees the file after it finishes syncing
-> voice_notes_ai.py transcribes/summarizes it
-> parsed note appears in daily/
-> source moves to processed/
-> catalog.md and log.md update
```

## Recommended Inbox

Use a folder that both iPhone Shortcuts and this Mac can see, usually an iCloud Drive folder.

Example:

```text
iCloud Drive/Voice Notes Inbox/
```

Then point the project at the synced folder by setting this in `.env`:

```env
VOICE_NOTES_INBOX=/Users/jazzzz/Library/Mobile Documents/com~apple~CloudDocs/Voice Notes Inbox
```

If you leave `VOICE_NOTES_INBOX` unset, the project uses:

```text
/Users/jazzzz/Projects/voice-notes/inbox
```

## iPhone Shortcut

Create a Shortcut named `Capture Voice Note`.

Steps:

1. `Record Audio`
   - Start Recording: Immediately
   - Finish Recording: On Tap
   - Audio Quality: Normal or High
2. `Format Date`
   - Date: Current Date
   - Format: Custom
   - Custom Format: `yyyy-MM-dd-HHmmss`
3. `Choose from Menu`
   - Prompt: `Save this voice note?`
   - Option: `Save`
   - Option: `Discard`
4. Under `Save`, add `Save File`
   - File: Recorded Audio
   - Destination Path: `Voice Notes Inbox/Voice Note - [Formatted Date]`
   - Ask Where to Save: Off
   - Overwrite If File Exists: Off
5. Under `Discard`, add `Stop This Shortcut`

Do not type `.m4a` in the Subpath. Shortcuts keeps the audio extension for the recorded file.

Then assign the iPhone Action Button to this Shortcut:

```text
Settings -> Action Button -> Shortcut -> Capture Voice Note
```

## Mac Processing

One-shot test:

```bash
python3 src/voice_notes_ai.py watch-inbox --once --settle-seconds 20
```

Continuous foreground watcher:

```bash
python3 src/voice_notes_ai.py watch-inbox --interval 30 --settle-seconds 20
```

The watcher waits until files are old enough before processing them. This avoids grabbing a file while iCloud is still syncing it.

## Cancelling Accidental Recordings

Best path: choose `Discard` in the Shortcut menu. The file is never saved, so cron or the watcher never sees it and no OpenAI API call happens.

Backup path if the file already synced but has not been processed yet:

```bash
python3 src/voice_notes_ai.py discard-inbox --latest
```

That moves the newest supported inbox file into `discarded/` and appends a log entry. To create a bigger cancellation window for cron, use a settle delay:

```cron
*/5 * * * * cd /Users/jazzzz/Projects/voice-notes && /usr/bin/python3 src/voice_notes_ai.py process-inbox --settle-seconds 120 >> logs/process-inbox-cron.log 2>&1
```

With this setup, you usually have at least a couple of minutes to discard an accidental recording before it is eligible for processing.

## Background Watcher

Use the LaunchAgent template in:

```text
automation/com.jazzzz.voice-notes.watch.plist.example
```

Install it manually when ready:

```bash
cp automation/com.jazzzz.voice-notes.watch.plist.example ~/Library/LaunchAgents/com.jazzzz.voice-notes.watch.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jazzzz.voice-notes.watch.plist
```

Stop it:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.jazzzz.voice-notes.watch.plist
```

## Cron

The project includes:

```text
automation/voice-notes.crontab
```

Install it with:

```bash
crontab automation/voice-notes.crontab
```

It checks every five minutes and exits immediately when no ready files exist. Empty checks do not call OpenAI.

### macOS iCloud Permission

macOS may block `/usr/sbin/cron` from reading iCloud Drive even though the same Python command works in Terminal. If `logs/process-inbox-cron.log` contains `Operation not permitted` for `Mobile Documents`, grant Full Disk Access:

1. Open `System Settings`.
2. Go to `Privacy & Security` -> `Full Disk Access`.
3. Click `+`.
4. Press `Command+Shift+G` and enter `/usr/sbin/cron`.
5. Add and enable `cron`.
6. If needed, also add `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3`.

Cron uses the explicit Python 3.14 path from the project crontab file.

## Notes

- The background watcher can call the OpenAI API whenever a new file appears, so enable it deliberately.
- If iCloud creates temporary files, the watcher ignores common incomplete suffixes such as `.icloud`, `.download`, `.part`, and `.tmp`.
- If iCloud exposes a dataless placeholder, ingest requests a download and waits up to `VOICE_NOTES_ICLOUD_TIMEOUT` seconds.
- For very long recordings, increase `--settle-seconds`.
