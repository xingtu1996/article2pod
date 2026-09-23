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


class EdgeTTSProvider:
    """edge-tts 双音色：每句按 role 选 voice（host_voice / author_voice）。"""

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


def build(cfg: dict):
    """按 config 造 TTS provider。"""
    tts_cfg = cfg["tts"]
    if tts_cfg["provider"] == "edge":
        return EdgeTTSProvider(tts_cfg["host_voice"], tts_cfg["author_voice"],
                               timeout=tts_cfg.get("timeout", 45.0))
    return SayProvider()
