"""article2pod · 文章→播客 零成本流水线（派生自 book2vido）。

把一篇公众号长文变成「主持人 + 作者」双人访谈式播客：
    Markdown 文章 → 本地 LLM 改写对话稿 → edge-tts 双音色 → FFmpeg 合成 mp3/m4a。
全程本地跑（ollama + edge-tts 免费档），零成本理念与 book2vido 一脉相承。
"""

__version__ = "0.1.0"
