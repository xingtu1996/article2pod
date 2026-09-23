"""CLI 入口：article2pod <文章.md> [-o 输出目录] [-c 配置] [--no-tts] [--fast]"""
from __future__ import annotations

import argparse
import sys

from . import config as config_mod
from . import llm, pipeline


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="article2pod",
        description="文章→播客 零成本流水线：公众号长文 → 双人对话播客（mp3/m4a）",
    )
    ap.add_argument("article", help="输入文章 Markdown 路径")
    ap.add_argument("-o", "--out", default="demo/out", help="输出目录（默认 demo/out）")
    ap.add_argument("-c", "--config", default=None, help="配置文件路径（默认项目 config.yaml）")
    ap.add_argument("--no-tts", action="store_true", help="只生成对话稿，不合成音频（先审稿）")
    ap.add_argument("--use-script", action="store_true",
                    help="输出目录已有 script.json 时跳过 LLM，直接用它合成（人工改稿后的标准路径）")
    ap.add_argument("--fast", action="store_true", help="关闭 LLM 思考模式，加快生成（质量略降）")
    ap.add_argument("--host-voice", default=None, help="主持人音色 id（默认 config）")
    ap.add_argument("--author-voice", default=None, help="作者音色 id（默认 config）")
    ap.add_argument("--tone", default=None, choices=list(llm.TONE_TEXT.keys()),
                    help="语气：natural/lively/serious/cute/story（默认 natural）")
    args = ap.parse_args(argv)

    cfg = config_mod.load(args.config)
    if args.fast:
        cfg["llm"]["think"] = False

    try:
        stat = pipeline.run(args.article, args.out, cfg, no_tts=args.no_tts,
                            use_script=args.use_script, tone=args.tone,
                            host_voice=args.host_voice, author_voice=args.author_voice)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    print(f"\n✔ 完成：{stat['turns']} 轮对话"
          + (f"，音频 {stat['duration']}s" if stat.get("tts") else "（未合成音频）")
          + f"，耗时 {stat['seconds']}s，估算成本 ¥{stat['cost']}")
    if stat.get("files"):
        for f in stat["files"]:
            print(f"  产出 → {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
