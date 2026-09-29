# demo · 实测成品

## 第 1 集：B19《我劝你别急着上 Agent 团队》

- 文章：《我劝你别急着上 Agent 团队》——一个让 4.7 万变 2.27 万的真实账本（公众号已发文章，B19 期）
- 成品：`out_B19/podcast.mp3`（157.7 s · 977 KB）· `out_B19/podcast.m4a`（1.78 MB）
- 对话稿：`out_B19/script.md`（18 轮：主持人 9 / 作者 9）

### 口径（每个对外数字都可复算）

| 数字 | 口径 |
|---|---|
| 157.7 s | `ffprobe format.duration` 实测回读 |
| 18 轮 | `script.json` 数组长度 |
| 生成耗时 96 s | 本次本机（M1 Pro 16GB）端到端含 LLM ~87 s；机器/模型不同会变 |
| 成本 ≈ ¥0.0005 | M1 ~30W × 96 s ÷ 3600 × ¥0.6/kWh 电费估算；TTS 免费、LLM 本地 |

### 对话稿的事实核验记录

LLM 首版对话稿被人工核出两处事实瑕疵，已在 `script.json` 修正后重合成（这也是推荐工作流 `--no-tts` 审稿 → 改稿 → `--use-script` 重合成的由来）：

1. **Marvis / Mavis 归属混淆**：首版「马维斯和 MiniMax 是同一家公司」→ 错。腾讯是 **Marvis**、MiniMax 是 **Mavis**（拼写差一字母，都致敬钢铁侠管家）；腾讯持股 MiniMax 约 2.58% 是真，但"共享敏感操作确认机制"是模型编造，已删。
2. 修正后表述与原文一致：「要手脚选腾讯 Marvis、要班组看 MiniMax 和 Kimi Work、要记性选 Hermes Agent；Grok Bot 不作安全边界」。

> 结论：**观点保真不能靠模型自觉，靠人工核稿**——LLM 输出必须过一遍原文比对，这是本项目的铁律。

---

## 冒烟复跑记录（2026-09-29 · 可用性验收）

用来证明「仓库 clone 下来就能跑」，不是成品展示。输入统一是 `samples/sample_article.md`（705 字）。

| 目录 | 路径 | 轮次 | 音频时长 | mp3 | m4a | 端到端耗时 |
|---|---|---|---|---|---|---|
| `out_smoke_ollama/` | ollama + qwen3:8b（默认路径） | 26 | 142.6 s | 812 KB | 1.45 MB | 147.9 s |
| `out_smoke_rule/` | `llm.provider: rule`（无模型降级） | 32 | 187.8 s | 1.01 MB | 1.83 MB | 21.3 s |

口径与上文一致：时长为 `ffprobe format=duration` 回读，耗时为端到端计时（含 LLM 与 TTS）。
`rule` 路径的作者句是**原文照搬**，不是访谈对话稿，只用于验证链路可跑。
