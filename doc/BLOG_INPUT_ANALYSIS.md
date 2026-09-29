# 博客内容输入能力分析（article2pod）

> 结论先行：**当前只吃「本地纯文本文件」，一个 URL 都吃不了。**
> 本文的每个结论都标了代码出处，没有的代码一律写「不支持」，不靠猜。
> 撰写时间：2026-09-29 · 代码基线：`src/article2pod/`（cli / pipeline / llm / tts / config / compose / gui）

---

## 一、当前支持什么（逐个读代码给结论）

| 输入源 | 支持 | 代码证据 | 说明 |
|---|---|---|---|
| 本地 `.md` | ✅ | `pipeline.py:24-35` `read_article()` | `Path(path).read_text(encoding="utf-8")`，UTF-8 硬编码 |
| 本地 `.txt` 及任意纯文本 | ✅（事实支持，非官方） | 同上 | **不校验扩展名**，只要是 UTF-8 文本就能读 |
| 本地文件带 YAML frontmatter | ✅ | `pipeline.py:15-21` `_strip_frontmatter()` | 开头 `--- … ---` 会被剥掉 |
| 图片 / 链接 / 标题符号 | ✅（自动清洗） | `pipeline.py:31-34` | 去 `#`、去 `![]()`、链接降级为纯文字、去 `*_>`~` |
| 公众号 URL | ❌ | 全仓无抓取代码 | 见下方 grep 证据 |
| 任意网页 URL | ❌ | 同上 | — |
| RSS / 站点批量导入 | ❌ | 同上 | — |
| 目录 / 批量多文件 | ❌ | `cli.py:16` 单个 positional | 一次只能给一个文件 |
| 剪贴板 / stdin | ❌ | 无相关分支 | — |

### 「不支持 URL」的证据（不是猜的）

对 `src/` 全量 grep 网络相关符号，对外 HTTP 只有两处，都跟「抓文章」无关：

- `llm.py:90-95` → `urllib.request.urlopen(base_url + "/api/generate")`：调本机 ollama
- `gui/server.py:224` → `urlopen("http://localhost:11434/api/tags")`：GUI 环境自检
- `gui/server.py:258-283` `/api/upload`：**multipart 上传文件**落 `uploads/`，不是抓 URL
- `gui/server.py:290-291`：`body.get("path")` 只认**本地存在的路径**（`Path(...).exists()` 否则报错）

没有任何 `requests` / `httpx` / `feedparser` / `readability` / `trafilatura` 依赖（`pyproject.toml:11-14` 只有 `pyyaml` + `edge-tts`）。

### 还有两个「能吃但会咬人」的既有约束

1. **12 000 字硬截断**：`pipeline.py:56-58`，正文超 `limits.max_chars` 直接取开头，**尾部静默丢弃**。万字长文会被砍掉后半段，对话稿也就只覆盖前半篇。
2. **UTF-8 硬编码**：`pipeline.py:28`，GBK 编码的 txt 会直接抛 `UnicodeDecodeError`，没有 fallback。

---

## 二、`article2pod fetch <url>` 最小实现方案

### 2.1 设计原则（对齐本项目既有铁律）

- **可选依赖，不污染主干**：`fetch` 是「有则更好」，不能让 `pip install -e .` 变重。
- **落 md 即脱钩**：抓取与生成解耦——`fetch` 只负责「URL → 本地 md」，后面照旧走 `read_article()`。落盘的 md 就是人工可改的口子（与 `--use-script` 同款设计）。
- **失败要吵，不要静默**：抓不到正文就报错退出，绝不返回空 md 让下游假装成功（`config.py` 里「读不到必须当场报错」的同款要求）。

### 2.2 流程（4 步）

```
URL → HTTP GET（带 UA / 超时 / 编码探测）
    → 正文提取（去导航、评论、广告、脚本）
    → 组装 md（YAML frontmatter: title/url/date/hostname + 正文）
    → 落盘 <out>/<slug>.md，打印路径，可直接喂 article2pod
```

### 2.3 依赖选型对比（实测，非拍脑袋）

实测环境：本机 · trafilatura 2.2.0 · 各站点单次 GET。

| 方案 | 装包体积 | 中文正文 | 直接出 Markdown | 元数据 | 维护活跃度 | 结论 |
|---|---|---|---|---|---|---|
| **trafilatura** | 中（纯 Py + lxml） | 好 | ✅ 原生 `output_format="markdown"` | ✅ title/date/author/url | 活跃（v2.x 持续更新） | **推荐** |
| readability-lxml | 小 | 好 | ❌ 只给 HTML 片段，需再接 html2text | ❌ 要自己补 | 弱（长期低频更新） | 次选，还要多接一个转换库 |
| newspaper3k | 大（拉 nltk 语料） | 中 | ❌ | ✅ | **停滞**（Py3.12 有兼容坑） | 不推荐 |
| 标准库 `urllib` + 正则 | **0** | 差 | 自己做 | ❌ | — | 只当兜底，正文质量无保障 |
| requests + BeautifulSoup | 小 | 中 | 自己做 | ❌ | 活跃 | 等于自己重写一遍 trafilatura |

**选 trafilatura 的理由**：它是唯一一个把「抓取 + 正文抽取 + Markdown 输出 + 元数据」一次性做完且还活着的库；本项目的 `read_article()` 本来就吃 md，输出 md 正好无缝对接，中间零转换代码。

### 2.4 trafilatura 实测数据（本次真跑）

| 目标 | HTTP | 原始 HTML | 抽出 md | 耗时 |
|---|---|---|---|---|
| `https://example.com` | 200 | 713 B | 186 B（含 title frontmatter） | 1.0 s |
| Hugo 静态博客 `gohugo.io/getting-started/quick-start/` | 200 | 76 KB | **4 902 B**（title/url/hostname/description 齐全） | 0.9 s |
| 重定向页（Rust blog 旧链接） | 200 | 460 B | 71 B | 0.8 s |

调用形态（就是这么短）：

```python
import trafilatura
html = trafilatura.fetch_url(url)
md = trafilatura.extract(html, output_format="markdown",
                         with_metadata=True, favor_recall=True)
```

### 2.5 已落地的实现（2026-09-29）

按方案实现，实际落成三处，共约 60 行：

| 位置 | 内容 |
|---|---|
| `src/article2pod/fetch.py` | `fetch_to_md(url, out_dir)`：抓 → 抽 → 落 md；含 `MIN_CHARS=200` 短正文判定与 `NOT_SUPPORTED_HOSTS` 提示表 |
| `src/article2pod/cli.py:14-30` | `article2pod fetch <url>` 子命令（主流程 positional `article` 原样保留，向后兼容） |
| `pyproject.toml:16-19` + `requirements-fetch.txt` | `[project.optional-dependencies] fetch = ["trafilatura>=1.12"]`，**不进主 `requirements.txt`** |

三条硬约束（与方案一致，代码里都有）：

1. **抓不到就报错退出**——空 HTML、抽取少于 200 字，都抛 `RuntimeError`，绝不静默返回空 md；
2. **公众号/知乎先提示**——命中 `NOT_SUPPORTED_HOSTS` 时先打印「不做官方抓取，请人工复制正文存 md」，再尝试一次；失败信息里也带这句话，用户不会误以为是 bug；
3. **未装依赖给明确出路**——`ImportError` 转成「pip install -r requirements-fetch.txt」，而不是裸抛堆栈。

用法：

```bash
pip install -r requirements-fetch.txt          # 只抓 URL 的人需要这一步
article2pod fetch https://某静态博客/某篇文章.html -o demo/samples
article2pod demo/samples/<落盘文件名>.md -o demo/out
```

---

## 三、各博客平台可行性（一条一个结论）

### 3.1 静态博客（Hexo / Hugo / Jekyll / 自建 WordPress）— **可行性：高**

- 服务端渲染，正文就在 HTML 里，不需要 JS 执行；本次实测 Hugo 站点 0.9 s 抽出 4.9 KB 干净 md，元数据齐全。
- 大多数还挂了 RSS/Atom——**优先走 RSS**，比解析 HTML 稳，还能批量。
- 结论：**直接上 trafilatura，成功率最高的一类**。这是 `fetch` 子命令真正的主战场。

### 3.2 微信公众号（mp.weixin.qq.com）— **可行性：中低，建议走人工导出**

已知事实（本次实测 + 代码事实）：

- 正文在 `#js_content` 容器内，**服务端已渲染**，理论上不跑 JS 也能拿到；
- 但链接有效性与访问环境强相关：本次用无效 id 实测，返回 **HTTP 200 + 31 KB 的 weui 提示页**（不是正文，也不是 404）——**必须校验「抽出来像不像正文」，光看状态码会翻车**；
- 高频访问会触发「环境异常」验证页，需要 cookie / 客户端 referer，脚本爬不稳；
- 图片走独立域名且带防盗链，本来也会被 `read_article()` 剥掉，不影响。

结论（**已拍板，2026-09-29**：**不纳入官方支持**）：不做 best effort 也要背维护债——爬不稳的失败会被当成 bug 报上来，人工导出只要 30 秒。
落地形态：`mp.weixin.qq.com` 进了 `fetch.py` 的 `NOT_SUPPORTED_HOSTS`，命中时**先打印提示再尝试**，失败信息里也带「请人工复制正文存 md」。用户不会误以为是程序坏了，但也不会有人来提「公众号抓取不准」的 issue。
正确路径：微信客户端/编辑器里复制正文 → 存 md → 本地喂入（现有链路已完全支持）。

### 3.3 掘金（juejin.cn）— **可行性：中**

- 列表/首页可访问（本次实测 `juejin.cn` 返回 200 / 79 KB）；文章页正文部分 SSR、部分依赖接口。
- 有风控（频率限制、偶发滑块），无登录状态一般能拿公开文章，但**稳定性不保证**。
- 结论：**能抓，但要带 UA + 限速 + 失败重试**，属于「能跑但别指望百分之百」。

### 3.4 知乎（zhihu.com）— **可行性：低，不建议抓**

- 本次实测：`https://www.zhihu.com/question/...` 直接 **HTTP 403**，响应体仅 650 B —— 未登录强风控，回答正文需要登录态。
- 登录态抓取涉及 cookie 合规与账号风险，与本项目「零成本、不出本机、不折腾」的定位冲突。
- 结论：**不做**。要走就人工复制正文存 md。

### 3.5 通用前提（任何平台都适用）

- 遵守 `robots.txt` 与目标站 ToS；
- **只拿自己的文章做播客**——他人文章的音频化改编涉及著作权与邻接权，本项目定位是「自己的文章 → 自己的播客」，不要越线；
- `limits.max_chars = 12000` 会截断长文，抓下来的长篇要留意尾部被砍（这是既有行为，不是 fetch 引入的）。

---

## 四、拍板结果（2026-09-29 已定，三项全采纳 A/A/B）

| # | 事项 | 决定 | 落地位置 |
|---|---|---|---|
| 1 | `fetch` 是否实现 | **实现** | `src/article2pod/fetch.py` + `cli.py` 子命令，见 §2.5 |
| 2 | 依赖策略 | **可选依赖组 `fetch`**（trafilatura ≥1.12，不进主 requirements） | `pyproject.toml:16-19`、`requirements-fetch.txt` |
| 3 | 公众号是否纳入官方支持 | **不纳入**，文档写明「请人工导出 md」 | `fetch.py:NOT_SUPPORTED_HOSTS` + §3.2 |

> 补充一条纪律：**不再从 book2vido 等私有仓取素材进本仓**（两仓可见性不同）。
> 本轮曾借过一份样例，已换成自造的公开样例 `demo/samples/sample_article.md`，并重跑了全部产物。

---

## 五、一句话总结

> 现在是「有 md 就能出播客，没有 md 就啥也干不了」。
> 加一个 `fetch`（trafilatura 可选依赖，~40 行）就能把静态博客这条路打通——**实测 0.9 秒拿 4.9 KB 干净 md**；
> 公众号和知乎不值得为它写爬虫，人工导出更划算。
