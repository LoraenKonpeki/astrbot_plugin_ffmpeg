import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_plugin_imports_when_installed_under_short_directory_name(tmp_path: Path):
    plugins_dir = tmp_path / "data" / "plugins"
    plugin_dir = plugins_dir / "ffmpeg"
    plugin_dir.mkdir(parents=True)
    (tmp_path / "data" / "__init__.py").write_text("", encoding="utf-8")
    (plugins_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[1]
    shutil.copy(repo_root / "main.py", plugin_dir / "main.py")
    shutil.copytree(repo_root / "astrbot_plugin_ffmpeg", plugin_dir / "astrbot_plugin_ffmpeg")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import data.plugins.ffmpeg.main as m; print(m.AstrBotFfmpegPlugin.__name__)",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "AstrBotFfmpegPlugin"
