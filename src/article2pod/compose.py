"""FFmpeg 合成：按顺序拼接各句配音，句间插入静音（呼吸感），输出 mp3 / m4a。

比 book2vido 简单得多：没有画面轨，只有纯音频 concat。
句间静音用 filter_complex 的 apad 实现——比 concat demuxer + 单独 silence 文件稳
（不依赖各句编码参数一致，不会出时间戳/采样率错乱）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def compose(voice_files: list[str], out_mp3: str, gap_ms: int = 350) -> float:
    """拼接语音片段 → 单 mp3。返回总时长（秒）。voice_files 顺序 = 对话顺序。"""
    if not voice_files:
        raise ValueError("没有可合成的语音片段")
    pad = gap_ms / 1000.0
    n = len(voice_files)

    # filter：每路输入先 apad 补尾静音，再 concat
    inputs: list[str] = []
    filters: list[str] = []
    for i in range(n):
        inputs += ["-i", voice_files[i]]
        filters.append(f"[{i}:a]apad=pad_dur={pad}[a{i}]")
    filters.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]")

    cmd = (["ffmpeg", "-nostdin", "-y"]
           + inputs
           + ["-filter_complex", ";".join(filters), "-map", "[out]",
              "-c:a", "libmp3lame", "-q:a", "4", out_mp3])
    subprocess.run(cmd, check=True, capture_output=True)

    out = Path(out_mp3)
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"合成失败：{out_mp3} 不存在或为空")

    # 回读时长（ffprobe，与生成路径不同的验证手段）
    probe = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", out_mp3]
    )
    import json
    return float(json.loads(probe)["format"]["duration"])


def to_m4a(in_mp3: str, out_m4a: str) -> None:
    """mp3 → m4a（AAC），公众号图文内嵌音频推荐格式。"""
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-i", in_mp3, "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", out_m4a],
        check=True, capture_output=True,
    )
    if not Path(out_m4a).exists() or Path(out_m4a).stat().st_size == 0:
        raise RuntimeError(f"m4a 转换失败：{out_m4a} 不存在或为空")
