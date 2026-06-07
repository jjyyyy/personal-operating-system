# XHS Share Capture

Use this when you share something from Xiaohongshu and want it to enter the
existing `capture-xhs` parsing flow automatically.

## Channel

Save the shared XHS text into either the normal inbox root or the `xhs/`
subfolder as a text file whose name starts with:

```text
xhs-share-
```

Example:

```text
inbox/xhs-share-20260607-120000.txt
inbox/xhs/xhs-share-20260607-120000.txt
```

The file can contain the full copied Xiaohongshu share text. The watcher looks
for the first `xhslink.com` or `xiaohongshu.com` URL inside it.

## iPhone Shortcut Shape

Create a Share Sheet shortcut for text/URLs:

1. Receive text and URLs from Share Sheet.
2. Combine the shared input into text.
3. Format the current date as `yyyy-MM-dd-HHmmss`.
4. Save the text file to the synced inbox's `xhs/` subfolder with a name like:

```text
xhs-share-[Formatted Date].txt
```

Then `watch-inbox` or cron can process it through the same XHS importer used by:

```bash
python3 src/voice_notes_ai.py capture-xhs --url "http://xhslink.com/o/9T9AbRY5cG0"
```

## Behavior

- Text/image-style notes become `source: xhs` Markdown notes under `xhs/`.
- Public video posts use the video evidence pipeline when Xiaohongshu exposes a
  downloadable media URL.
- The original share text is archived with the source. For video posts, it is
  copied into the archived evidence bundle as `share.txt`.
- Protected videos still require manual export and `capture-xhs --video-file`.
