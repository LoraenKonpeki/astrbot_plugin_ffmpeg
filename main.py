from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot_plugin_ffmpeg.core import (
    FfmpegConfig,
    FfmpegPlanError,
    build_audio_plan,
    build_convert_plan,
    build_cover_plan,
    build_cut_plan,
    build_gif_plan,
    build_probe_plan,
    parse_ffprobe_json,
    run_plan,
)
from astrbot_plugin_ffmpeg.media_context import MediaContextManager, MediaItem

try:
    from astrbot.api import logger
    from astrbot.api.event import AstrMessageEvent, filter
    from astrbot.api.message_components import File, Image, Record, Video
    from astrbot.api.star import Context, Star, register
    from astrbot.core.message.message_event_result import MessageChain
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
except ImportError:  # pragma: no cover - exercised indirectly by unit tests
    import logging

    logger = logging.getLogger(__name__)

    class _FallbackDecorator:
        def __call__(self, *args, **kwargs):
            def decorator(obj):
                return obj

            return decorator

    class _FallbackPlatformAdapterType:
        ALL = "ALL"

    class _FallbackFilter:
        command = _FallbackDecorator()
        llm_tool = _FallbackDecorator()
        platform_adapter_type = _FallbackDecorator()
        PlatformAdapterType = _FallbackPlatformAdapterType

    filter = _FallbackFilter()
    AstrMessageEvent = Any

    class Context:
        pass

    class Star:
        def __init__(self, context: Context):
            self.context = context

    def register(*args, **kwargs):
        def decorator(cls):
            return cls

        return decorator

    class _BaseFallbackComponent:
        def __init__(self, file: str = "", name: str = ""):
            self.file = file
            self.name = name

        @staticmethod
        def fromFileSystem(path):
            return _BaseFallbackComponent(str(path))

    class Image(_BaseFallbackComponent):
        @staticmethod
        def fromFileSystem(path):
            return Image(str(path))

    class Record(_BaseFallbackComponent):
        @staticmethod
        def fromFileSystem(path):
            return Record(str(path))

    class Video(_BaseFallbackComponent):
        @staticmethod
        def fromFileSystem(path):
            return Video(str(path))

    class File(_BaseFallbackComponent):
        def __init__(self, name: str, file: str = "", url: str = ""):
            super().__init__(file=file or url, name=name)
            self.url = url

    @dataclass
    class MessageChain:
        chain: list[Any]

    def get_astrbot_data_path() -> str:
        return tempfile.gettempdir()


@dataclass(frozen=True)
class PluginConfig:
    ffmpeg: FfmpegConfig
    max_concurrent_jobs: int = 1
    max_media_context_items: int = 20
    default_gif_seconds: float = 5.0
    llm_silent_mode: bool = False


@register(
    "ffmpeg",
    "Loraen_Konpeki",
    "安全的 FFmpeg/FFprobe 媒体转换、裁剪、探测工具，支持命令和 LLM tool",
    "0.1.0",
    "https://github.com/LoraenKonpeki/astrbot_plugin_ffmpeg",
)
class AstrBotFfmpegPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.plugin_config = _config_from_dict(config or {})
        self.media_context = MediaContextManager(self.plugin_config.max_media_context_items)
        self._semaphore = asyncio.Semaphore(self.plugin_config.max_concurrent_jobs)

    @filter.platform_adapter_type(filter.PlatformAdapterType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        self.media_context.capture_event_media(event)

    @filter.command("ffmpeg_help", alias={"ffmpeghelp"})
    async def ffmpeg_help(self, event: AstrMessageEvent):
        yield event.plain_result(_help_text())

    @filter.command("ffprobe")
    async def ffprobe_command(self, event: AstrMessageEvent):
        item = self._select_media(event)
        if not item:
            yield event.plain_result("没有找到可处理的媒体。请回复图片、语音、视频或文件后再使用 ffprobe。")
            return
        async for result in self._probe_event_media(event, item):
            yield result

    @filter.command("ffmpeg")
    async def ffmpeg_command(self, event: AstrMessageEvent):
        try:
            operation, args = _parse_ffmpeg_args(getattr(event, "message_str", ""))
        except ValueError as exc:
            yield event.plain_result(f"参数错误：{exc}\n\n{_help_text()}")
            return

        item = self._select_media(event)
        if not item:
            yield event.plain_result("没有找到可处理的媒体。请回复图片、语音、视频或文件后再使用 ffmpeg。")
            return

        async for result in self._convert_event_media(event, item, operation, args, send_result=False):
            yield result

    @filter.llm_tool(name="ffmpeg_list_media")
    async def ffmpeg_list_media_tool(self, event: AstrMessageEvent) -> str:
        """List recent media in this chat before probing or converting with FFmpeg.

        Returns:
            JSON array. Use media_id to select a specific item in other ffmpeg tools.
        """
        self.media_context.capture_event_media(event)
        return json.dumps({"success": True, "items": self.media_context.list_media(event)}, ensure_ascii=False)

    @filter.llm_tool(name="ffmpeg_probe_media")
    async def ffmpeg_probe_media_tool(self, event: AstrMessageEvent, media_id: str = "", index: int = -1) -> str:
        """Probe recent media with FFprobe and return format, duration, size and stream details.

        Args:
            media_id(string): Stable media id returned by ffmpeg_list_media. Preferred when available.
            index(number): 1-based media index, or -1 for latest. Used when media_id is empty.
        """
        self.media_context.capture_event_media(event)
        item = self._select_media(event, index=index, media_id=media_id)
        if not item:
            return json.dumps({"success": False, "error": "未找到可处理的媒体"}, ensure_ascii=False)
        try:
            info = await self._probe_media(item)
            return json.dumps({"success": True, "probe": info, "text": _format_probe_text(info)}, ensure_ascii=False)
        except Exception as exc:
            logger.exception("ffmpeg_probe_media failed")
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    @filter.llm_tool(name="ffmpeg_convert_media")
    async def ffmpeg_convert_media_tool(
        self,
        event: AstrMessageEvent,
        operation: str,
        media_id: str = "",
        index: int = -1,
        output_format: str = "",
        start: str = "",
        end: str = "",
        timestamp: str = "",
    ) -> str:
        """Convert recent media with a safe FFmpeg preset.

        Args:
            operation(string): One of to, cut, audio, cover, gif.
            media_id(string): Stable media id returned by ffmpeg_list_media. Preferred when available.
            index(number): 1-based media index, or -1 for latest. Used when media_id is empty.
            output_format(string): Required for operation=to. One of mp3, wav, ogg, mp4, gif, jpg, png.
            start(string): Start time for cut/gif, such as 0, 1.5, 00:01:02.
            end(string): End time for cut/gif.
            timestamp(string): Frame timestamp for cover.
        """
        self.media_context.capture_event_media(event)
        item = self._select_media(event, index=index, media_id=media_id)
        if not item:
            return json.dumps({"success": False, "error": "未找到可处理的媒体"}, ensure_ascii=False)

        try:
            args = _llm_args_for_operation(
                operation=operation,
                output_format=output_format,
                start=start,
                end=end,
                timestamp=timestamp,
                default_gif_seconds=self.plugin_config.default_gif_seconds,
            )
            message = None
            async for result in self._convert_event_media(event, item, operation, args, send_result=not self.plugin_config.llm_silent_mode):
                message = result
            return json.dumps(
                {
                    "success": True,
                    "operation": operation,
                    "message_sent": not self.plugin_config.llm_silent_mode,
                    "result": str(message) if message is not None else "ok",
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.exception("ffmpeg_convert_media failed")
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    def _select_media(self, event: AstrMessageEvent, index: int = -1, media_id: str = "") -> MediaItem | None:
        self.media_context.capture_event_media(event)
        return self.media_context.get_media(event, index=index, media_id=media_id or None)

    async def _probe_event_media(self, event: AstrMessageEvent, item: MediaItem):
        try:
            info = await self._probe_media(item)
            yield event.plain_result(_format_probe_text(info))
        except Exception as exc:
            logger.exception("ffprobe command failed")
            yield event.plain_result(f"ffprobe 失败：{exc}")

    async def _convert_event_media(self, event: AstrMessageEvent, item: MediaItem, operation: str, args: list[str], send_result: bool):
        try:
            plan = await self._build_plan_for_item(item, operation, args)
            async with self._semaphore:
                await run_plan(plan, self.plugin_config.ffmpeg)
            if not plan.output_path:
                yield event.plain_result("操作没有生成输出文件。")
                return
            component = _component_for_output(plan.output_path, plan.output_kind or "file")
            if send_result:
                await event.send(MessageChain(chain=[component]))
                yield event.plain_result(f"已完成 {operation}，结果已发送。")
            else:
                yield event.chain_result([component])
        except Exception as exc:
            logger.exception("ffmpeg command failed")
            yield event.plain_result(f"ffmpeg 失败：{exc}")

    async def _probe_media(self, item: MediaItem) -> dict[str, Any]:
        source = await _media_item_to_path(item)
        plan = build_probe_plan(source, self.plugin_config.ffmpeg)
        async with self._semaphore:
            result = await run_plan(plan, self.plugin_config.ffmpeg)
        return parse_ffprobe_json(result.stdout)

    async def _build_plan_for_item(self, item: MediaItem, operation: str, args: list[str]):
        source = await _media_item_to_path(item)
        output_dir = _output_dir()
        operation = operation.strip().lower()
        if operation == "to":
            if not args:
                raise FfmpegPlanError("to 需要目标格式，例如 ffmpeg to mp3")
            return build_convert_plan(source, args[0], output_dir, self.plugin_config.ffmpeg)
        if operation == "cut":
            if len(args) < 2:
                raise FfmpegPlanError("cut 需要开始和结束时间，例如 ffmpeg cut 1 3")
            return build_cut_plan(source, args[0], args[1], output_dir, self.plugin_config.ffmpeg)
        if operation == "audio":
            return build_audio_plan(source, output_dir, self.plugin_config.ffmpeg)
        if operation == "cover":
            timestamp = args[0] if args else "0"
            return build_cover_plan(source, timestamp, output_dir, self.plugin_config.ffmpeg)
        if operation == "gif":
            start = args[0] if len(args) >= 1 else "0"
            end = args[1] if len(args) >= 2 else str(self.plugin_config.default_gif_seconds)
            return build_gif_plan(source, start, end, output_dir, self.plugin_config.ffmpeg)
        raise FfmpegPlanError(f"unknown operation: {operation}")


def _config_from_dict(raw_config: Any) -> PluginConfig:
    config = _to_plain_dict(raw_config)
    gif_config = _to_plain_dict(config.get("gif", {}))
    allowed_formats = config.get("allowed_formats") or ["mp3", "wav", "ogg", "mp4", "gif", "jpg", "png"]
    ffmpeg = FfmpegConfig(
        ffmpeg_path=str(config.get("ffmpeg_path") or "ffmpeg"),
        ffprobe_path=str(config.get("ffprobe_path") or "ffprobe"),
        timeout_seconds=max(1, int(config.get("timeout_seconds", 120))),
        max_input_bytes=max(1, int(config.get("max_input_mb", 50))) * 1024 * 1024,
        max_output_bytes=max(1, int(config.get("max_output_mb", 50))) * 1024 * 1024,
        gif_width=max(64, int(gif_config.get("width", 480))),
        gif_fps=max(1, int(gif_config.get("fps", 10))),
        allowed_formats=frozenset(str(fmt).lower().lstrip(".") for fmt in allowed_formats),
    )
    return PluginConfig(
        ffmpeg=ffmpeg,
        max_concurrent_jobs=max(1, int(config.get("max_concurrent_jobs", 1))),
        max_media_context_items=max(1, int(config.get("max_media_context_items", 20))),
        default_gif_seconds=max(0.1, float(config.get("default_gif_seconds", 5))),
        llm_silent_mode=bool(config.get("llm_silent_mode", False)),
    )


def _parse_ffmpeg_args(message: str) -> tuple[str, list[str]]:
    parts = str(message or "").strip().split()
    if parts and parts[0].lower().lstrip("/") in {"ffmpeg", "～ffmpeg", "~ffmpeg"}:
        parts = parts[1:]
    if not parts:
        raise ValueError("缺少操作。可用：to/cut/audio/cover/gif")

    operation = parts[0].lower()
    args = parts[1:]
    if operation not in {"to", "cut", "audio", "cover", "gif"}:
        raise ValueError(f"unknown operation: {operation}")
    return operation, args


def _component_for_output(path: Path, output_kind: str):
    output_kind = (output_kind or "file").lower()
    if output_kind == "image":
        return Image.fromFileSystem(path)
    if output_kind == "record":
        return Record.fromFileSystem(path)
    if output_kind == "video":
        return Video.fromFileSystem(path)
    return File(name=Path(path).name, file=str(path))


def _format_probe_text(info: dict[str, Any]) -> str:
    streams = info.get("streams") or []
    lines = [
        "FFprobe 结果",
        f"格式: {info.get('format', 'unknown')}",
        f"时长: {info.get('duration', 'unknown')}",
        f"大小: {info.get('size', 'unknown')}",
        f"码率: {info.get('bit_rate', 'unknown')}",
    ]
    if streams:
        lines.append("流:")
        lines.extend(f"- {stream}" for stream in streams)
    return "\n".join(lines)


async def _media_item_to_path(item: MediaItem) -> Path:
    converter = getattr(item.component, "convert_to_file_path", None)
    if callable(converter):
        return Path(await converter()).resolve()

    source = item.source
    if source.startswith("file:///"):
        source = source[8:]
    return Path(source).expanduser().resolve()


def _llm_args_for_operation(
    operation: str,
    output_format: str,
    start: str,
    end: str,
    timestamp: str,
    default_gif_seconds: float,
) -> list[str]:
    op = (operation or "").strip().lower()
    if op == "to":
        return [output_format]
    if op == "cut":
        return [start, end]
    if op == "cover":
        return [timestamp or "0"]
    if op == "gif":
        return [start or "0", end or str(default_gif_seconds)]
    if op == "audio":
        return []
    raise FfmpegPlanError(f"unknown operation: {operation}")


def _output_dir() -> Path:
    return Path(get_astrbot_data_path()) / "temp" / "astrbot_plugin_ffmpeg"


def _to_plain_dict(config: Any) -> dict[str, Any]:
    if isinstance(config, dict):
        return dict(config)
    try:
        return dict(config.items())
    except Exception:
        return {}


def _help_text() -> str:
    return """FFmpeg 媒体工具

用法：回复图片、语音、视频或文件后发送：
ffprobe - 查看媒体信息
ffmpeg to mp3|wav|ogg|mp4|gif|jpg|png - 转换格式
ffmpeg cut <开始> <结束> - 裁剪片段
ffmpeg audio - 从视频提取 mp3 音频
ffmpeg cover [时间] - 截取封面
ffmpeg gif [开始] [结束] - 转 GIF

时间可写成 3、3.5、01:02 或 00:01:02。"""
