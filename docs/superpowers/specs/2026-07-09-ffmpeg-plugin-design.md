# AstrBot FFmpeg Plugin Design

## Goal

Build `astrbot_plugin_ffmpeg` as a lightweight AstrBot media utility plugin. Version 1 provides direct chat commands and LLM tools for common FFmpeg/FFprobe operations without adding a heavy task queue or web UI.

## Scope

The plugin supports two usage modes:

- Command mode: users reply to a media message and run commands such as `ffprobe`, `ffmpeg to mp3`, `ffmpeg cut 00:00:03 00:00:12`, `ffmpeg audio`, `ffmpeg cover`, and `ffmpeg gif`.
- LLM tool mode: the model can inspect the latest media in the current session, run approved operations, and return user-readable summaries or generated media.

The first version intentionally avoids arbitrary FFmpeg argument passthrough. It exposes safe presets only.

## Architecture

The plugin separates AstrBot integration from media logic:

- `main.py` owns AstrBot commands, LLM tools, message parsing, and response components.
- `core.py` owns operation planning, FFmpeg/FFprobe command construction, process execution, limits, and JSON-friendly result objects.
- `media_context.py` remembers recent media components per conversation so LLM tools can operate on the latest available media.

FFmpeg is invoked through `asyncio.create_subprocess_exec`. Inputs are converted to local paths through AstrBot message component methods when available. Outputs are written under AstrBot data temp directories or a local temporary directory fallback.

## Features

The command surface is:

- `ffprobe`: inspect replied or recently seen media.
- `ffmpeg to <format>`: convert to one of `mp3`, `wav`, `ogg`, `mp4`, `gif`, `jpg`, `png`.
- `ffmpeg cut <start> <end>`: trim audio or video.
- `ffmpeg audio`: extract audio from video as MP3.
- `ffmpeg cover [timestamp]`: extract a video frame as JPG.
- `ffmpeg gif [start] [end]`: convert a video segment to GIF.
- `ffmpeg help`: show concise usage.

The LLM tool surface mirrors the safe command surface:

- `ffmpeg_list_media`: list recent media in the current session.
- `ffmpeg_probe_media`: probe selected recent media.
- `ffmpeg_convert_media`: convert selected recent media with an approved operation.

## Safety

The plugin enforces:

- Allowed output formats and operations.
- Maximum input size.
- Maximum output size.
- Process timeout.
- Per-plugin async semaphore for concurrent jobs.
- No shell invocation and no raw user argument passthrough.

When a file exceeds limits, a process times out, FFmpeg fails, or the platform cannot send a generated media type, the plugin returns a clear plain-text error.

## Testing

Unit tests cover command construction, argument validation, time parsing, probe parsing, output component selection, and media context behavior. Integration with a real AstrBot runtime is kept thin and manually verifiable on `mini` without restarting the service by default.
