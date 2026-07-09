from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class FfmpegPlanError(ValueError):
    """Raised when a requested FFmpeg operation is not allowed or invalid."""


@dataclass(frozen=True)
class FfmpegConfig:
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    timeout_seconds: int = 120
    max_input_bytes: int = 50 * 1024 * 1024
    max_output_bytes: int = 50 * 1024 * 1024
    gif_width: int = 480
    gif_fps: int = 10
    allowed_formats: frozenset[str] = field(
        default_factory=lambda: frozenset({"mp3", "wav", "ogg", "mp4", "gif", "jpg", "jpeg", "png"})
    )


@dataclass(frozen=True)
class FfmpegPlan:
    kind: str
    args: list[str]
    input_path: Path
    output_path: Path | None = None
    output_format: str | None = None
    output_kind: str | None = None


@dataclass(frozen=True)
class FfmpegRunResult:
    plan: FfmpegPlan
    stdout: bytes
    stderr: bytes


def parse_time_to_seconds(value: str | int | float) -> float:
    text = str(value).strip()
    if not text:
        raise FfmpegPlanError("invalid time: empty value")

    if text.startswith("-"):
        raise FfmpegPlanError("time must be non-negative")

    parts = text.split(":")
    if len(parts) > 3:
        raise FfmpegPlanError(f"invalid time: {value}")

    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise FfmpegPlanError(f"invalid time: {value}") from exc

    if any(number < 0 for number in numbers):
        raise FfmpegPlanError("time must be non-negative")

    total = 0.0
    for number in numbers:
        total = total * 60 + number
    return total


def output_kind_for_format(fmt: str) -> str:
    normalized = _normalize_format(fmt)
    if normalized in {"mp3", "wav", "ogg"}:
        return "record"
    if normalized in {"mp4"}:
        return "video"
    if normalized in {"gif", "jpg", "jpeg", "png"}:
        return "image"
    return "file"


def build_probe_plan(input_path: str | Path, config: FfmpegConfig) -> FfmpegPlan:
    source = _validate_input_path(input_path, config)
    args = [
        config.ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source),
    ]
    return FfmpegPlan(kind="probe", args=args, input_path=source)


def build_convert_plan(
    input_path: str | Path,
    output_format: str,
    output_dir: str | Path,
    config: FfmpegConfig,
) -> FfmpegPlan:
    source = _validate_input_path(input_path, config)
    fmt = _validate_format(output_format, config)
    target = _make_output_path(output_dir, fmt)
    args = [config.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source)]

    if fmt in {"mp3", "wav", "ogg"}:
        args.extend(["-vn"])
    elif fmt == "mp4":
        args.extend(["-movflags", "+faststart"])
    elif fmt in {"jpg", "jpeg", "png"}:
        args.extend(["-frames:v", "1"])

    args.append(str(target))
    return FfmpegPlan(
        kind="convert",
        args=args,
        input_path=source,
        output_path=target,
        output_format=fmt,
        output_kind=output_kind_for_format(fmt),
    )


def build_cut_plan(
    input_path: str | Path,
    start: str | int | float,
    end: str | int | float,
    output_dir: str | Path,
    config: FfmpegConfig,
) -> FfmpegPlan:
    source = _validate_input_path(input_path, config)
    start_seconds = parse_time_to_seconds(start)
    end_seconds = parse_time_to_seconds(end)
    if end_seconds <= start_seconds:
        raise FfmpegPlanError("end time must be after start time")

    fmt = _infer_output_format(source)
    if fmt not in config.allowed_formats:
        fmt = "mp4"
    target = _make_output_path(output_dir, fmt)
    args = [
        config.ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        _format_seconds(start_seconds),
        "-to",
        _format_seconds(end_seconds),
        "-i",
        str(source),
        "-c",
        "copy",
        str(target),
    ]
    return FfmpegPlan(
        kind="cut",
        args=args,
        input_path=source,
        output_path=target,
        output_format=fmt,
        output_kind=output_kind_for_format(fmt),
    )


def build_audio_plan(input_path: str | Path, output_dir: str | Path, config: FfmpegConfig) -> FfmpegPlan:
    source = _validate_input_path(input_path, config)
    target = _make_output_path(output_dir, "mp3")
    args = [
        config.ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-codec:a",
        "libmp3lame",
        str(target),
    ]
    return FfmpegPlan(
        kind="audio",
        args=args,
        input_path=source,
        output_path=target,
        output_format="mp3",
        output_kind="record",
    )


def build_cover_plan(
    input_path: str | Path,
    timestamp: str | int | float,
    output_dir: str | Path,
    config: FfmpegConfig,
) -> FfmpegPlan:
    source = _validate_input_path(input_path, config)
    seconds = parse_time_to_seconds(timestamp)
    target = _make_output_path(output_dir, "jpg")
    args = [
        config.ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        _format_seconds(seconds),
        "-i",
        str(source),
        "-frames:v",
        "1",
        str(target),
    ]
    return FfmpegPlan(
        kind="cover",
        args=args,
        input_path=source,
        output_path=target,
        output_format="jpg",
        output_kind="image",
    )


def build_gif_plan(
    input_path: str | Path,
    start: str | int | float,
    end: str | int | float,
    output_dir: str | Path,
    config: FfmpegConfig,
) -> FfmpegPlan:
    source = _validate_input_path(input_path, config)
    start_seconds = parse_time_to_seconds(start)
    end_seconds = parse_time_to_seconds(end)
    if end_seconds <= start_seconds:
        raise FfmpegPlanError("end time must be after start time")

    target = _make_output_path(output_dir, "gif")
    video_filter = f"fps={config.gif_fps},scale={config.gif_width}:-1:flags=lanczos"
    args = [
        config.ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        _format_seconds(start_seconds),
        "-to",
        _format_seconds(end_seconds),
        "-i",
        str(source),
        "-vf",
        video_filter,
        str(target),
    ]
    return FfmpegPlan(
        kind="gif",
        args=args,
        input_path=source,
        output_path=target,
        output_format="gif",
        output_kind="image",
    )


async def run_plan(plan: FfmpegPlan, config: FfmpegConfig) -> FfmpegRunResult:
    process = await asyncio.create_subprocess_exec(
        *plan.args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=config.timeout_seconds)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise FfmpegPlanError(f"{plan.kind} timed out after {config.timeout_seconds}s") from exc

    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip() or f"{plan.kind} failed"
        raise FfmpegPlanError(message)

    if plan.output_path and plan.output_path.exists() and plan.output_path.stat().st_size > config.max_output_bytes:
        raise FfmpegPlanError("output file exceeds configured size limit")

    return FfmpegRunResult(plan=plan, stdout=stdout, stderr=stderr)


def parse_ffprobe_json(raw: bytes | str) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FfmpegPlanError("ffprobe returned invalid JSON") from exc

    format_info = data.get("format") or {}
    streams = data.get("streams") or []
    return {
        "format": str(format_info.get("format_name") or "unknown"),
        "duration": _format_duration(format_info.get("duration")),
        "size": _format_bytes(format_info.get("size")),
        "bit_rate": _format_bit_rate(format_info.get("bit_rate")),
        "streams": [_format_stream(stream) for stream in streams],
        "raw": data,
    }


def _validate_input_path(input_path: str | Path, config: FfmpegConfig) -> Path:
    source = Path(input_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FfmpegPlanError(f"input file does not exist: {source}")
    if source.stat().st_size > config.max_input_bytes:
        raise FfmpegPlanError("input file exceeds configured size limit")
    return source


def _validate_format(fmt: str, config: FfmpegConfig) -> str:
    normalized = _normalize_format(fmt)
    if normalized not in config.allowed_formats:
        raise FfmpegPlanError(f"output format is not allowed: {normalized}")
    if normalized == "jpeg":
        return "jpg"
    return normalized


def _normalize_format(fmt: str) -> str:
    return str(fmt).strip().lower().lstrip(".")


def _infer_output_format(source: Path) -> str:
    suffix = source.suffix.lower().lstrip(".")
    if suffix == "jpeg":
        return "jpg"
    return suffix or "mp4"


def _make_output_path(output_dir: str | Path, fmt: str) -> Path:
    target_dir = Path(output_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"astrbot_ffmpeg_{uuid.uuid4().hex}.{fmt}"


def _format_seconds(seconds: float) -> str:
    if seconds.is_integer():
        return str(int(seconds))
    return f"{seconds:.3f}".rstrip("0").rstrip(".")


def _format_duration(value: Any) -> str:
    try:
        return f"{float(value):.2f}s"
    except (TypeError, ValueError):
        return "unknown"


def _format_bytes(value: Any) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "unknown"
    units = ["B", "KiB", "MiB", "GiB"]
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} B"
    return f"{size:.2f} {unit}"


def _format_bit_rate(value: Any) -> str:
    try:
        return f"{int(value) / 1000:.0f} kbps"
    except (TypeError, ValueError):
        return "unknown"


def _format_stream(stream: dict[str, Any]) -> str:
    kind = stream.get("codec_type") or "stream"
    codec = stream.get("codec_name") or "unknown"
    if kind == "video":
        width = stream.get("width")
        height = stream.get("height")
        duration = _format_duration(stream.get("duration"))
        size = f" {width}x{height}" if width and height else ""
        return f"video: {codec}{size} {duration}"
    if kind == "audio":
        sample_rate = stream.get("sample_rate")
        suffix = f" {sample_rate} Hz" if sample_rate else ""
        return f"audio: {codec}{suffix}"
    return f"{kind}: {codec}"
