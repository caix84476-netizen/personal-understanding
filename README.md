<div align="center">

# Personal Understanding

**一个带原话溯洄的模拟人脑联想、发散、聚合、逆向等的 agent 记忆系统。**

[English](README.en.md) · [它是什么](#它是什么) · [功能地图](#功能地图) · [上手](#上手) · [设计思路](#设计思路)

[![PyPI](https://img.shields.io/pypi/v/personal-understanding)](https://pypi.org/project/personal-understanding/)
[![Python](https://img.shields.io/pypi/pyversions/personal-understanding)](https://pypi.org/project/personal-understanding/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/caix84476-netizen/personal-understanding?style=social)](https://github.com/caix84476-netizen/personal-understanding/stargazers)

</div>

`agent 记忆` `personal memory` `AI 记忆系统` `MCP server` `local-first` `verbatim capture` `原话溯洄` `联想检索` `Personalized PageRank` `时间线记忆` `可审计记忆` `anti-hallucination memory` `personal knowledge management` `LLM agent memory` `claude skill` `codex skill`

---

## 它是什么

给 AI 助手用的个人记忆系统：装在 Claude / Codex / Pi 这类客户端里，让它跨会话地「记得你这个人」。

和主流做法（每句话先摘要、先向量化，原话加工完就丢）相反，它把顺序倒过来：**先把你说的话一字不改存下来，理解只是原话的派生物**。派生物记错了可以重算、可以纠正，原话永远在位可以核对——这是「原话溯洄」的意思。至于「联想、发散、聚合、逆向」，是它在回忆时模拟人脑的四种找法，下面[功能地图](#功能地图)逐个讲。

## 一条消息的一生

```text
你的消息 → ① 预检分类：是个人内容吗？（技术问答直接跳过，不碰档案）
        → ② 原话捕获：完整消息逐字节落盘 + SHA-256，永不可改
        → ③ 派生：拆出事件、人物、情境卡、待回访；模型猜测进独立假设层
        → ④ 闭环：每条捕获显式关闭，过不了硬闸门就不算「已记住」
        → ⑤ 日后回想：survey 看地图 → probe 发散 → deep 回原话，外加一条联想通道
```

①–④ 的机制：[docs/how-it-works.md](docs/how-it-works.md) 第一到三节；⑤ 在第四到八节。

## 功能地图

按「记、存、想、养」四组。每条给一句「为什么」，细节全部链到详文。

### 记：进来的时候

- **两档闸门**——个人内容走全流程；纯技术、吃什么、一次性购物完全不碰档案。分类器漏判由模型兜底，宁可多收不漏收。（为什么：漏收 = 原话永久丢失；[机制](docs/how-it-works.md#1-入口两档闸门与预检分类)）
- **原话不可变捕获**——完整消息逐字节落盘，带 SHA-256、时间戳、会话标识；纠正只新增不覆盖；图片音频保原件，OCR 只是派生。（为什么：摘要先行 = 原话加工后无法审计；[机制](docs/how-it-works.md#2-原话保真先存证据再谈理解)）
- **派生闭环 + 硬闸门**——存下原话不算完：必须拆出记录并显式闭环，孤立捕获过不了回答前的 session_check。（为什么：「相信我，存好了」在真实生活里不够格——[2.5.0 重复建档事故](docs/why-it-works.md#31-事故与修补全表)；[机制](docs/how-it-works.md#3-派生与闭环从一段原话到档案)）
- **足迹纪律**——游戏攻略、在读在看这类轻足迹：先定向查重，恰好一条微型记录，零新增体面关闭。（为什么：防止把单次咨询堆成档案噪声；[机制](docs/how-it-works.md#1-入口两档闸门与预检分类)）

### 存：档案怎么组织

- **时间主干**——每条记录带发生日/精度/依据/阶段/前后邻居；禁止把录入当天冒充发生日。（为什么：「你现在处于某阶段」的断言要先对日期再讲故事；[细则](references/timeline-and-followup-policy.md)）
- **实体档案 + 情境卡**——人、学校、地点、作品、游戏、概念九类实体页 + 「学校 × 足球」式交叉情境卡；事实只存一份，卡片只是投影。（为什么：实体正文写可变状态会变成永不更新的僵尸信息；[细则](references/entity-and-context-policy.md)）
- **事实五层**——原话事实 / 你的评价 / 你的解释 / 模型假设 / 无法确认，永远分层摆放；模型猜测恒为 `candidate`，至少两条证据才立项，永不转正。（为什么：防止 AI 把自己的推测当你的事实记；[细则](references/causal-hypothesis-policy.md)）
- **待回访**——「等几天看结果」这类开放闭环带到期日入档，到期主动带上下文回访。（为什么：沉默不是答复，换话题不等于已解决；[细则](references/timeline-and-followup-policy.md)）

### 想：怎么回忆起来

- **survey → probe → deep 三层渐进**——先看 48K 紧凑路由地图定向，再沿实体/情境/时间邻居发散，最后回原话核验；每步预算封顶，不把全库灌给模型。（为什么：灌全库 = 模型被无关记忆淹没；[机制](docs/how-it-works.md#5-survey--probe--deep三层渐进检索)）
- **联想通道（发散）**——个性化 PageRank 沿档案图扩散，带出词面零重叠但确实相关的候选（「打击感」→「巫师3 骑马手感」）；是候选池不是结论，模型判断成立才引用。（为什么：「书荒了整本来嚼嚼」这类话三个词面通道全灭过——[2.6.0 事故](docs/why-it-works.md#31-事故与修补全表)；[机制](docs/how-it-works.md#6-联想通道发散词面对不上的怎么想起来)）
- **聚合读法（侦探拼图）**——「我该怎么办」拆成情绪线/利益线/人物线分头查，再拼起来；回答分档案事实/模式观察/模型推断三层。（为什么：宽泛问题单一查询必漏；[机制](docs/how-it-works.md#7-聚合读法侦探拼图与逆向冷回溯)）
- **逆向冷回溯**——想不起关键词时，从人物/地点/时间任何线索顺实体发散、沿时间邻居走、按时间窗浏览认领；禁止宣布「查不到」。（为什么：「查不到」三个字在记忆系统里等于撒谎——只是没找到，不是不存在；[机制](docs/how-it-works.md#7-聚合读法侦探拼图与逆向冷回溯)）

### 养：档案的自我维护

- **反馈回路**——被纠正/确认才记录，note 必须引用当时原话作证据；沉默、换话题不算信号。（为什么：防止模型给自己的作业打分；[细则](references/review-and-feedback-loops.md)）
- **季度权重复盘**——180 天未再确认的导入权重降为 0：保留、可检索、退出活跃地图，永不删除。（为什么：档案只增不减，权重会漂移；[细则](references/review-and-feedback-loops.md)）
- **语义审查 + 三态校验**——定期扫「摘要冒充原话」「假设悄悄转正」「归属张冠李戴」；结构校验输出 clean/warnings/failed。（[机制](docs/how-it-works.md#9-质量回路反馈复盘审查备份)）
- **快照备份与范围恢复**——「跑了 7 天且校验通过」才切快照；恢复分 code/data/all 三级，dry-run 默认。（为什么：这份档案真实丢过一次数据；[细则](references/maintenance-and-durability.md)）
- **可视化审计面板**——本地静态页，能沿 事件→实体→情境→原话 完整链路逐层点开核查。（[机制](docs/how-it-works.md#9-质量回路反馈复盘审查备份)）

## 上手

让智能体跑这一条命令即可装好（路径按你客户端的 skills 目录调整）：

```bash
git clone https://github.com/caix84476-netizen/personal-understanding.git \
    ~/.claude/skills/personal-understanding && \
cd ~/.claude/skills/personal-understanding && \
python scripts/init_archive.py && \
python scripts/install_mcp.py --auto
```

重启客户端，`personal_*` 工具上线，正常聊天即可——「我最近……」「记住一下……」「为什么我总是……」，它会自己接住。手动逐步教程（含验证清单、升级、卸载）：[docs/install.md](docs/install.md)。

需要 Python 3.10+，仅标准库，零 pip 依赖，Windows / macOS / Linux 都行。也能 `pip install personal-understanding` 装服务端，但完整的大脑（`SKILL.md` + 审计面板）建议用上面的 clone。

## 设计思路

为什么原话优先、为什么硬闸门、为什么诚实比召回率重要、以及每一版修了什么：[docs/why-it-works.md](docs/why-it-works.md)。一句话概括：**它不是设计出来的框架，是一份天天在用的档案被十几轮实测事故磨出来的**——分类器曾把「我堵得慌」锁在档案外、缺日期记录曾被时间衰减无声埋掉、整句口语查询曾被假切片霸榜，每一版修补都在 [CHANGELOG](CHANGELOG.md) 里有现场。

检索与词面层站在前人工作上（[逐个的取舍与实测结论](docs/why-it-works.md#4-借鉴与致谢)）：**SYNAPSE**（ACL 2026 Findings，扩散激活门控）、**HippoRAG**（NeurIPS 2024，个性化 PageRank 种子权重）、**Generative Agents**（Stanford，时间衰减）、**Qiao & Sun**（ACL Y09-2003，自训练词典）、**jieba**（MIT，中文分词）。

## 项目结构

```text
personal-understanding/
├── SKILL.md                 # 每轮操作契约：两档闸门、原话保真、派生闭环、三层检索
├── docs/                    # how-it-works（机制）· why-it-works（动机）· install（安装）
├── references/              # 14 份字段级政策文件（捕获/检索/时间线/实体/假设/审查/备份……）
├── scripts/                 # 全部实现，仅 Python 标准库
│   ├── mcp_server.py        # MCP 服务端（11 个 personal_* 工具）
│   ├── preflight_context.py · capture_user_update.py · finalize_capture.py · session_check.py
│   ├── catalog_context.py · retrieve_v2.py   # survey / probe / deep
│   ├── ppr.py · lexicon.py                   # 联想通道 / 词元净化
│   └── validate_memory.py · review_v2.py · salience_review.py · backup_archive.py
├── dashboard/               # 可视化审计面板（纯本地静态页）
├── templates/branches/      # 六大领域分支模板
├── resources/lexicon/       # jieba 词典（vendor，MIT）
├── tests/                   # 180+ 回归测试 + 验收卷
└── VERSION / CHANGELOG.md   # 版本与实测修补史
```

## 你的数据归你

全在本地、在这个文件夹里跑。无遥测、无云调用、无第三方 embedding 服务。`.gitignore` 默认挡住 `memory/`、`sources/`、`backups/`——你给这个目录做版本管理也绝不会误提交私人档案。

## 许可

[MIT](LICENSE) © 2026 caix84476-netizen
