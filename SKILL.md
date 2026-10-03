---
name: personal-understanding
version: 2.8.0
description: 两档调用。①完整档：当用户谈及自己的经历、状态、感受、家人朋友、学校、决定、长期偏好，或要求记住、纠正关于他本人的信息，或问"我为什么会这样"，包括抒发、闲聊和活动足迹类（游戏攻略、宿舍安置、在读在看）轮次——先以不可变原话保存，再沿"时间主干 survey → 实体/情境 probe → 原话 deep"渐进检索；纯足迹类轮次遵守"足迹纪律"（恰好一条微型记录）。②跳过档：纯技术、吃什么、一次性购物决策等零增值轮次完全不碰档案。默认用中文工作。
---

# 个人理解 v2.8（瘦身版核心契约）

本地、可追溯、原话优先、时间主干驱动的个人认知档案。本文只保留**每轮必须遵守的操作契约**；各领域细则已外置到 `references/*.md`（英文政策文件），本文给出索引，**按需加载，不要一次全读**。

档案布局：不可变会话原话在 `sources/conversation/`，v2 派生主干在 `memory/v2/`，旧版 `memory/records/` 为兼容层。

## 1. 两档调用闸门

**完整档（full，默认）**：消息含个人经历、状态、感受、关系、偏好、决定，或用户要求记住/纠正，或个人背景会实质改变建议、取舍、风险提示时，走完整流程。抒发、闲聊、自我陈述同档：档案价值是提供背景，不以"必须给建议"为前提。

**活动足迹轮次并入完整档**（游戏攻略、宿舍安置、在读在看、装备选型等消息本身不含实质个人材料、但可沉淀一条足迹者，如"只狼怎么打弦一郎"→"正在玩《只狼》"）：capture、读取、闭环一项不可少，另遵守**足迹纪律**：

1. **写入前定向查重（不可跳过）**：按足迹关键词 probe/routing，核对 (a) 是否已有覆盖同一足迹的 current 记录（有则沿版本链更新，不新建）；(b) 待写内容是否与既有事实或"不得把 A 写成 B"类状态告诫矛盾；
2. **恰好一条微型记录**：`tier=light`、salience 0–1，带 `capture_id` 回链；不拆多条、不生成假设或待回访、不把单次咨询升级成决定；
3. **零新增可体面收场**：查重确认完全覆盖时以 `no-derivation-needed` 关闭，reason 写明命中的具体记录；禁止为闭环制造噪声；
4. 查重翻出档案内部矛盾留证不断言；待写内容实为多条独立事实或需纠正既有记录时，按完整档正常拆分（同档位内派生深度变化）。

**跳过档（skip）**：纯技术（代码/配置/排障/MCP/仓库维护）、"今天吃什么"、一次性购物决策、无后效评价请求——完全不碰档案：不 receipt、不 capture、不派生、不存审计副本。护栏：内容分类检出个人材料的轮次不得用 `tier=skip` 压制；压制留痕于 receipt 的 `reasons_suppressed` 供审计。

**light 档已废除**：`preflight tier=light` 枚举仅兼容保留，一律按 full 处理。记录层 `tier=light` 微型标记保留，仅表示记录形态。

本 Skill 的边界规则维护对话不属于个人材料：直接改规则，不归档。客户端指令文件里的语气/工具偏好不捕获、不派生成个人事实。

## 2. 原话保真与派生闭环（最高优先级）

**只要消息含个人材料，必须先把完整原话一字不改保存，再做任何摘要、拆分、提取或解释。**

固定执行顺序：

```text
内容优先 preflight receipt（MCP personal_preflight_turn / scripts/preflight_context.py <完整消息> --turn-id <id>）
→ capture（personal_capture_user_turn / capture_user_update.py --turn-id <id>；SHA256 必须与 receipt 一致）
→ survey/probe/deep 检索
→ 派生记录（personal_add_record，必须带 capture_id 或 verbatim_refs；禁止裸 current-conversation）
→ finalize（personal_finalize_capture / finalize_capture.py；derived 须至少一条 capture↔record 双向链接，
   或 no-derivation-needed 写明具体查重理由）
→ session_check --turn-id <id>（回答/声称已更新前的硬闸门）
→ 回答
```

硬性规则：

1. 文字存完整消息，不截取"重要句子"；图片/音频/文件用 `scripts/capture_attachment.py` 保留原件并登记哈希，OCR/转写只是派生；精确重复附件复用原件但仍登记并以查重理由关闭；
2. 每份原话有 `utf8_sha256`、捕获时间、会话标识、来源路径；捕获一旦存在不得覆盖，纠正只能新增；模型摘要不得冒充原话，旧摘要记录标 `summary_only`；捕获失败必须如实报告，不得假装已存；
3. capture 成功 ≠ 档案更新完成：它进入 `memory/derivation-ledger.json` 的 `pending`，必须派生并 finalize 关闭。**仍有本轮 pending 时禁止声称"已录入"或结束答复**；捕获成功但尚无派生时，回答须区分"已存原话"与"尚未写入经历/状态卡"；
4. 一条原话含多个独立事件/人物/纠正/偏好/状态时逐项拆分，不用一张笼统摘要卡应付；每条 capture 逐条 finalize；
5. 历史材料的事件日期、材料写作日期、回忆日期、录入日期分开，禁止把录入当天冒充发生日；
6. `requires_personal_understanding=true` 的 receipt 缺 capture/finalize/session_check 任一项即 fail closed；捕获失败时停止个人理解分析并报告，不得先回答再补录；
7. 本闸门同样适用于把个人材料包在改写/润色/翻译/总结/看图任务里的消息——任务外形不能覆盖个人材料；也适用于直接提及档案/记忆/"记住"的消息；
8. 写入工具的 isError 只回答"本次写入是否落位"（2.7.0）：收到 isError=true 按拒绝理由修正重试；不要因收尾并发警告盲重试已成功写入（重复 id 会被拒）；锁等待超时是干净的可重试拒绝，不是服务崩溃。

### 内容分类器与模型兜底

分类器是关键词启发式：第一人称+标记词触发；**强情感词无"我"字也召回**（"有点烦""挺焦虑的"）；技术语境（python/代码/配置/报错等词）否决强情感词触发。词表枚举不尽——**兜底责任在模型**：判断为个人材料就在同一 turn-id 上重声明 `--tier full`（同 id 升级即时生效）。判错方向宁可多 capture（no-derivation 收场无成本）也不要漏 capture（原话永久丢失）。

## 3. 低信号快速通道（完整档内部）

低信息量个人消息（"有点迷茫""唉"）：

1. **capture 立即执行，无例外**；
2. 读取降级：不跑完整 survey，直接用 preflight 输出的到期回访 + 当前状态快照挑一个入口，必要时一次小范围 probe；
3. 回答优先：像熟人聊天，工具调用控制在 capture + 至多一次轻读取；
4. 同轮内 finalize + session_check 收尾；用户连续追问转实质内容则升级完整流程。

放宽的是读取/派生时序，绝不放宽捕获与闭环本身。

## 4. 事实层级与记忆权重

层级：①用户原话事实 → ②用户对材料的评价 → ③用户自己的解释（保留为用户观点）→ ④模型候选解释（单独放假设层）→ ⑤无法确认（留来源和缺口，不凭空补全）。新内容优先于旧档案；旧事实不静默擦除，建 `supersedes`/`contradicts` 纠正链。

权重唯一轴 `salience` 0–3：`3 主轴`（改变长期理解/多领域/人生方向）、`2 关键`（改变某条生活线/当前决定/关系过程）、`1 关联`（背景/连接/反例）、`0 提及`。`entry_kind` 表示是什么，与权重是两回事；不再另设第二套分类。迁移权重标 `imported heuristic`，不伪装成用户评定。

## 5. 档案建模要点（写档案时必读）

- **时间主干**：每条留 `date_start/date_end/date_precision/date_basis/phase/salience/entity_refs/before_ids/after_ids` 与原话片段保真度。日期不确定就写不确定，禁止为好看造日期、禁止把记录创建日期当事件日期。
- **总览结构**：事件优先、体验跟随、当前状态单独叠加——人生主干（主轴/关键事件）→ 事件展开（发生/感受/解释/影响）→ 当前状态快照 → 证据入口。
- **实体档案**：类型含 person/group/school_or_organization/place/object/book_or_work/game_or_media/concept/environment。事实只存一份（原话与事件是 canonical source），实体页是投影；**实体正文不写可变状态**（拥有/在读/已购这类断言放挂靠 `state` 记录走版本链，否则制造永不更新的僵尸信息）；交叉连接不删除；路人档案可只有几句话，身份能从上下文确定就建短档案。
- **模糊代词**：上下文无法确定指向时不造假人物、不写"未确认实体"垃圾节点；原话挂事件的 `unresolved_referent`，等明确后补正式档案。
- **情境卡（facet）**：解决"学校 × 足球"式交叉——卡片放共同事件/人物/原话入口，不复制假故事；边界按共同故事（同事件共现、明确关系/空间连接、共同体验/决定）；偶然共现不写因果，也不因"跨领域"删除。
- **当前状态五块**：个人内核 / 现实处境 / 体验负荷 / 开放张力 / 下一检查点，每块 1–3 个高密度条目附可展开事例与原话。
- **因果假设**：独立工程，字段 `claim/mechanism/supports/contradicts/alternatives/scope/confidence/status:candidate`。触发：用户问"为什么我会这样"、多条独立经历跨时间重复同一条件—反应—适应链、当前决定需比较成因。单次事件不生成稳定因果；普通事实问题不自动加载假设。

细则索引（写对应内容时加载）：`references/entity-and-context-policy.md`、`timeline-and-followup-policy.md`、`causal-hypothesis-policy.md`、`conflict-and-correction-policy.md`、`decision-policy.md`、`evaluation-policy.md`、`self-distillation-policy.md`。

## 6. 待回访

模型提出的问题、"等几天看结果"、对方未回复、待确认事项 → `memory/v2/followups.jsonl`（MCP `personal_add_followup`），至少含：原问题、具体上下文、创建日期、`due_at`（合法日历日期；相对说法换算成具体日期，不想定死就只写 `due_rule`）、状态、来源。

每次运行 Skill 先查到期与临近（默认 3 天窗口）回访；到期主动提问且必须带上下文（"你在某日提到…当时约定…现在到检查时间了，后来怎么样？"）。关闭三分支（MCP `personal_resolve_followup` / `followup_check.py --resolve`）：`answered`（用户回复了）/`declined`（明确不再跟进）/`resolved`（被取代或过时），`note` 必填写具体依据；用户回答本身是新原话时先 capture 再把 `capture_id` 传给 resolve。被取代的回访不关闭会持续污染到期清单。

发现当前消息与档案矛盾时，列出冲突两条事实、日期、来源、差异再询问；禁止没头没尾突然追问。

## 7. 引导开场（用户不知讲什么时）

运行 `python scripts/conversation_starters.py`（JSON），挑**一条**（到期回访优先，其次最空领域）用自己的话温暖地问。绝不整张清单一次抛出；建议必须来自档案真实空缺，绝不编造心理学判断。

**"档案里没有 X"是需要证据的断言**：说出口之前必须先对 X 做定向 probe（用 X 的话题关键词，不是别人起的标题原句），probe 空手才许出口。档案标题、目录、直觉印象都不算证据。用户回答后回归正常流程：捕获 → 派生 → 回答。

## 8. 检索：三层发散，不把全库塞进模型

**survey**（`personal_catalog --view survey`，48K 预算）：紧凑路由地图——时间主干、当前状态、实体/情境卡/假设目录、待回访、资料缺口。不含旧记录全量列表；按领域展开用 `--view routing --query`，完整目录用 `--view full`。因果假设默认只带 id/status/confidence 存根，当轮消息内容词真实命中假设文本才带出全文；用户求解释且存根看着相关时，主动 `--view full` 或把用户因果措辞放进 `--query`。

**probe**（`personal_retrieve`，80K 预算）：选入口（事件/实体/情境卡/当前状态/待回访/假设）读派生卡片并扩展——时间邻居、涉及的实体、共同情境卡、支持/反驳/替代/supersede 关系。每条时间条目带 `evidence_fidelity` 保真计数；用摘要债务支撑的说法要向用户说明"这段来自旧摘要，不是原话"。检索决策轨迹存 `memory/v2/traces/` 供回放。

**deep**（100K 预算）：只在需要精确事实、时间、归属、矛盾、人物关系、原意或因果解释时读对应原话片段；旧摘要在 deep 阶段不能伪装成原文。

**associations（联想通道）**：probe 输出里的独立段，个性化 PageRank 沿档案图扩散（种子=本轮查询命中的实体/概念卡），带出词面零重叠候选。契约：它是候选池不是排序结果，模型自己判断联想成立才引用；绝不混入 timeline；概念卡（`entity.concept.*`，aliases 覆盖口语入口词如"书荒""晕3D""考公""史低"）是它的地基，新概念出现时按实体卡流程开卡挂链；宽泛兴趣问题实体零命中时经概念卡 aliases 自动获种子。

**聚合读法（侦探拼图）**：宽泛决策问题（"我该怎么办""我是个什么样的人"）拆 2–4 个 probe（情绪线/利益线/人物线各一发，用该线足迹关键词），跨域收集各线前排 + associations 强候选 + entities 段命中的概念/实体卡，再对直接相关记录用 `ids` 精读核原话。回答区分"档案事实/模式观察/模型推断"三层，推断注明依据哪几条记录；禁止把单次事件升格为人格定论。

**工具与模型分工**：工具负责把召回体力活做厚（候选捞全、宁滥勿漏），判断与拍板永远在模型。模型**必须自己提关键词再 probe**（整句直查只在 routing/时间窗场景合法）；不必替工具干活（不手工过滤假切片、不重算 IDF——发现问题报维护轮修机制）；前排有噪声不静默吞下，按 trace 说明"为什么出现、为什么不采信"。

**冷回溯**（用户"想不起关键词"）：从已提到的任何人物/地点/物品/时间线索 probe 顺实体发散 → 命中后沿 `before_ids/after_ids` 时间邻居走 → 仍无命中用 `retrieve_v2.py --window 2025-03`（或 `起:止`）按时间窗浏览标题让用户认领 → 时间也说不准按 phase 逐段扫主轴。禁止宣布"查不到"。

读取入口与闸门：MCP 工具优先，带读取前捕获校验。五类读取尺寸预算 survey 48K / routing 68K / full 96K / probe 80K / deep 100K，超预算确定性截断附 truncated 元数据。足迹/攻略类消息被 capture 闸门拦下时可用 `maintenance: true` 只读降级（有 trace 审计），但仍应按足迹纪律同轮 `tier=full` 重声明补 capture——只读通道解决"读不到"，不免捕获。会话里没有 `personal_*` 工具说明 MCP 未注册：运行 `python scripts/install_mcp.py --auto`（幂等）后提示重启；多份 skill 树并存时受防劫持护栏约束，切换须显式 `--force`。

检索机制细则（排序配方、词元净化、锚定降权、PPR 参数）见 `references/retrieval-policy.md` 与 `references/retrieval-decision-trace.md`，维护轮或排查漏召回时加载。

## 9. 隐私边界

用户已允许本地 Skill 在相关时读取 private/highly-private 内容，敏感度不作隐藏/降级/归档理由。相关性过滤保留：会改变答案才读敏感内容；无关问题不主动泄露无关私密材料；原话与档案只在本地 Skill 目录处理；外部聊天、第三方分析、OCR、模型分析不自动当用户事实。放宽隐私读取 ≠ 把档案倒进每个回答。

## 10. 校验、审查与维护

`personal_validate` / `scripts/validate_memory.py` 三态：`clean` / `warnings`（摘要债务、来源/日期缺口、待回访、实体连接问题）/ `failed`（哈希错、重复 ID、孤立引用、关系环、损坏 JSONL）；`--strict` 警告即失败，适合迁移验收。`--require-closed-captures` 阻止孤立/未跟踪/未闭环捕获混入完成态。

`review_v2.py --deep --json` 语义审查：原话与事件一致性、归属正确性、共同故事误删、时间顺序混淆、事实/感受/解释/假设混层、旧摘要冒充原话、假设证据缺口、回访到期。深度审查可输出警告与缺口，不能凭空补写丢失原话。

维护入口（CLI 与 MCP 等价）：`capture_user_update.py`（超长消息用 `--stdin`/`--file`）、`preflight_context.py`/`turn_receipts.py`、`capture_attachment.py`、`derivation_ledger.py`（`--repair` 重建投影）、`finalize_capture.py`、`catalog_context.py`、`retrieve_v2.py`、`followup_check.py`、`review_v2.py`、`validate_memory.py`、`session_check.py`（缺省 turn-id 自动审计最近 receipt，不能靠不传参绕过；exit 2=有警告"可用但须如实报告"；`--stale-days` 默认 7 把历史遗留 pending 降级为警告，近期 pending 依旧硬拦）、`salience_review.py`（季度权重复盘）、`record_feedback.py`（回答效果反馈）、`rebuild_views.py`（重建视图+档案自训练词表）、`pipeline_view.py`（一轮管线时间线回放）、`backup_archive.py`（带 SHA256 清单的备份+镜像；重要更新后、迁移前、至少每周一次）、`init_archive.py`（新装初始化）、`install_mcp.py`（注册 MCP）、`mcp_server.py`。CLI 读取同样遵守"先捕获再读"（需 `--capture-id`；维护/测试/审计读取显式 `--maintenance`）。

**弃用兼容层（勿作读取入口）**：`query_context.py`、`retrieve_context.py`（旧结构，仅回归调试保留）；`references/proactive-cues.json` 英文触发词默认关闭，重新启用须先翻译中文。`review_context.py` 不是这层——review_skill 活依赖，别误删。

维护原则：先完成当前任务再做非紧急维护；但用户纠正、捕获失败、归属错误、结构损坏、回访到期、临近决策必须及时处理；preflight/session_check 输出的 `maintenance` 提醒是唯一需看的维护状态——`backup.due: true` 时任务完成后先跑 `backup_archive.py` 再结束会话；依赖个人记忆的回答被用户明确纠正/确认时按 `references/review-and-feedback-loops.md` 记 `personal_add_feedback`（写不出原话证据就不记录）。永久删除须用户明确指定；旧摘要标迁移债务不删除；新档案用版本链不覆盖；所有 writer 共享进程间锁、原子 replace 落盘，写入一律在锁内基于最新磁盘快照读-改-提交，禁止从旧快照覆盖其他进程已写入的数据。

**时间落点硬规则**：任何"用户当前处于某阶段/地点/状态"的断言，输出前必须拿当前日期与档案覆盖该日期的时间记录显式对照；对不上就只能问或说不知道。推断顺序永远"先对日期，再讲故事"；supersedes 链说明某断言被纠正过时，同一断言复发即红线。不把一句自我评价升级成人格定论；不为图谱好看制造因果边、合并人物或填补时间。

## 11. 可视化审计契约

面板（`dashboard/`）让用户检查 Skill 是否按规则工作：首页只给状态/数量入口；诊断页能看到 SKILL.md、references、scripts、memory/v2 真实文件入口，各环节实际数量，clean/warnings/failed 机器校验结果，摘要债务/日期缺口/归并/未解析/假设缺口，以及事件→实体→情境→知识卡→前后条目→原话来源的完整链路。任何列表点击用自己的 ID，禁止多条目绑同一默认目标；实体重定向显示旧 ID、canonical ID、归并来源。
