# FFmpeg Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AstrBot plugin that exposes safe FFmpeg/FFprobe media utilities through chat commands and LLM tools.

**Architecture:** Keep FFmpeg process logic in `core.py`, recent-media tracking in `media_context.py`, and AstrBot command/tool glue in `main.py`. Use subprocess exec without shell and whitelist operations instead of exposing raw FFmpeg arguments.

**Tech Stack:** Python 3.10+, AstrBot plugin API, FFmpeg/FFprobe command line tools, pytest.

---

### Task 1: Core Planning And Validation

**Files:**
- Create: `astrbot_plugin_ffmpeg/core.py`
- Create: `tests/test_core.py`

- [ ] Write failing tests for time parsing, format validation, and command planning.
- [ ] Run `python -m pytest tests/test_core.py -q` and verify tests fail because `astrbot_plugin_ffmpeg.core` does not exist.
- [ ] Implement dataclasses, config defaults, time parsing, output suffix mapping, and safe command planners.
- [ ] Run `python -m pytest tests/test_core.py -q` and verify tests pass.

### Task 2: Media Context

**Files:**
- Create: `astrbot_plugin_ffmpeg/media_context.py`
- Create: `tests/test_media_context.py`

- [ ] Write failing tests for per-session media retention, max item trimming, stable IDs, and selection by latest/index/id.
- [ ] Run `python -m pytest tests/test_media_context.py -q` and verify tests fail because `astrbot_plugin_ffmpeg.media_context` does not exist.
- [ ] Implement the media context manager.
- [ ] Run `python -m pytest tests/test_media_context.py -q` and verify tests pass.

### Task 3: AstrBot Plugin Glue

**Files:**
- Create: `main.py`
- Create: `astrbot_plugin_ffmpeg/__init__.py`
- Create: `tests/test_plugin_helpers.py`

- [ ] Write failing tests for output component classification and user argument parsing helpers.
- [ ] Run `python -m pytest tests/test_plugin_helpers.py -q` and verify tests fail because `main.py` does not exist.
- [ ] Implement AstrBot imports with test fallbacks, plugin registration, command handlers, LLM tools, and helper functions.
- [ ] Run `python -m pytest tests/test_plugin_helpers.py -q` and verify tests pass.

### Task 4: Plugin Metadata And Docs

**Files:**
- Create: `metadata.yaml`
- Create: `_conf_schema.json`
- Create: `README.md`
- Create: `pyproject.toml`

- [ ] Add AstrBot metadata, WebUI config schema, README usage examples, and pytest configuration.
- [ ] Run `python -m pytest -q` and verify all tests pass.
- [ ] Run `python -m compileall .` and verify all Python files compile.
