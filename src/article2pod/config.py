"""配置加载。YAML 即 SSoT，代码只读不写。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

# 项目根：本文件在 src/article2pod/config.py，向上三级 = 项目根
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config.yaml"
DEFAULT_PROMPT = ROOT / "prompts" / "podcast_writer.md"


def load(config_path: str | os.PathLike | None = None) -> dict:
    p = Path(config_path) if config_path else DEFAULT_CONFIG
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在：{p}（可用默认 config.yaml 或 -c 指定）")
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg.setdefault("prompt_file", None)
    return cfg


def prompt_path(cfg: dict) -> Path:
    """提示词资产路径：config 指定优先，否则默认 prompts/podcast_writer.md。
    读不到必须当场报错，不退回任何内置文本（改了像没改是头号缺陷）。"""
    p = Path(cfg["llm"].get("prompt_file")) if cfg["llm"].get("prompt_file") else DEFAULT_PROMPT
    if not p.exists():
        raise FileNotFoundError(f"提示词资产不存在：{p}")
    return p
