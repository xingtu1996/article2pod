# 贡献指南（简版）

## 环境

```bash
git clone <你的 fork>
cd article2pod
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # 运行时依赖 + pytest + ruff
pip install -e .
```

系统前置：`ffmpeg` / `ffprobe`（合成与时长回读都要用）。
可选：`ollama` + `ollama pull qwen3:8b`（要真对话稿才需要，见下）。

## 两条运行路径

| 路径 | 命令 | 需要什么 | 产出 |
|---|---|---|---|
| 真·对话稿 | `article2pod 文章.md -o demo/out` | ollama 在跑 + qwen3:8b | 访谈式播客 |
| 无模型降级 | 把 `config.yaml` 的 `llm.provider` 改成 `rule` | 什么都不要 | 原文切句版（**不是**对话稿，只保链路可跑） |

## 提交前必跑

```bash
ruff check src tests
pytest -q
article2pod --help        # 退出码必须是 0
```

CI（`.github/workflows/ci.yml`）在 Python 3.10 / 3.12 上跑同样的四步，红就是红。

## 本项目的三条铁律（改代码前先读）

1. **YAML 与提示词是 SSoT**：`config.yaml` 管行为、`prompts/podcast_writer.md` 管模型行为。代码只读不写，不要在代码里内置兜底文本（改了像没改是头号缺陷）。
2. **失败要吵，不要静默**：TTS 空音频、配置读不到、LLM 输出不合契约——一律抛错，不许凑合产出。
3. **每个对外数字都能复算**：README / demo 里的时长、体积、耗时、成本，都要写清口径（怎么测的）。

## 目录约定

```
src/article2pod/   代码（config / llm / tts / compose / pipeline / cli / gui）
prompts/           提示词资产（改这个等于改模型行为）
config.yaml        行为配置
tests/             不碰网络、不碰模型、不碰 ffmpeg 的冒烟测试
demo/              实测成品（保留，是口径证据）
doc/               设计分析文档
```

## 隐私红线

- 仓库里**禁止出现真实姓名、本机绝对路径、模型本地路径**（`.gitignore` 已排除 6.7G 模型目录）。
- 写文档、贴日志、写测试数据时先自查一遍再提交。
