# astrbot_plugin_ffmpeg

AstrBot 的安全 FFmpeg/FFprobe 媒体工具插件。它提供两种入口：

- 命令模式：用户回复媒体后手动转换、裁剪、探测。
- LLM tool 模式：让模型在安全白名单内帮用户探测或转换最近的媒体。

插件调用系统 `ffmpeg` 和 `ffprobe`，不会暴露任意 FFmpeg 参数给用户或模型。

## 功能

- `ffprobe`：查看格式、时长、大小、码率、音视频流。
- `ffmpeg to mp3|wav|ogg|mp4|gif|jpg|png`：转换格式。
- `ffmpeg cut <开始> <结束>`：裁剪音视频片段。
- `ffmpeg audio`：从视频提取 MP3 音频。
- `ffmpeg cover [时间]`：截取视频封面。
- `ffmpeg gif [开始] [结束]`：转 GIF。
- LLM tools：`ffmpeg_list_media`、`ffmpeg_probe_media`、`ffmpeg_convert_media`。

## 示例

回复一个视频后发送：

```text
ffprobe
ffmpeg audio
ffmpeg cover 2.5
ffmpeg cut 00:00:03 00:00:12
ffmpeg gif 0 5
ffmpeg to mp4
```

时间支持 `3`、`3.5`、`01:02`、`00:01:02`。

## 安全边界

- 只允许配置里的输出格式。
- 不支持任意参数透传。
- 使用 `asyncio.create_subprocess_exec`，不经过 shell。
- 限制输入大小、输出大小、超时和并发数。
- 命令和 LLM tool 共用同一套安全规划逻辑。

## 运行要求

AstrBot 运行环境需要能找到 `ffmpeg` 和 `ffprobe`。在 `mini` 的 AstrBot Pod 中已确认存在：

```text
/usr/bin/ffmpeg
/usr/bin/ffprobe
```

如运行环境不同，可在 AstrBot WebUI 配置 `ffmpeg_path` 和 `ffprobe_path`。

## 开发验证

```bash
python3 -m pytest -q
python3 -m compileall .
```

