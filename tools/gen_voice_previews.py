#!/usr/bin/env python3
"""预生成音色试听预览 mp3。

对 src/article2pod/tts.py 中 EDGE_VOICES 的每个中文音色，用 edge-tts
合成一段固定句（约 5 秒），落盘到项目根 voices_preview/{voice_id}.mp3，
供 GUI「音色试听」按钮直接播放（预生成而非实时合成，更稳、零网络延迟）。

用法：
    python3 tools/gen_voice_previews.py          # 已存在且非空的跳过
    python3 tools/gen_voice_previews.py --force  # 全部重新生成
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 项目根 = tools/ 的上一级；src/ 布局，把 src 加入 import 路径
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from article2pod.tts import EDGE_VOICES  # noqa: E402

# 固定试听句（约 5 秒）
PREVIEW_TEXT = "你好，我是这个音色的试听，我们开始今天的话题吧。"
OUT_DIR = ROOT / "voices_preview"


async def _gen_one(voice_id: str, out: Path) -> None:
    """用 edge-tts 合成单个音色预览。"""
    import edge_tts

    comm = edge_tts.Communicate(PREVIEW_TEXT, voice_id)
    await comm.save(str(out))


def main() -> int:
    ap = argparse.ArgumentParser(description="预生成音色试听预览 mp3")
    ap.add_argument("--force", action="store_true", help="忽略已存在文件，全部重新生成")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    made, skipped = 0, 0

    for v in EDGE_VOICES:
        vid = v["id"]
        out = OUT_DIR / f"{vid}.mp3"
        # 已存在且非空则跳过（除非 --force）
        if out.exists() and out.stat().st_size > 0 and not args.force:
            print(f"  跳过 {v['name']}（{vid}）：已存在 {out.stat().st_size} 字节")
            skipped += 1
            continue
        try:
            print(f"  生成 {v['name']}（{vid}）…")
            asyncio.run(_gen_one(vid, out))
            size = out.stat().st_size if out.exists() else 0
            if size == 0:
                print(f"  ⚠️ {v['name']} 输出为 0 字节，可能 edge-tts 未命中该音色")
            else:
                print(f"  ✓ {v['name']} → {out.name}（{size} 字节）")
                made += 1
        except Exception as e:  # 网络/限流/缺包都不中断整批
            print(f"  ✗ {v['name']} 失败：{e}")

    print(f"\n完成：新生成 {made} 个，跳过 {skipped} 个，输出目录 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
