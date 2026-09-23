"""双音色 TTS。edge-tts（免费匿名，需网）| say（macOS 本地，断网可跑）。

并发、重试、自适应降并发、超时保护的设计直接复用 book2vido narrator.py 的实测结论：
纯网络 IO 等待，高并发收益大；限流时硬重试只会加剧限流，要降并发；绝不允许静默产出 0 字节。
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable


def _duration(p: str) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", p]
        )
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 3.0


# edge-tts 中文音色表（微软免费档，2026-09-23 实测：仅下表 6 个音色可用）。
# ⚠️ 曾列入的晓梦/晓涵/晓辰/云野/云枫/云杰实测返回 NoAudioReceived（服务端无此音色），已剔除。
# 集成新的本地开源 TTS（ChatTTS/CosyVoice 等）后，这里会扩展出更自然的音色。
EDGE_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓", "gender": "女", "desc": "温暖清晰，默认主持人", "cute": False},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊", "gender": "女", "desc": "活泼少女感，可爱首选", "cute": True},
    {"id": "zh-CN-XiaoxuanNeural", "name": "晓萱", "gender": "女", "desc": "干练女声", "cute": False},
    {"id": "zh-CN-YunxiNeural", "name": "云希", "gender": "男", "desc": "阳光青年，默认作者", "cute": False},
    {"id": "zh-CN-YunjianNeural", "name": "云健", "gender": "男", "desc": "沉稳磁性", "cute": False},
    {"id": "zh-CN-YunyangNeural", "name": "云扬", "gender": "男", "desc": "新闻播报感", "cute": False},
]


# 音色组合预置（GUI「选组合」）。host/author 取 EDGE_VOICES 的 id。
VOICE_PRESETS = [
    {"id": "default", "name": "知性访谈", "desc": "晓晓(女)+云希(男)，清晰对谈，默认",
     "host": "zh-CN-XiaoxiaoNeural", "author": "zh-CN-YunxiNeural"},
    {"id": "cute", "name": "萌系对谈", "desc": "晓伊(女)+云希(男)，活泼可爱风",
     "host": "zh-CN-XiaoyiNeural", "author": "zh-CN-YunxiNeural"},
    {"id": "deep", "name": "沉稳深谈", "desc": "云健(男)+云希(男)，深夜电台质感",
     "host": "zh-CN-YunjianNeural", "author": "zh-CN-YunxiNeural"},
    {"id": "warm", "name": "温暖陪伴", "desc": "晓晓(女)+云健(男)，温柔治愈向",
     "host": "zh-CN-XiaoxiaoNeural", "author": "zh-CN-YunjianNeural"},
    {"id": "news", "name": "新闻质感", "desc": "云扬(男)+云希(男)，信息密度高",
     "host": "zh-CN-YunyangNeural", "author": "zh-CN-YunxiNeural"},
]


# 语气（GUI「选语气」，注入对话稿 prompt 的 {tone}）
TONES = [
    {"id": "natural", "name": "自然口语", "desc": "像朋友聊天（默认）"},
    {"id": "lively", "name": "活泼轻快", "desc": "节奏快、情绪上扬、多语气词"},
    {"id": "serious", "name": "沉稳专业", "desc": "克制、理性、少修辞"},
    {"id": "cute", "name": "可爱萌系", "desc": "语气软糯、多叠词与拟声"},
    {"id": "story", "name": "讲故事", "desc": "叙述感强、有画面、留悬念"},
]


class EdgeTTSProvider:
    """edge-tts 双音色：每句按 role 选 voice（host_voice / author_voice）。"""

    @classmethod
    def voices(cls) -> list[dict]:
        """可用音色列表（GUI 音色选择器）。"""
        return EDGE_VOICES

    def __init__(self, host_voice: str, author_voice: str, timeout: float = 45.0):
        self.voices = {"host": host_voice, "author": author_voice}
        self.timeout = timeout

    def voice_for(self, role: str) -> str:
        if role not in self.voices:
            raise ValueError(f"未知 role：{role}")
        return self.voices[role]

    def speak(self, role: str, text: str, out_path: str) -> float:
        import edge_tts

        async def _run():
            comm = edge_tts.Communicate(text, self.voice_for(role))
            # 超时保护：edge-tts 断网/限流会静默 hang，抛 TimeoutError 让上层回退 say。
            await asyncio.wait_for(comm.save(out_path), timeout=self.timeout)

        asyncio.run(_run())
        p = Path(out_path)
        if not p.exists() or p.stat().st_size == 0:
            raise RuntimeError(f"TTS 输出为空（{out_path}）——edge-tts 未产出音频")
        return _duration(out_path)

    def speak_many(self, items: list[tuple[int, str, str, str]], max_workers: int = 8,
                   on_progress: Callable[[int, int], None] | None = None) -> dict[int, float]:
        """items = [(index, role, text, out_path)] → {index: duration}。

        带重试（初始 2 次额度）与自适应降并发（失败率 >50% 减半线程），绝不丢条、绝不静默空音频。
        """
        if not items:
            return {}
        total = len(items)
        pending = [(idx, role, text, out, 2) for idx, role, text, out in items]
        results: dict[int, float] = {}
        errors: dict[int, Exception] = {}
        workers = max(1, max_workers)

        while pending:
            ran = len(pending)
            failed: list = []
            with ThreadPoolExecutor(max_workers=min(workers, ran)) as ex:
                futs = {ex.submit(self.speak, role, text, out): (idx, role, text, out, rt)
                        for idx, role, text, out, rt in pending}
                for fut in as_completed(futs):
                    idx, role, text, out, rt = futs[fut]
                    try:
                        results[idx] = fut.result()
                    except Exception as e:
                        errors[idx] = e
                        failed.append((idx, role, text, out, rt))
                    if on_progress:
                        on_progress(len(results), total)

            if not failed:
                break
            if ran > 1 and len(failed) / ran > 0.5:
                workers = max(1, workers // 2)
                print(f"[tts] 本轮失败率 {len(failed) / ran:.0%} > 50%，降到 {workers} 线程重试")

            next_pending = []
            for idx, role, text, out, rt in failed:
                if rt > 0:
                    time.sleep(0.3)
                    next_pending.append((idx, role, text, out, rt - 1))
            pending = next_pending
            if not pending:
                break

        if len(results) != total:
            failed_idx = sorted(set(i[0] for i in items) - results.keys())
            last = "; ".join(f"#{i}: {type(errors[i]).__name__}: {errors[i]}" for i in failed_idx)
            raise RuntimeError(f"TTS 最终仍失败 {len(failed_idx)}/{total} 条，index={failed_idx}。最后异常：{last}")
        return results


class SayProvider:
    """macOS say 本地兜底（断网可跑）。双音色：host=婷婷, author=阿亮（中文变体）。"""

    @classmethod
    def voices(cls) -> list[dict]:
        return [
            {"id": "Tingting", "name": "婷婷", "gender": "女", "desc": "macOS 本地", "cute": False},
            {"id": "Liang", "name": "阿亮", "gender": "男", "desc": "macOS 本地", "cute": False},
        ]

    def __init__(self):
        self.voices = {"host": "Tingting", "author": "Liang"}

    def speak(self, role: str, text: str, out_path: str) -> float:
        aiff = str(out_path).replace(".mp3", ".aiff")
        voice_arg = f"{self.voices[role]} (中文（中国大陆）)"
        subprocess.run(["say", "-v", voice_arg, "-o", aiff, text], check=True)
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", aiff, out_path], check=True)
        p = Path(out_path)
        if not p.exists() or p.stat().st_size == 0:
            raise RuntimeError(f"say→ffmpeg 未产出音频（{out_path}）")
        return _duration(out_path)

    def speak_many(self, items, max_workers=4, on_progress=None):
        if not items:
            return {}
        results: dict[int, float] = {}
        for i, (idx, role, text, out) in enumerate(items):
            results[idx] = self.speak(role, text, out)
            if on_progress:
                on_progress(len(results), len(items))
        return results


def build(cfg: dict, host_voice: str | None = None, author_voice: str | None = None):
    """按 config 造 TTS provider。host_voice/author_voice 非空则覆盖配置（GUI 传参）。"""
    tts_cfg = cfg["tts"]
    hv = host_voice or tts_cfg.get("host_voice")
    av = author_voice or tts_cfg.get("author_voice")
    if tts_cfg["provider"] == "edge":
        return EdgeTTSProvider(hv or "zh-CN-XiaoxiaoNeural", av or "zh-CN-YunxiNeural",
                               timeout=tts_cfg.get("timeout", 45.0))
    return SayProvider()


def list_providers() -> list[dict]:
    """GUI 引擎选择：当前已实现的 TTS 引擎。集成新的本地开源 TTS 时在这里注册。"""
    return [
        {"id": "edge", "name": "edge-tts（免费在线）", "desc": "微软免费档，12 个中文音色，需网"},
        {"id": "say", "name": "macOS say（本地）", "desc": "断网可跑，仅 2 个中文音色"},
    ]
