from pathlib import Path
import asyncio

import pytest
import main as plugin_main

from main import (
    PluginConfig,
    _component_for_output,
    _config_from_dict,
    _format_probe_text,
    _media_item_to_path,
    _parse_ffmpeg_args,
)
from astrbot_plugin_ffmpeg.media_context import MediaItem


def test_config_from_dict_normalizes_limits_and_paths():
    config = _config_from_dict(
        {
            "ffmpeg_path": "/usr/bin/ffmpeg",
            "ffprobe_path": "/usr/bin/ffprobe",
            "timeout_seconds": 1,
            "max_input_mb": 2,
            "max_output_mb": 3,
            "max_concurrent_jobs": 0,
            "gif": {"width": 240, "fps": 8},
            "allowed_formats": ["mp3", "mp4"],
            "file_base_url": "http://astrbot:6185",
            "file_token_timeout_seconds": 600,
        }
    )

    assert isinstance(config, PluginConfig)
    assert config.ffmpeg.ffmpeg_path == "/usr/bin/ffmpeg"
    assert config.ffmpeg.timeout_seconds == 1
    assert config.ffmpeg.max_input_bytes == 2 * 1024 * 1024
    assert config.ffmpeg.max_output_bytes == 3 * 1024 * 1024
    assert config.max_concurrent_jobs == 1
    assert config.ffmpeg.gif_width == 240
    assert config.ffmpeg.gif_fps == 8
    assert config.file_base_url == "http://astrbot:6185"
    assert config.file_token_timeout_seconds == 600


def test_parse_ffmpeg_args_supports_safe_operations():
    assert _parse_ffmpeg_args("ffmpeg to mp3") == ("to", ["mp3"])
    assert _parse_ffmpeg_args("ffmpeg cut 00:00:01 00:00:03") == ("cut", ["00:00:01", "00:00:03"])
    assert _parse_ffmpeg_args("ffmpeg audio") == ("audio", [])
    assert _parse_ffmpeg_args("ffmpeg cover 2.5") == ("cover", ["2.5"])
    assert _parse_ffmpeg_args("ffmpeg gif 1 3") == ("gif", ["1", "3"])


def test_parse_ffmpeg_args_rejects_unknown_operation():
    with pytest.raises(ValueError, match="unknown operation"):
        _parse_ffmpeg_args("ffmpeg -i a b")


def test_component_for_output_always_uploads_generated_media_as_file(tmp_path: Path):
    image_path = tmp_path / "out.gif"
    record_path = tmp_path / "out.mp3"
    video_path = tmp_path / "out.mp4"
    file_path = tmp_path / "out.bin"
    for path in (image_path, record_path, video_path, file_path):
        path.write_bytes(b"x")

    for path, output_kind in (
        (image_path, "image"),
        (record_path, "record"),
        (video_path, "video"),
        (file_path, "file"),
    ):
        component = asyncio.run(_component_for_output(path, output_kind))
        assert component.__class__.__name__ == "File"
        assert component.name == path.name


def test_component_for_output_uses_file_service_url_when_configured(tmp_path: Path, monkeypatch):
    output_path = tmp_path / "out.mp3"
    output_path.write_bytes(b"x")

    class FakeFileTokenService:
        async def register_file(self, file_path: str, timeout=None):
            assert file_path == str(output_path)
            assert timeout == 900
            return "token-123"

    monkeypatch.setattr(plugin_main, "file_token_service", FakeFileTokenService())

    component = asyncio.run(
        _component_for_output(
            output_path,
            "file",
            file_base_url="http://astrbot:6185/",
            file_token_timeout_seconds=900,
        )
    )

    assert component.__class__.__name__ == "File"
    assert component.name == "out.mp3"
    assert component.url == "http://astrbot:6185/api/file/token-123"
    assert component.file == "http://astrbot:6185/api/file/token-123"


def test_format_probe_text_includes_summary_fields():
    text = _format_probe_text(
        {
            "format": "mp4",
            "duration": "8.50s",
            "size": "1.18 MiB",
            "bit_rate": "1162 kbps",
            "streams": ["video: h264 1920x1080 8.50s", "audio: aac 48000 Hz"],
        }
    )

    assert "格式: mp4" in text
    assert "时长: 8.50s" in text
    assert "video: h264" in text


def test_media_item_to_path_uses_async_get_file_for_file_components(tmp_path: Path):
    downloaded = tmp_path / "downloaded.mp3"
    downloaded.write_bytes(b"fake")

    class FakeFileComponent:
        async def get_file(self):
            return str(downloaded)

        @property
        def file(self):
            raise AssertionError("File.file must not be accessed in async context")

    item = MediaItem(
        media_id="m1",
        session_id="s1",
        component=FakeFileComponent(),
        component_type="File",
        source="https://example.test/a.mp3",
        message_id="msg",
        sender_id="u",
        created_at=0,
    )

    assert asyncio.run(_media_item_to_path(item)) == downloaded.resolve()
