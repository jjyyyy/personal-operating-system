# XHS Video Ingestion

## Boundary

The implementation has three small layers:

1. `xhs_import.py` validates the XHS URL, reads public metadata, detects a media
   URL, and downloads the source video when available.
2. `video_ingestion.py` accepts any local video and builds a portable evidence
   package. It has no knowledge of Obsidian, indexes, cron, or XHS login state.
3. `voice_notes_ai.py` turns the evidence timeline into the existing `source:
   xhs` Markdown note and archives the package.

This keeps media understanding reusable without introducing a generalized
ingestion platform.

## Evidence Package

`content-package.json` uses schema `voice-notes.video-content.v1` and contains:

- source metadata and duration;
- relative paths to video, audio, subtitles, and selected frames;
- timestamped transcript segments;
- frame timestamps;
- visible frame content;
- OCR/visible text;
- explicitly labeled AI interpretation;
- provider/model/error metadata for graceful degradation.

All paths inside the package are relative, so the archived directory can move
without invalidating the record.

## Frame Policy

Frames are selected from scene changes, with beginning and ending anchors.
Selection is capped and spread across the full timeline. If scene detection
produces too little evidence, adaptive uniform sampling is used as a fallback.

This means a simple talking-head clip may use only a few frames, while a dense
tutorial can use more. It does not blindly take ten screenshots.

Configuration:

```env
VOICE_NOTES_VIDEO_SCENE_THRESHOLD=0.28
VOICE_NOTES_VIDEO_MAX_FRAMES=16
VOICE_NOTES_MAX_VIDEO_BYTES=500000000
```

## Quality Gate

A video note is not generated unless extraction produces at least one of:

- timestamped spoken content; or
- analyzed visual events.

Title and post caption alone are insufficient. Failed temporary bundles are
removed so cron cannot mistake partial work for a completed capture.

## Acquisition Fallback

Public XHS video URLs are downloaded automatically. Login-protected media is an
edge concern and should not couple this vault to another project's cookies or
browser profile. Export the video locally and pass `--video-file` instead.
