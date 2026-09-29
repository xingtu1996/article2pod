"""冒烟测试：不碰网络、不碰模型、不碰 ffmpeg。

三条底线：
1. 配置加载得通（YAML 是 SSoT，读不出来整条链路就死了）；
2. CLI 能起得来（--help 退出 0，是「装上了」的最低证据）；
3. 纯函数级转换符合契约（read_article / build_script_md / llm.validate）。
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from article2pod import config as config_mod
from article2pod import fetch as fetch_mod
from article2pod import llm, pipeline


# ── 1. 配置加载 ────────────────────────────────────────────


def test_load_default_config():
    cfg = config_mod.load()
    for section in ("llm", "tts", "limits", "concurrency", "out"):
        assert section in cfg, f"config.yaml 缺 {section} 段"
    assert cfg["llm"]["provider"] in ("ollama", "rule")


def test_load_missing_config_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        config_mod.load(tmp_path / "nope.yaml")


def test_prompt_asset_exists():
    """提示词资产读不到必须当场报错（改了像没改是头号缺陷）。"""
    cfg = config_mod.load()
    assert config_mod.prompt_path(cfg).exists()


# ── 2. CLI ────────────────────────────────────────────────


def test_cli_help_exit_zero():
    r = subprocess.run([sys.executable, "-m", "article2pod.cli", "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "article2pod" in r.stdout


def test_cli_missing_article_exits_nonzero():
    """不给文章参数 → argparse 退出 2，不是 0。"""
    r = subprocess.run([sys.executable, "-m", "article2pod.cli"],
                       capture_output=True, text=True)
    assert r.returncode != 0


# ── 3. 纯函数级转换 ────────────────────────────────────────


def test_read_article_strips_markdown(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(
        "---\ntitle: T\n---\n"
        "# 大标题\n\n"
        "![图](http://x/y.png)\n\n"
        "这是**正文**，带[链接](http://a.b)和 `代码`。\n",
        encoding="utf-8",
    )
    text = pipeline.read_article(p)
    assert "title: T" not in text        # frontmatter 已剥
    assert "http://x/y.png" not in text  # 图片已去
    assert "大标题" in text and not text.startswith("#")
    assert "这是正文" in text            # 加粗符号已去
    assert "链接" in text and "http://a.b" not in text


def test_read_article_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        pipeline.read_article("/definitely/not/here.md")


def test_build_script_md_labels():
    turns = [{"role": "host", "text": "问题"}, {"role": "author", "text": "回答"}]
    md = pipeline.build_script_md(turns)
    assert "**主持人**：问题" in md
    assert "**行途（作者）**：回答" in md


def test_validate_accepts_alternating_script():
    turns = [{"role": "host", "text": "a"}, {"role": "author", "text": "b"}]
    assert llm.validate(turns) == turns


@pytest.mark.parametrize("bad,why", [
    ([], "空数组"),
    ([{"role": "author", "text": "x"}], "非 host 开场"),
    ([{"role": "host", "text": "a"}, {"role": "host", "text": "b"}], "角色未交替"),
    ([{"role": "host", "text": "  "}], "text 为空"),
    ([{"role": "narrator", "text": "a"}], "role 非法"),
])
def test_validate_rejects_bad_script(bad, why):
    with pytest.raises(RuntimeError):
        llm.validate(bad)


def test_fetch_without_optional_dependency():
    """fetch 是可选能力：没装 trafilatura 必须给明确安装提示，不能静默失败。"""
    try:
        import trafilatura  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("本机已装 trafilatura，跳过「未装依赖」分支")
    with pytest.raises(RuntimeError, match="requirements-fetch"):
        fetch_mod.fetch_to_md("https://example.com")


def test_fetch_rejects_unsupported_host_before_network():
    """公众号/知乎只提示不拦截：真要抓由 trafilatura 决定，提示信息必须落到 stdout。"""
    assert "mp.weixin.qq.com" in fetch_mod.NOT_SUPPORTED_HOSTS
    assert "zhihu.com" in fetch_mod.NOT_SUPPORTED_HOSTS


def test_rule_provider_needs_no_model():
    """rule 是无模型降级路径：不联网、不调 ollama，也能产出合规对话稿。"""
    cfg = config_mod.load()
    cfg["llm"]["provider"] = "rule"
    turns = llm.generate(cfg, "第一句说的是开源这件事。第二句说的是本地优先。第三句说的是成本。")
    assert turns[0]["role"] == "host"
    for a, b in zip(turns, turns[1:]):
        assert a["role"] != b["role"]
    assert all(t["text"] for t in turns)
    assert len(turns) <= cfg["limits"]["max_turns"]
