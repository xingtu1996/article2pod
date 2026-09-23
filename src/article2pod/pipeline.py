"""编排：文章 → 对话稿 → 双音色配音 → 合成 mp3/m4a。

只做编排 + 进度打印，不实现任何环节（各环节的活在自己的模块里）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import compose, config as config_mod, llm, tts


def _strip_frontmatter(md: str) -> str:
    """公众号稿件偶有 YAML frontmatter（--- ... ---），正文前剥掉。"""
    if md.startswith("---"):
        m = re.match(r"^---\s*\n.*?\n---\s*\n", md, re.DOTALL)
        if m:
            return md[m.end():]
    return md


def read_article(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文章不存在：{p}")
    md = p.read_text(encoding="utf-8")
    md = _strip_frontmatter(md)
    # 去掉 markdown 标记但保留正文结构（对话稿只需要文字；标题符号去掉更干净）
    md = re.sub(r"^#{1,6}\s*", "", md, flags=re.MULTILINE)
    md = re.sub(r"!\[.*?\]\(.*?\)", "", md)          # 图片
    md = re.sub(r"\[.*?\]\(.*?\)", lambda m: m.group(0).split("](")[0].lstrip("["), md)  # 链接→文字
    md = re.sub(r"[*_>`~]", "", md)
    return md.strip()


def build_script_md(turns: list[dict]) -> str:
    """对话稿的可读版（Markdown），供人工审稿/发布说明使用。"""
    label = {"host": "主持人", "author": "行途（作者）"}
    lines = [f"**{label[t['role']]}**：{t['text']}\n" for t in turns]
    return "\n".join(lines)


def run(article_path: str, out_dir: str, cfg: dict, no_tts: bool = False,
        use_script: bool = False, tone: str | None = None,
        host_voice: str | None = None, author_voice: str | None = None) -> dict:
    """主流程。tone 注入对话稿语气；host_voice/author_voice 覆盖 TTS 音色（GUI 传参）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. 取料
    article = read_article(article_path)
    max_chars = cfg["limits"]["max_chars"]
    if len(article) > max_chars:
        print(f"[in] 正文 {len(article)} 字 > 上限 {max_chars}，截取开头 {max_chars} 字")
        article = article[:max_chars]
    else:
        print(f"[in] 正文 {len(article)} 字")

    # 2. 对话稿（最贵，~1-2 分钟）。--use-script 且已有 script.json → 跳过 LLM，
    #    直接用人（或上次）改好的稿——落盘 = 人工可改的口子（book2vido 同款设计）。
    script_json = out_dir / "script.json"
    script_md = out_dir / "script.md"
    if use_script and script_json.exists():
        turns = llm.validate(json.loads(script_json.read_text(encoding="utf-8")))
        print(f"[script] 使用现有 {script_json.name}（{len(turns)} 轮，跳过 LLM）")
    else:
        turns = llm.generate(cfg, article, tone=tone)
        script_json.write_text(json.dumps(turns, ensure_ascii=False, indent=2), encoding="utf-8")
        n_h = sum(1 for t in turns if t["role"] == "host")
        print(f"[script] 对话稿 {len(turns)} 轮（host {n_h} / author {len(turns) - n_h}）")
    script_md.write_text(build_script_md(turns), encoding="utf-8")
    print(f"[script] 已落盘 {script_json.name} / {script_md.name}"
          f"（人工可改，改完用 --use-script 重合成，跳过 LLM）")
    n_turns = len(turns)

    if no_tts:
        return {"turns": n_turns, "script": str(script_md), "seconds": round(time.time() - t0, 1),
                "cost": 0.0, "tts": False}

    # 3. 双音色配音
    tts_cfg = cfg["tts"]
    provider = tts.build(cfg, host_voice=host_voice, author_voice=author_voice)
    hv = host_voice or tts_cfg.get("host_voice", "")
    av = author_voice or tts_cfg.get("author_voice", "")
    print(f"[tts] {tts_cfg['provider']} 双音色（host={hv}, author={av}）"
          f"并发 {cfg['concurrency']['tts_workers']} 线程…"
          + (f"，语气={tone}" if tone else ""))
    work = out_dir / ".voice"
    work.mkdir(exist_ok=True)
    items = [(i, t["role"], t["text"], str(work / f"v{i:03d}.mp3")) for i, t in enumerate(turns)]
    try:
        durs = provider.speak_many(items, max_workers=cfg["concurrency"]["tts_workers"])
    except Exception as e:
        print(f"[warn] edge-tts 失败（{e}）——回退 macOS say 本地兜底")
        provider = tts.SayProvider()
        durs = provider.speak_many(items, max_workers=4)

    # 4. 合成
    voices = [str(work / f"v{i:03d}.mp3") for i in range(n_turns)]
    out_mp3 = out_dir / "podcast.mp3"
    total = compose.compose(voices, str(out_mp3), cfg["out"].get("gap_ms", 350))
    print(f"[out] 合成完成：{out_mp3.name}，{total:.1f}s 音频")

    produced = [str(out_mp3)]
    fmt = cfg["out"].get("formats", "both")
    if fmt in ("m4a", "both"):
        out_m4a = out_dir / "podcast.m4a"
        compose.to_m4a(str(out_mp3), str(out_m4a))
        produced.append(str(out_m4a))
        print(f"[out] 已转 m4a：{out_m4a.name}")

    sec = round(time.time() - t0, 1)
    # M1 ~30W 电费估算，与 book2vido 同口径（¥0.6/kWh）
    cost = round(0.03 * sec / 3600 * 0.6, 5)
    print(f"[done] 总耗时 {sec}s，估算成本 ¥{cost}（纯电费，TTS 免费）")
    return {"turns": n_turns, "duration": round(total, 1), "seconds": sec,
            "cost": cost, "tts": True, "files": produced}
