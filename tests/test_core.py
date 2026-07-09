from pathlib import Path

import pytest

from astrbot_plugin_ffmpeg.core import (
    FfmpegConfig,
    FfmpegPlanError,
    build_convert_plan,
    build_cover_plan,
    build_cut_plan,
    build_gif_plan,
    build_probe_plan,
    output_kind_for_format,
    parse_ffprobe_json,
    parse_time_to_seconds,
)


def test_parse_time_to_seconds_accepts_seconds_and_clock_values():
    assert parse_time_to_seconds("12") == pytest.approx(12)
    assert parse_time_to_seconds("01:02") == pytest.approx(62)
    assert parse_time_to_seconds("01:02:03.5") == pytest.approx(3723.5)


def test_parse_time_to_seconds_rejects_invalid_values():
    with pytest.raises(FfmpegPlanError, match="invalid time"):
        parse_time_to_seconds("1:2:3:4")

    with pytest.raises(FfmpegPlanError, match="non-negative"):
        parse_time_to_seconds("-1")


def test_output_kind_for_format_maps_all_ffmpeg_outputs_to_files():
    assert output_kind_for_format("mp3") == "file"
    assert output_kind_for_format("mp4") == "file"
    assert output_kind_for_format("gif") == "file"
    assert output_kind_for_format("jpg") == "file"
    assert output_kind_for_format("zip") == "file"


def test_build_probe_plan_uses_ffprobe_json_output(tmp_path: Path):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"fake")

    plan = build_probe_plan(source, FfmpegConfig(ffprobe_path="ffprobe-custom"))

    assert plan.kind == "probe"
    assert plan.args[:4] == ["ffprobe-custom", "-v", "error", "-print_format"]
    assert "-show_format" in plan.args
    assert "-show_streams" in plan.args
    assert plan.input_path == source
    assert plan.output_path is None


def test_build_convert_plan_whitelists_formats_and_builds_output(tmp_path: Path):
    source = tmp_path / "original song.wav"
    source.write_bytes(b"fake")

    plan = build_convert_plan(source, "mp3", tmp_path, FfmpegConfig(ffmpeg_path="ffmpeg-custom"))

    assert plan.kind == "convert"
    assert plan.output_format == "mp3"
    assert plan.output_kind == "file"
    assert plan.output_path is not None
    assert plan.output_path.suffix == ".mp3"
    assert plan.output_path.name == "original song.mp3"
    assert plan.output_path.parent.parent == tmp_path.resolve()
    assert plan.args[:3] == ["ffmpeg-custom", "-y", "-hide_banner"]
    assert plan.args[-1] == str(plan.output_path)


def test_build_convert_plan_rejects_disallowed_format(tmp_path: Path):
    source = tmp_path / "input.wav"
    source.write_bytes(b"fake")

    with pytest.raises(FfmpegPlanError, match="not allowed"):
        build_convert_plan(source, "exe", tmp_path, FfmpegConfig())


def test_build_cut_plan_requires_end_after_start(tmp_path: Path):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"fake")

    with pytest.raises(FfmpegPlanError, match="after start"):
        build_cut_plan(source, "10", "5", tmp_path, FfmpegConfig())


def test_build_cut_plan_outputs_mp4_by_default(tmp_path: Path):
    source = tmp_path / "meeting clip.mp4"
    source.write_bytes(b"fake")

    plan = build_cut_plan(source, "1", "3.5", tmp_path, FfmpegConfig())

    assert plan.kind == "cut"
    assert plan.output_format == "mp4"
    assert plan.output_kind == "file"
    assert "-ss" in plan.args
    assert "-to" in plan.args
    assert plan.output_path is not None
    assert plan.output_path.suffix == ".mp4"
    assert plan.output_path.name == "meeting clip.mp4"
    assert plan.output_path.parent.parent == tmp_path.resolve()


def test_build_cover_and_gif_plans_use_safe_presets(tmp_path: Path):
    source = tmp_path / "cat video.mp4"
    source.write_bytes(b"fake")

    cover = build_cover_plan(source, "2.5", tmp_path, FfmpegConfig())
    gif = build_gif_plan(source, "1", "4", tmp_path, FfmpegConfig(gif_width=320, gif_fps=12))

    assert cover.output_format == "jpg"
    assert cover.output_kind == "file"
    assert cover.output_path.name == "cat video.jpg"
    assert "-frames:v" in cover.args
    assert gif.output_format == "gif"
    assert gif.output_kind == "file"
    assert gif.output_path.name == "cat video.gif"
    assert "fps=12,scale=320:-1:flags=lanczos" in gif.args


def test_parse_ffprobe_json_returns_readable_summary():
    raw = b"""
    {
      "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "duration": "8.50"},
        {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"}
      ],
      "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "8.50", "size": "1234567", "bit_rate": "1161940"}
    }
    """

    info = parse_ffprobe_json(raw)

    assert info["format"] == "mov,mp4,m4a,3gp,3g2,mj2"
    assert info["duration"] == "8.50s"
    assert info["size"] == "1.18 MiB"
    assert "video: h264 1920x1080 8.50s" in info["streams"]
    assert "audio: aac 48000 Hz" in info["streams"]
