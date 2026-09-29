"""URL → 本地 md（可选依赖 trafilatura，不进主 requirements）。

只做一件事：抓正文、落 md。落盘之后照旧走 `pipeline.read_article()`——
抓取与生成解耦，落盘的 md 就是人工可改的口子（与 --use-script 同款设计）。

抓不到就报错，绝不静默返回空 md：空 md 会让下游「假装成功」，
合成出一集没有内容的播客，比直接失败难查得多。
"""
from __future__ import annotations

import re
from pathlib import Path

# 低于这个字数基本是登录墙 / 验证页 / 404 页，不是正文。
MIN_CHARS = 200

# 明确不支持官方抓取的站点（风控/验证页/需要客户端态），见 doc/BLOG_INPUT_ANALYSIS.md
NOT_SUPPORTED_HOSTS = {
    "mp.weixin.qq.com": "公众号（正文 SSR 但风控与验证页多，请人工复制正文存 md）",
    "www.zhihu.com": "知乎（未登录 403，请人工复制正文存 md）",
    "zhihu.com": "知乎（未登录 403，请人工复制正文存 md）",
}


def fetch_to_md(url: str, out_dir: str = "demo/samples") -> Path:
    """抓 url 正文落 md，返回落盘路径。"""
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    if host in NOT_SUPPORTED_HOSTS:
        print(f"[fetch] ⚠️ {host} 不做官方抓取：{NOT_SUPPORTED_HOSTS[host]}。仍会尝试一次。")

    try:
        import trafilatura
    except ImportError as e:
        raise RuntimeError(
            "fetch 需要可选依赖 trafilatura：pip install -r requirements-fetch.txt"
            "（或 pip install '.[fetch]'）"
        ) from e

    html = trafilatura.fetch_url(url)
    if not html:
        raise RuntimeError(
            f"抓不到页面：{url}\n"
            f"（网络不通 / 被反爬 / URL 有误。若目标站需要登录，请人工复制正文存 md）"
        )

    md = trafilatura.extract(html, output_format="markdown",
                             with_metadata=True, favor_recall=True) or ""
    if len(md.strip()) < MIN_CHARS:
        raise RuntimeError(
            f"正文只抽出 {len(md.strip())} 字（<{MIN_CHARS}），多半是登录墙或反爬页：{url}\n"
            f"这是目标站的限制，不是 bug——请人工复制正文存成 md，再跑 article2pod <md>"
        )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w\u4e00-\u9fff-]", "_", url.rstrip("/").split("/")[-1])[:60] or "article"
    p = out / f"{slug}.md"
    p.write_text(md, encoding="utf-8")
    return p
