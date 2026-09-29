"""对话稿生成（LLM）。文章 → 双人访谈式对话稿 JSON。

提示词不在代码里（资产独立）：住在 prompts/podcast_writer.md，
本模块只负责「加载 → 渲染 → 调用 → 解析」，是管道不是内容（book2vido T2V-007 同款）。
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request

from . import config as config_mod

# 对话稿契约：list[{"role": "host"|"author", "text": str}]
# role 只允许这两个值，host 开场、两者交替——pipeline 与 TTS 都依赖此契约。
ROLES = ("host", "author")


TONE_TEXT = {
    "natural": "像朋友在咖啡馆聊天：松弛、自然、有来有回，不端着。",
    "lively": "活泼轻快：节奏快、情绪上扬、多用语气词（哇/诶/真的假的），偶尔开个小玩笑。",
    "serious": "沉稳专业：克制、理性、少修辞，数字和逻辑优先，不煽情。",
    "cute": "可爱萌系：语气软糯，允许叠词与拟声（嘿嘿/咕咕），但观点依然清晰不卖萌水话。",
    "story": "讲故事：叙述感强、有画面感、关键处留悬念，像深夜电台讲一个真实经历。",
}


def load_prompt(cfg: dict, tone: str | None = None) -> tuple[str, str]:
    """返回 (渲染后的 prompt, 指纹)。指纹 = 模板内容 hash + max_turns + tone，进缓存键。"""
    p = config_mod.prompt_path(cfg)
    body = p.read_text(encoding="utf-8")
    tone = tone or "natural"
    tone_text = TONE_TEXT.get(tone, TONE_TEXT["natural"])
    rendered = (body.replace("{max_turns}", str(cfg["limits"]["max_turns"]))
                .replace("{tone}", tone_text))
    fp = hashlib.sha256(f"{body}|{cfg['limits']['max_turns']}|{tone}".encode()).hexdigest()[:16]
    return rendered, fp


# 规则降级用的主持人串词池（无模型时的兜底，不是对话稿创作）
RULE_HOST_LINES = [
    "我们先从一个最根本的问题聊起——这东西到底是怎么来的？",
    "说得很清楚。接着往下，它具体是怎么跑起来的？",
    "那落到工程上，最关键的取舍是什么？",
    "有没有哪个数字能说明这件事的代价？",
    "最后一句，你想让听的人记住什么？",
]


def _rule_generate(cfg: dict, article: str) -> list[dict]:
    """无模型降级：把正文切句，主持人串词与作者原句交替。

    只保证链路可跑（审稿/TTS/合成全通），**不产出真正的访谈对话稿**——
    作者句全部是原文照搬，不做改写、不做提问设计。要成品请用 ollama。
    """
    sents = [s.strip() for s in re.split(r"[。！？!?；;\n]+", article) if len(s.strip()) >= 8]
    if not sents:
        raise RuntimeError("规则降级失败：正文切不出可用句子（换个长一点的文章）")
    max_turns = cfg["limits"]["max_turns"]
    # host+author 成对，最多 max_turns 轮
    pairs = (max_turns - 1) // 2
    chunk = max(1, -(-len(sents) // max(1, pairs)))  # 向上取整，合并句子凑够每轮
    # 先切块再截断，避免 range 走到空切片产出「。」这种空轮
    blocks = [sents[i:i + chunk] for i in range(0, len(sents), chunk)][:pairs]
    turns: list[dict] = []
    for i, block in enumerate(blocks):
        turns.append({"role": "host",
                      "text": RULE_HOST_LINES[i] if i < len(RULE_HOST_LINES) else "继续说说。"})
        turns.append({"role": "author", "text": "。".join(block) + "。"})
    print("[script] ⚠️ rule 降级：作者句为原文照搬，非访谈对话稿（出成品请用 ollama）")
    return validate(turns)


def generate(cfg: dict, article: str, tone: str | None = None) -> list[dict]:
    """生成对话稿。provider=ollama 走本地模型；rule 为无模型降级（config.yaml 已声明）。"""
    llm = cfg["llm"]
    if llm["provider"] == "rule":
        return _rule_generate(cfg, article)
    if llm["provider"] != "ollama":
        raise RuntimeError(f"llm.provider={llm['provider']} 不支持对话稿生成（需要 ollama 或 rule）")
    prompt, fp = load_prompt(cfg, tone)
    rendered = prompt.replace("{article}", article)
    payload = {
        "model": llm["model"],
        "prompt": rendered,
        "stream": False,
        "think": llm.get("think", True),
        "options": {"temperature": 0.7, "num_predict": 6000},
    }
    url = llm["base_url"].rstrip("/") + "/api/generate"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        raw = urllib.request.urlopen(req, timeout=600).read().decode()
        resp_text = json.loads(raw).get("response", "")
    except Exception as e:
        raise RuntimeError(f"Ollama 调用失败（{url}）：{e}") from e
    turns = _parse(resp_text)
    return turns


def validate(arr) -> list[dict]:
    """契约校验（LLM 输出与 --use-script 人工改稿共用）：role 合法、text 非空、host 开场、交替。"""
    if not isinstance(arr, list) or not arr:
        raise RuntimeError("对话稿为空数组")
    out: list[dict] = []
    for i, item in enumerate(arr):
        if not isinstance(item, dict):
            raise RuntimeError(f"对话稿第 {i + 1} 项不是对象：{item!r}")
        role = str(item.get("role", "")).strip()
        text = str(item.get("text", "")).strip()
        if role not in ROLES:
            raise RuntimeError(f"对话稿第 {i + 1} 项 role 非法：{role!r}（只允许 {ROLES}）")
        if not text:
            raise RuntimeError(f"对话稿第 {i + 1} 项 text 为空")
        out.append({"role": role, "text": text})
    # 契约：host 开场 + 交替。违反就是模型没服从 prompt，宁可报错重跑。
    if out[0]["role"] != "host":
        raise RuntimeError("对话稿必须以 host 开场")
    for a, b in zip(out, out[1:]):
        if a["role"] == b["role"]:
            raise RuntimeError(f"对话稿角色未交替：第 {out.index(b) + 1} 项连续出现 {b['role']}")
    return out


def _parse(raw: str) -> list[dict]:
    """从模型输出里抽出 JSON 数组并校验契约。非法输出直接报错，不静默凑合。"""
    # 模型偶尔会包 markdown 代码块或前后缀文字——剥掉后仍要整体是数组。
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        raise RuntimeError("模型输出中没有 JSON 数组，对话稿解析失败（可调 prompt 或换模型）")
    try:
        arr = json.loads(m.group())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"模型输出 JSON 解析失败：{e}") from e
    return validate(arr)
