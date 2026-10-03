# Changelog

## 2.8.0 — 2026-09-28 — 瘦身轮：宿主上下文开销减半，行为契约不变

针对 pi 等宿主的常驻/调用开销做结构性瘦身，不改变任何档案语义与闸门逻辑。

- **SKILL.md 44.1KB → 20.0KB（-55%）**：只保留每轮必须遵守的操作契约（两档闸门、原话保真、派生闭环、足迹纪律、低信号快速通道、检索三层、回访、校验维护）；领域细则索引到 `references/*.md` 按需加载。删除叙事性事故复盘与逐版批注，硬规则全部保留。
- **MCP 工具 13 → 11**：`personal_derivation_status` 并入 `personal_validate`（`derivation` 段内嵌台账审计，默认开）；`personal_add_hypothesis` 并入 `personal_add_record`（`kind=causal_hypothesis` 伪 kind 路由到 hypotheses.jsonl 写入路径，不进 VALID_KINDS 防 md 记录路径误收；summary 契约 `claim || mechanism`）。两个旧名保留迁移期指针（isError 提示新调用方式），一个发布周期后删除。全部工具 description 砍到一行，规则叙述回归 SKILL.md 单一事实源。
- **session_check 默认 light 模式（--light / MCP light=true 默认）**：本轮 turn 闸门 + pending 台账 + 回访调度，跳过 validate_memory 全库子进程——收尾从秒级降到毫秒级；`light=false` 恢复完整闸门供维护轮/迁移验收。gate_version 2.2.0，输出带 mode 字段。
- 测试同步：版本五方钉（SKILL/VERSION/pyproject/README×2/CHANGELOG）更新；被合并工具名的两个套件断言改为新面 + 迁移指针行为断言。

## 2.7.0 — 2026-09-26 — 诚实与规模轮：写入错误信号、读取尺寸预算、闸门治理，全部换新试卷验收

接班自 16 项实测问题报告（3 项硬伤），按批准的 A–I 分组根治；防过拟合三律全程执行（修复常量不对单条查询调、冻结套件只作回归地板、验收换全新试卷 t10–t16）。

- **A 写入链路重构（mcp_server.py / storage.py / view_freshness.py 新建）**：写入只做轻量落位校验决定 isError——"isError 恰好回答一件事：本次写入是否落位"。旧实现每写一次内联全量重建（实测 ~6.4s/次）并让收尾 validate 竞态并发写者，把成功写入报成失败、诱发盲重试与重复 id。视图改为 mtime 脏检测 + 读时重建（view_freshness.py，故意不用脏标志文件——mtime 不会与磁盘事实分歧，崩溃不留悬空标志）；锁 30s→120s + 指数退避；TimeoutError 从协议错误（-32603）改为干净可重试拒绝。实测：6 并发全周期 3.1s，record 写入最长 1.86s。
- **B 台账/闸门（derivation_ledger.py / session_check.py / validate_memory.py）**：finalize 的 pending 提示死代码修复（旧代码对 run_script 的字符串输出调 .get()，永远空）；已闭环 capture 同状态幂等重入（already_closed）、异状态改判拒绝（翻转即洗白通道）；session_check 缺省 turn_id 自动审计最近 receipt（不再静默跳过 turn 闸门）、exit 2（警告）不再映射 isError、`--stale-days`（默认 7）把历史遗留 pending/receipt 降级为可见警告。
- **C 校验统一 + 原子性（schema.py 新建 / v2_archive.py / record_feedback.py）**：schema.py 成为 branch id/日历日期/枚举的单一事实源，add_record 写入前校验与 validate_memory 完全对齐（未知 domain 拒绝并列出合法 branch id、salience 0-3、"learning" 类写入即废 kind 拒绝、非日历日期拒绝）；verbatim_refs 先预检再写文件（伪引用不再留下孤儿记录）；followup 伪 due_at（"下个月吧"）、hypothesis 枚举外 confidence、feedback 伪 capture 全部服务端拒绝。
- **D 检索评分三缺陷（catalog_utils.py / lexicon.py / retrieve_v2.py / ppr.py）**：档案漂移暴露而非代码回归（差分诊断定案）。①嵌套 n-gram 三重计分改最大咬合 span；②自训练词表自污染加边界认证（jieba 单词或两个 ≥2 字词典词的复合）；③recency 越权乘了整个 event_value 改为只乘词面 + 实体聚焦先验（boost × (2/len(entity_refs))^k，PU_ENTITY_FOCUS 可关）；§4b 承诺的联想通道职责补完（零词面支持的实体反馈行按 timeline 序作为 preferred 传给 ppr）。v12 全套 26/26，h16 双断言（timeline rank 5 + associations 在场）真实档案实测通过。
- **E 分类器（turn_receipts.py）**：裸"烦"改多字形态（"麻烦/这样有点麻烦"不再误触，冻结金标"挺烦/有点烦"保留）；补失落/迷茫/后怕/悬系（好悬/很悬/有点悬/提心吊胆）漏判词；第一人称弱标记（觉得/决定类）加技术语境否决，强情绪词不受否决。
- **F 尺寸预算（catalog_context.py / retrieve_v2.py）**：五类读取全部带字符预算与确定性截断（survey 48K / routing 68K / full 96K / probe 80K / deep 100K，按实测 floor 校准而非硬凑——原 64K 目标低于诚实 floor，会截断每次读取让元数据失义）；超预算输出保持合法 JSON 并附 budget.truncated/omitted 元数据；probe 结构上限收紧（facets 20→10、entities 12→8、knowledge 10→8、fragments 16→10），facet 卡/实体卡/current_state 字段级裁剪；fit_budget 收缩计划加最终档，收缩循环可迭代到底。
- **G CLI 修补（pipeline_view.py / update_state.py）**：pipeline_view 传 capture id 也渲染整回合管线（旧实现只渲染单个 capture，多 capture 回合的兄弟捕获不可见），`--latest` 落 HTML 索引；update_state 对 capture id 形态的 source（含 fragment.capture.* 前缀形态）自动解析为真实 source_path。
- **H 本体修复（唯一动真实档案处，有备份有证据）**：capture.turn.b31babda… 的 link-drift 根因是同一晚 update_state 双跑留下的两份时间戳副本（均自称 current、正文均自述"现行版本见 …b"）。diff 确认 → fresh stable 备份（SHA 验证）→ 两副本 frontmatter 追认 archived（文件保留）→ `derivation_ledger.py --repair` → 审计清零（capture-record-link-drift 0 条，ledger 如实记录历史派生），b 记录在 timeline、归档副本退出投影。
- **新试卷 t10–t16（验收层，全部通过）**：t10 并发错误信号、t11 视图预算+写入后免手动重建、t12 finalize 护栏、t13 记录 schema 与零孤儿、t14 分类器全新句子矩阵（17 句）、t15 会话闸门二卷、t16 检索二卷（5 条全新查询 + h16 回归点）。**验收过程抓出并修掉三个真缺陷**：①view_freshness 双检锁包住重建子进程 = 跨进程死锁（父持锁等子、子等锁，写入后第一次 MCP 读取必然 120s 超时）——外层放锁、由子进程自持锁；②`if args.get("stale_days")` 把合法的 0 当 falsy 吞掉——改为 `is not None`；③validate_memory `--require-closed-captures` 无龄期概念，结构闸门把 session_check 的降级短路——validate 补 `--stale-days` 透传（老遗留保持 warning，新 pending 依旧硬拦）。
- **回归**：作者冻结套件 182/182（test_v03/v05 的 spine≥50 断言按"可观主干+诚实截断元数据"意图改写并注明理由；test_v08 加活档案 pending 环境前提跳过——真实 pending 出现在验收期间属闸门正确行为；test_v09 提醒在场断言与退出码正交化）；旧试卷 t01–t09 重跑通过（两处夹具适配：t04/t04b 的非 branch domain "learning" 升级为合法 branch id——恰是旧"写入即废"病灶的原始案例；t08 完整性检查改走 MCP validate 真实路径）。
- **诚实边界**：probe/deep 预算上浮到 80K/100K 是"floor 可达 + 元数据诚实"的代价——结构上限已收紧，剩余体积主要是 12 条 timeline 卡、current_state 与 trace 的真实信息量；冻结金标 h16 在默认预算下零截断。


## 2.6.1 — 2026-09-06 — 泛化审计轮：召回/排序/分类三处修复，全部先测后改

接班自验轮（用户铁律：不闭门造车、具体问题具体分析地借鉴前人、每步防过拟合三律）。全部改动沙盒实测后移植，评测底座为自动派生的集合（LongMemEval 式题型矩阵 IE/MR/TR/KU/ABS + 时间一致性金标 + 精确召回回归网，harness 与工作区镜像 parity 5/5）。

- **§4b 联想通道修复（ppr.py + retrieve_v2.py，commit 8a4728b）**：口语↔规范摘要零词面重叠的记录两头不靠问题修通——①assoc 自我屏蔽（仅实体反馈进 timeline 的记录不再因"已选中"被踢出 associations，`_lexically_supported()` 门控）；②投影预算双重花费（records_of 新增 taken 集合在切片前剔除）；③同分并列改"声明序>salience>相关性>日期新先>id"；④删除 Tier1 外层 re-sort（它冲掉了 main 刚加的 relevance 键）。h16 目标记录从两头不靠到 timeline 第2 + associations 第3 带可审计 seed:father 路径。交接档案 g06"失眠漏召回"证伪：全档案无"失眠"，属空手场景非检索缺陷。
- **§4c Generative-Agents 时间相关性（catalog_utils.recency_factor，commit ceb02ea）**：词面 event_value ×0.5^(age/180d)。自动派生 31 例时间金标违反率 0.419→0.161，精确召回网 0.617→0.617 不动；**缺日期记录中性 1.0**（9% 事件无 date_start，按"极旧"会无声埋正确记录——实测踩出）。同轮实验否决两条：SYNAPSE 激活级时间衰减在本架构（rank 仅驱动种子序）结构性无效；HippoRAG 收敛 PPR 与现状局部扩散 top30 重合 0.64 但成对判据一致——均维持现状。
- **§4d 分类器结构修复（turn_receipts.py，commit 917bbaa）**：交接归因"词表法到头"实为 `elif not first` 结构门把 STRONG_MARKERS 对第一人称情感句锁死（"我堵得慌/我社死了/我诸事不顺"两头落空）。拆门 + 窄形态槽（X得慌框架，排除饿/渴/撑身体需求与"好难"泛化误触）。冻结金标捕获率 0.438→1.000、零新增误触、基线→修复 diff 恰 13 条全是应抓。SKILL.md 低信号段据实重写。
- **§4f 知识更新契约修复（retrieve_v2.py STATUS_DEMOTE=0.5，commit bd7d977）**：LongMemEval 式题型矩阵发现——版本化事实的 superseded 旧行可盖过 current 新行（"录取结果"里 0721 压在 0722 上）。软降权不过滤（行仍可见、带 status 供模型讲版本链，只动顺序）。矩阵 KU 15/17→17/17，其余四型（IE/MR/TR/ABS）一项不动——无代价增益。
- **概念卡扩充（§4a 结构审计）**：新增 emotional-writing（写作=情绪出口）、autonomy/dignity 转正式卡补口语别名、family-boundary 扩挂 5 条孤儿；salience≥3 孤儿 33→23。卡片措辞设计规则入档：aliases/正文避开"的事"类结构尾巴词（IDF 虚高会劫持联想种子）。PMI 词表内聚过滤（新词发现经典法）经行为实验否决并留档——种子走 content_hit 不经词表，砍 40% 词表零金标收益。
- **SKILL.md**：聚合读法第2步补"entities 段命中卡也算跨域信号"（P5 端到端考研场景实测：决策卡经 entities 首位可达，照字面读前三段会漏）。
- 测试 173→182（recency_factor 单测×4、时间一致性/h16/KU 集成×3、分类器结构×2）。诚实边界不变：associations 是候选池不是排序结果，判分由模型做。

## 2.6.0 — 2026-09-05 — 联想检索与档案词表：让"词面零重叠"的回忆变得可达

承接 2026-09-05 深夜与用户的演进讨论（"回忆 ≠ 语义相似：反面与精神内核相似物打分为 0 就不可见"），全部改动先在沙盒实测、再落库；新增三层能力与一次闸门放宽。

- **词元净化层（scripts/lexicon.py + resources/lexicon/）**：vendor jieba 词典（MIT，fxsjy/jieba，34.9 万词条）+ 档案自训练词表（`memory/v2/archive-lexicon.json`：档案文本 DF≥2 的 2-4 字字段 + 全部实体卡 label/aliases，rebuild_views 自动刷新）。三类修复均有实测根因：① ASCII 单字符（"巫师3"拆出的"3"）不再具备内容词资格——记录 id/日期里的"3"曾让驾照记录在巫师3查询拿 timeline 第 1；② 中英混写专名自动粘连成整词（"巫师3""晕3D"），CJK/ASCII 边界不再切碎最强锚定；③ 词典外切片权重 ×0.4 封顶——保留召回（唯一命中仍前排、排序是相对的）但不再当锚定词，跨词假切片（"郎我""卡了"）失去虚高 IDF。设计教训已写进代码注释与测试：第一版"直接删除 OOV 切片"立即回归 T02（"弦一郎"档案仅出现 1 次、任何 DF 门槛都救不了它），改为降权后零误杀。`known()` 的判定含档案自训练词表——档案自身就是最懂自己专名的词典（用户 5.6b 提案）。
- **联想检索通道（scripts/ppr.py + retrieve_v2 `associations` 段）**：个性化 PageRank 在档案图上扩散（种子 = 查询命中的实体/概念卡；4 次迭代的局部扩散——收敛式 PPR 会让 ai-agi/home 这类 50-68 mention 的枢纽把"联想"变成"热度榜"；非种子邻居 mention_count≤30 封顶）。两级候选：种子实体投影（图距离 1 的自有记录，按 salience 排序——"打击感烂"经概念卡直达"巫师3 骑马手感"记录，词面零重叠）+ 图扩散邻居。输出独立 `associations` 段，每条带 `via_entity` 路径与 `spread_score`，绝不混入 timeline、绝不自行构成入选资格——词面管精确回忆、图管发散，证据链可见可审计。
- **概念卡层（实体 55→63）**：PPR 需要抽象层节点才能产生"精神内核"联想——第一版无概念卡的实测是共现随机游走（"打击感"查询联想出足球装备边界）。新增 8 张概念卡（操作手感/叙事体验/品味锚点/金钱自主/消费纪律/家庭边界/考公路径/身体限制）+ 《百年孤独》正式实体卡；aliases 覆盖口语入口词（"书荒""晕3D""考公""史低""打击感"）。实测："书荒了，整本来嚼嚼"——此前三通道全灭——现经 concept.reading-taste 带出阅读史与开放清单。"打击感跟纸糊的一样"→ witcher3-feel 记录 via concept.gameplay-feel。
- **足迹轮只读降级（MCP `maintenance` 参数）**：实测发现 fail-closed 链（足迹消息判 non-personal → capture 拒写 → retrieve 拒读）把攻略/书荒类轮次彻底锁在档案之外，连读都不行。`personal_retrieve`/`personal_catalog` 现接受 `maintenance: true`（等价 CLI `--maintenance`，trace 审计）做只读降级；写入闸门分毫未动，SKILL 指引模型随后仍按足迹纪律 tier=full 重声明补 capture。
- **管线时间线（scripts/pipeline_view.py）**：一轮对话的一生——receipt 判档理由 → capture 哈希 → 派生闭环 → 检索轨迹（query/scoring/选中/联想/停用）一页只读回放（`--turn-id X` / `--latest N`，HTML 到 dashboard/）。可视化第一步，同时是验收工具：足迹纪律、闭环完整性、检索捞偏都能在此回放。
- 测试 171→173 全绿（新增 OOV 降权契约、混合专名存活、tools/list 健康检查连带修复 MCP schema 的 Python `False` 字面量笔误）；`retrieval_version` 升为 2.6.0。诚实边界不变：probe 契约输入仍是足迹关键词；associations 是候选池不是排序结果，引用前模型必须自行判断联想是否成立。


## 2.5.1 — 2026-09-05 — 门面卫生补丁（无检索/写入行为变更）

- README 双语：包文件计数彻底解钉（2.5.0 时英文钉 38、中文漏改还挂着过时的 37），统一为“每次发布逐字节校验”的版本无关表述。
- scripts/hot_mirror.py：移除三处机器硬编码的绝对用户路径（随公开 wheel 分发），改为 home 派生默认值 + PU_SKILLS_DIR / PU_HOT_MIRROR_DIR / PU_HOT_MIRROR_LOG 环境变量覆盖；本机行为不变。
- mcp_test.py：修复对现行 preflight 返回结构（turn_receipt 嵌套）的解析——原驱动按顶层 turn_id 取值，第 43 行 KeyError，公开仓库里的验收驱动已与被测 schema 脱节。
- peek.py：与验收工作区副本同步（自动注入 --maintenance），评分不再依赖当轮 capture。
- 测试 171 全绿；wheel 与源码逐字节一致性在构建时复验。


## 2.5.0 — 2026-09-05 — audit-repair release: retrieval honesty, write integrity, ops hardening

承接 2.4.1 质量审计交接文档的全量修复轮：交接文档列出的问题全部修复，另经交叉审计新挖并修复约 10 项（下文标"新发现"）。

- 检索召回（§4.1/§4.2/§5.2 + 新发现）：单字实体别名（妈/她）豁免 ×0.15 噪音降权，实体→事件反哺在口语查询上真正接通（T06"妈 转钱"核心事件 16→7）；新增 `content_terms` 名额门槛——只被非别名单字偶然命中的记录不再占检索名额（T02"只狼"的 5 条误拉清零，无匹配玩法记录时 timeline 诚实为空）；`STOP_TERMS` 堵闭类疑问词（怎么/什么）被 IDF 误当稀有专有词（新发现）；trace 标签 `weighted-idf-3-stopcontent`；deep 读取时被显式核验记录的自有片段优先于邻居 verbatim（§5.2）。实体状态大迁移（§5.1）：实体正文只留稳定身份，可变状态归 state/decision 记录，sekiro 僵尸断言清除。
- 写入一致性（§5/§6.1/§6.2/§6.9/§6.10）：MCP 写工具不再在 capture pending 的正常中间态误报 isError（消除"写成功也报错→重试→重复建档"）；`repair_ledger` 信任规则重写——附件 ledger-only 链接保留、文本 capture 以 frontmatter 为准清陈旧声明（真实档案 8 条漂移清零）、no-derivation 处置不被 source_path 共现翻转，三向测试；`update_state` 版本链开放 decision（兑现"旧决定只做版本链"）；validate 与 v2 层的 verbatim 债务指标统一 `split_ids`（§6.9 真相是漏计 34 条的 bug，非"两个指标"）。
- 回访与预检（§6.3/§8/§8.1 + 新发现）：回访正规关闭通道 `resolve_followup`（answered/declined/resolved + 具体 note，MCP `personal_resolve_followup` + CLI `--resolve`），过时回访不再赖着；tier 同 turn-id 重声明即时升级生效、降级拒绝（§8.1 假 receipt 修复）；分类器强情感词独立触发（省略主语的抒发轮次）+ 技术语境否决（§8）；preflight 补上文档承诺却从未存在的当前状态快照，CLI/MCP 双路径兑现低信号快通道（新发现）。
- 耐久运维（§6.4/§6.5/§6.6 + 新发现）：`backup_archive --no-cloud`（沙盒残留真实 remote 不再覆盖真备份）；CLI 读取 capture 闸门与 MCP 对齐（`--capture-id` 校验存在性或显式 `--maintenance`，内部工具经共享 helper 自动带钥匙）；`install_mcp` 防劫持护栏——旧注册树仍在磁盘即判定为副本劫持并拒绝改注册（`--force` 覆盖），§1.2 事故制度化修复。
- 审计可见性与兼容层（§6.7/§6.8 + 新发现）：对话开场模板中文化；legacy `query_context`/`retrieve_context` 标 DEPRECATED 并写入 SKILL 维护清单（`review_context` 澄清为活依赖）；悬空实体引用显形（`entity_refs_for` 曾静默丢弃→orphan 审计永不触发，现投影 `unresolved_referents` 发 `entity-ref-dangling`，真实档案 7 处清零，SKILL 承诺的 `unresolved_referent` 死字段接通）；`review_v2 --deep` 新增薄证据假设、无 capture 锚点反馈两条审计警告（提示不拦停，守行为约束）。
- 文档与测试：references 与实现对齐（fidelity 三级现实/第四态归属/文件清单/trace schema 拆分并删自动关联承诺）；`restore_stable` 补 4 项测试（此前零锁死）；测试 113→150，各修复带回归锁；版本同步测试扩面到 README×2 + CHANGELOG 顶部，堵"只 pin 前四处"漂移盲区（新发现）。
- 发布前验收轮遗留修复（上一班 §4 清单的三个 [中] 项，发布前就地修掉）：① 因果假设按需携带——政策承诺"普通事实问题不自动加载"而 retrieve_v2/catalog 每次全量带 claim，现共享闸门 `select_hypotheses`（内容词命中才携带、上限 6、目录层降级为无 claim 存根、`--view full` 作为显式完整读取绕闸），SKILL 补"求解释时主动读完整假设"的模型指引；② add_followup 缺 source_refs/到期规则时返回值附提醒（不拒收，守行为约束），review_v2 新增 `followup-without-source-or-rule` 审计警告（只盯 open 条目）；③ `resolve_followup` 可选 `capture_id` 绑定用户回答原话（须存在于 ledger，假 id 拒绝），MCP schema 与 CLI `--capture-id` 双路接通。
- 验收轮新发现并修复——锚定比值降权（scoring 升为 `weighted-idf-4-anchor`）：按矩阵原句（整句口语）重跑 18 轮回测发现，长句切出的意外 n-gram（"郎我""卡了"这类跨词切片）在 427 条量级的语料上 df≈0-1、拿满 IDF（log(1+N/1)），信号倒置——真决定词"只狼"（df=4）权重反而低于噪音切片，无关长记录靠"小时+阶段"两个词就能霸占 timeline 前排（T02/T13 实测）。修复：事件与知识卡得分乘以"该记录命中的最强词重 ÷ 查询最强词重"（实体分与实体反哺 boost 不降——实体命中本身就是查询点名的锚），route_catalog 查重排序同步接入；实测零回归、T08 知识卡 2→1、T16 职业路线 11→5、T12 哥哥冲突 13→9。已验证并放弃的方案：句形自适应低 df 降权（0.35×）——把青旅/拿刀等真金决定词与彩票词一起误伤，T14 青旅住宿记录掉出前排，回退。诚实边界写入 SKILL 双语：probe 契约输入是足迹关键词，整句原话直查的噪音地板（n-gram 无分词的固有极限）无法在检索层根除，模型侧先提关键词再 probe。

## 2.4.1 — 2026-09-04 — retrieval recall fix: weighted ranking for probe and routing

- 检索召回质量修复（2026-09-03 实测三类故障：漏召回、捞偏、弱相关噪音）。根因定位：probe 的 `score()` 是等权词计数，`query_terms` 生成的单字（在/一/人/看…）能命中 60%–70% 的记录，长记录靠单字堆分霸榜；实体选择存在名额 bug——被选中事件挂的实体先塞满 `max_entities` 名额，把词面匹配最强的实体（如 entity.game.sekiro）完全挤出。
- `scripts/catalog_utils.py`：新增共享加权打分三件套——`weighted_query_terms`（CJK 连续串不再拆单字，仅独立单字保留）、`term_weights`（IDF：稀有词高权、单字近零、拉丁专有名词加码）、`weighted_match_score`（命中权重和除以 1+log(文本长度)，长度归一）。`route_catalog` 域内排序接入同一打分（全量列出结构不变）。
- `scripts/retrieve_v2.py`：probe 全面换用加权打分；实体选择改为"词面匹配实体优先、事件链实体填充剩余名额"（修复名额 bug）；新增实体→事件反哺加权（查询命中实体时，挂靠该实体的时间条目获得 boost，如"哥哥 家里"→哥哥冲突事件）。trace 记录 `scoring: weighted-idf-1` 便于回放。
- 敏感性：按用户决策不做任何拦截或降权——档案写出来就是给模型看的，怕泄露而少接触数据是本末倒置；加权打分本身已消除"无关查询靠单字误拉敏感记录"（实测隐私查询下敏感健康记录从第 3 名自然掉到第 9 名）。
- 验收：沙盒 9 案例（5 失败 + 4 正面对照）回归 hard_fail=0——只狼实体第 1、巫师3 卡第 1、家里噪音第 2（哥哥冲突第 8，软期望）、隐私规范化第 3、CS2 第 1；四个正面对照全部保持第 1–3。
- 文档：SKILL.md/SKILL.zh-CN.md probe 节补充加权排序说明，撤下"probe 漏召回、查重以 routing 为主"的临时指引（2.4.0 遗留）。
- 版本同步修复（存量漂移）：pyproject.toml 停在 2.3.1 与 VERSION 2.4.0 不一致（test_repo_version_sync 自 2.4.0 起即红），本次统一升至 2.4.1。

## 2.4.0 — 2026-09-03 — two-tier reform: light tier merged into full

- 两档制改革（当日实测驱动）：轻量补记档（light）废除，活动足迹轮次并入完整档，受"足迹纪律"约束——写入前定向查重（防盲写，当日"已入学"误记的制度根源）、恰好一条 tier=light/salience 0–1 微型记录、查重零新增以 no-derivation-needed 体面收场（reason 须写明命中记录）、矛盾留证不断言。废除理由：免读取省下的少量 token 低于其引入的复杂度与事故率（盲写误记、查重死锁、回答无法利用档案背景）。
- `scripts/turn_receipts.py`：删除 `light-tier-requires-derived-record` 闸门（与"写入前查重"组合会产生"查重说别写、闸门说必须写"的死锁，实测复现于碎钉足球鞋场景）；`classify_personal_turn` 收到 tier=light 一律映射为 full（枚举仅为兼容保留）；signal 不再产生 personal-light。
- 查重工具指引：定向查重以 routing 视图为主入口（retrieve_v2 probe 对短词游戏名等查询存在漏召回，实测"只狼"场景 probe 未命中而 routing 命中）。
- 文档同步：SKILL.md 与 zh-CN 镜像同步两档制；README/zh-CN 当前版本声明更新；mcp_server 工具描述（preflight/finalize/add_record）同步两档语义，add_record 的记录层 tier=light 微型标记保留。

## 2.3.1 — 2026-09-03 — three-tier audit hardening

- Skip 声明留痕：`classify_personal_turn` 在 tier=skip 压制内容分类检出时，把被压掉的原始 reasons 保留进 receipt 新字段 `reasons_suppressed`——"内容判了个人却被声明 skip"从此可事后审计，不再只留当轮 stdout。
- 轻量档空闭环闸门：`audit_turn` 对 tier=light 且 closure_status=no-derivation-needed 的 receipt fail closed（`light-tier-requires-derived-record`）——文档承诺的"要么一条微型记录闭环，要么不该声明 light"从纯自觉升级为闸门强制；完整档的 no-derivation-needed（低信号快速通道）不受影响。
- finalize 返回语义修复（CLI + MCP）：收尾一个 capture 后的校验不再带 `--require-closed-captures`——多 capture 轮（正文+附件）里第一个 finalize 曾被"兄弟 capture 未关闭"误报为 error/rc=1；轮级闭环把关权集中在 session_check，finalize 只对结构性失败报错，并在返回中列出剩余 pending。
- 文档三处修订（SKILL.md 与 zh-CN 镜像同步）：档位升级必须换新 turn_id（同 turn_id 换档被幂等缓存吞掉、skip receipt 拒绝 capture）；skip 护栏条款（内容已检出个人材料的轮次禁止声明 skip）；消除"no-derivation-needed 之外的裁量空间"歧义句；轻量档多 capture 收尾方式（`verbatim_refs` 挂全本轮 capture）。`personal_finalize_capture` 工具描述同步轻量档限制。README/zh-CN 当前版本声明更新。

## 2.3.0 — 2026-09-03 — three-tier invocation (full/light/skip)

- 三档调用闸门重构：完整档 full（含抒发/闲聊，全流程）/ 轻量补记档 light（模型显式声明，capture 原话 + 恰好一条 salience 0–1 微型记录）/ 跳过档 skip（零接触）。设计原则：不扩充关键词自动检测，边界由模型具体问题具体分析。
- `scripts/turn_receipts.py`：`classify_personal_turn(text, tier)` 新增 tier 参数，receipt schema 1.1.1 含 tier 字段；light 强制 required（signal=personal-light），skip 强制清空。
- `scripts/mcp_server.py`：`personal_preflight_turn` inputSchema 加 tier 枚举；`personal_add_record` 加 tier 字段（full/light），tier=light 且 salience>1 拒绝写入，frontmatter 落盘 `tier:`。
- `scripts/v2_archive.py`：timeline entry 与 knowledge card 贯通 tier 字段（缺省 full）；entities/fragments 不携带（实体与原话无档位语义）。
- `SKILL.md`/`SKILL.zh-CN.md`/宿主 AGENTS.md 重写调用闸门为三档；版本四处同步（SKILL.md、SKILL.zh-CN.md、VERSION、pyproject）。

## 2.2.2 — 2026-09-03 — incident hardening, attachment restoration, protocol fix

- Attachment restoration: every incident-lost original recovered and re-captured under its original capture ID with sha256-verified provenance — 3 selfies (08-29), teeth photo, essay screenshot, gaokao note screenshot, barbershop mirror selfie (08-30), canon sports-meet photo (IMG_20241110); the 2024-03-02 essay's full 234-character text was re-transcribed from its recovered screenshot into the record.
- MCP server now forces UTF-8 stdio at startup: without it, a Windows box lacking `PYTHONUTF8=1` emitted GBK/cp1252 frames, breaking the MCP protocol (this is also why CI Windows was red since the workflow was born — it never installed pytest; fixed too).
- Turn receipts support multiple immutable captures per turn (`capture_ids`): a user turn containing text plus N photos no longer dies on the second capture — the exact 08-29 scenario. Found and fixed by the dummy-data release-gate pipeline; gate 3/3 green.
- `hot_mirror.py` hot-mirror watchdog: mirrors the skills tree every 15 minutes and auto-restores from the mirror the moment a mass deletion is detected (live state-file count collapses below 60% of the mirror). Sandbox `--selftest` covers mirror, idempotent cycle, and simulated wipe; deployed via a Startup VBS.
- `scripts/daily-backup.cmd` plus a real Task Scheduler task ("PersonalUnderstanding Daily Backup", 12:30 daily; previously blocked by antivirus HIPS, now created and test-run successfully).
- Test fixes found during a full drill: `test_v08_loops` window-range assertion now matches the intended interval-overlap semantics; the SKILL surface test detects per-file language instead of assuming one language. Suite: 92/92.
- Repo/body convergence: repo packaging and community files (pyproject, CI, LICENSE, templates, zh-CN docs, issue templates) synced into the local body; watchdog and backup scripts synced into the repo; union `.gitignore`.

## 2.2.1 — 2026-09-02 — installability and recovery hardening

- `validate_memory.py` derives the expected version from the `VERSION` file instead of hardcoding it (2.2.0 installs failed validation out of the box).
- `init_archive.py` builds v2 views during bootstrap so a fresh archive validates clean.
- `restore_stable.py`: scoped recovery from the stable zip (code/data/all, dry-run default, sha-256 verified, pre-restore snapshot).
- Added `glama.json` and a `Dockerfile` for the Glama MCP directory (install + security scan).
- CI (GitHub Actions matrix), issue templates, and a repo version-sync test.


All notable changes to Personal Understanding are documented here.
The project is developed as a working, daily-driven archive — many entries below
were motivated by real incidents found during use, which is exactly why the
hardening exists.

## 2.2.0 — 2026-09-01 — main branch hardening

> First release published to [PyPI](https://pypi.org/project/personal-understanding/) as `personal-understanding`.

- Added content-first, immutable turn receipts so personal material cannot be skipped just because it is framed as rewriting, translation, summarization, or image review.
- Bound capture, finalization, and `session_check --turn-id` to the receipt hash and made incomplete personal turns fail closed.
- Added a shared inter-process mutation lock, atomic writes, ledger journal/repair, and locked MCP record/follow-up/hypothesis writers to prevent lost updates between Agents and MCP processes.

## 2.1.0 — 2026-08-29 (three review-and-repair rounds: correctness, product polish, loop closure)

### Correctness fixes (P0)

- **Fixed a data-corruption defect in `salience_review.apply_decay`**: line numbers returned by `_frontmatter_span` were treated as character offsets for `text[:end]` slicing, so `--apply` could write `salience: 0` into the middle of an id line and shred frontmatter (on a scratch copy, 54 records had ids truncated and validation went straight to `failed`). Closing `---` is now inserted line-wise with CRLF handled. Found the first time the decay feature was exercised against real data — the lesson: rehearse on real-shaped data before shipping.
- Unified "follow-up is due" semantics: new shared helpers `v2_archive.followup_is_due / followup_open / followup_due_day` (dates truncated to day, unified status sets) replace four divergent implementations across v2_audit, build_current_state, review_v2, and retrieve_v2.
- Fixed `followup_check.py` CLI `--horizon` defaulting to 0 and overriding the library default of 3: the "due soon" reminder window works again.
- `load_v2` / `v2_audit` now tolerate a corrupt manifest / current-state file: corruption is reported as a structured error (`manifest-corrupt`, …) instead of crashing the whole preflight / validate / retrieval chain.
- Atomic writes everywhere: `jsonl_write`, pages rebuilds, current-state / index / manifest, MCP capture meta, add_followup / add_hypothesis all write tmp-then-rename; pages rebuild writes first and cleans later to avoid half-written states.
- `build_followups` turned from a one-shot seed import into an idempotent merge: new open loops keep flowing in, and hand-edited statuses inside the JSONL are no longer clobbered.
- Removed dead code (`query_memory.py`, `transition_record.py`, `build_catalog.py`); removed a stale hardcoded historical path from `review_skill.py`; cleaned leftover `.tmp` probes.
- MCP fixes: capture meta now records `codepoint_length` and writes atomically; unknown methods return JSON-RPC `-32601`; exception handling no longer relies on `locals()`; `finalize_capture` only validates instead of triggering needless full rebuilds; subprocess timeout raised 60s → 120s.
- `review_skill.py` thresholds unified with preflight (8); preflight no longer inlines a full deep review on its lightest step — it schedules one instead.

### Product polish (P1)

- SKILL.md description rewritten to be trigger-scenario oriented, improving auto-trigger hit rate;
- **Low-signal fast path** added: on low-information turns, capture fires immediately, reads degrade, the answer comes first, and finalization completes within the same turn — resolving the tension between the "natural conversation" contract and gate ceremony;
- survey spine buckets representative entries by life phase (childhood / middle school / high school / university …), fixing recency bias from "keep only the latest 60" so early pivotal events return to the resident map;
- survey takes the light path: no more building an ~879 KB legacy catalog just for survey (measured ~3109 ms → ~230 ms);
- probe output now carries an `evidence_fidelity` count per timeline entry (verbatim vs summary debt), making "is this from the exact words or an old summary?" visible at probe level.

### Loop closure (P2)

- Retrieval decision traces persisted: `retrieve_v2.py` appends every run's trace to `memory/v2/traces/trace-YYYYMM.jsonl` (`--capture-id` links the current turn, `--no-trace` disables) — decision traces became machine facts, not documentation wishes;
- **Backup model redesigned**: working archive as the living preview; archived snapshots (two fixed files: stable + previous, always one version behind) as rollback points; a new snapshot is cut only when more than 7 days have passed **and** structural validation passes ("behaves fine" is the criterion, not "nothing changed"). Optional cloud mirror pushes snapshots on demand to any rclone remote (a WebDAV cloud drive works; no resident background process, a few files per push, friendly to rate-limited free tiers — a 503 is a temporary throttle that recovers by itself); USB auto-mirror off by default; preflight / session_check surface snapshot age and nudge when overdue;
- `session_check` output adds feedback reminders and pending-capture age details (leftover pending captures are no longer a black box);
- references consolidated from 26 files into 14 (activation merged into retrieval policy, open loops into the timeline policy, people into entities, source catalog into capture policy, interaction + low-signal + proactive cues together, conflict + correction together, review + feedback together, maintenance + durability together);
- **New `scripts/install_mcp.py`**: detects local AI clients and registers the local MCP server (idempotent; no-op when paths already match). Covers Claude desktop builds, Codex, VS Code / Insiders, Cursor, Windsurf, Cline, Trae, ZCode and generic `.agents` layouts; `--export-dir` emits a universal `mcpServers` snippet with paste instructions for any future MCP-standard client;
- New root-level `register-mcp.cmd` (double-click registration) and a user README (daily use, moving machines, backups, health checks).

### Maintenance

- VERSION / SKILL.md / validate_memory version strings synced to 2.1.0; the v2 archive schema is unchanged (manifest `version` stays 2.0.0 with a separate `skill_version`), so no data migration is needed.

## 2.0.0 — runtime hardening round (2026-08-28; schema unchanged)

No data-architecture changes, only runtime defects fixed:

- survey became a compact routing map: only the v2 timeline spine, entity catalog, shared-story facets, model/value knowledge cards, current state, and follow-ups; the full legacy list moved to `routing`/`full` views. Size dropped from ~818 KB to ~90 KB per turn;
- fixed a double-escaping regex in `update_state.py` supersede handling: after `--apply`, superseded state records are now actually marked;
- fixed open-loops.md legend lines being imported as follow-up questions; `parse_open_loops` accepts only structured `- id:` entries and skips answered/declined loops;
- follow-up "due" checks now filter by date — future due dates no longer trigger early; `check_followups` default horizon set to 3 days so "due soon" reminders actually fire;
- fixed literal `\n` leaks in `validate_memory.py` and `retrieve_v2.py` output;
- the `next checkpoints` block of current state is now populated from due/undated follow-ups instead of staying empty;
- v2 builds support `date_end` and explicit `entity_refs` in record frontmatter; entity redirects merge old aliases to avoid post-merge recall loss;
- `rebuild_views.py` clears stale pages before rebuilding (no more ghost pages);
- `preflight_context.py` budget trimming drops items one by one until under budget;
- `capture_user_update.py` gained `--stdin` so very long verbatim messages no longer hit Windows command-line length limits;
- `update_state.py` confidence enum unified with the rest of the archive (six levels);
- **New `scripts/backup_archive.py` + backup policy**: the archive previously had "never delete" protection but no disaster tolerance — and a real data-loss incident had already been recorded inside it. Now there are append-only, verifiable local backups with SHA-256 manifests.

Three structural additions (2026-08-28 review round):

- **Salience review**: `scripts/salience_review.py` + policy. The archive only grows, so imported heuristic weights drift over time; quarterly, event/fact/entity weights unconfirmed for 180+ days decay to `salience: 0` (passing level — still retrievable, never deleted).
- **The hard gate**: `scripts/session_check.py` + MCP `personal_session_check`. One command with a hard exit code fusing structural validation + derivation closure + v2 integrity; claiming "the archive is updated" requires passing it. `update_state.py` now rejects state writes whose source record does not exist.
- **The feedback loop**: `scripts/record_feedback.py` + MCP `personal_add_feedback` + policy. After any answer that relied on memory, record how it landed (helpful / missed / corrected) and which memories were used; `review_v2 --deep` aggregates frequently corrected memories and prioritizes them for review. The user's natural reaction is the rating — no formal scoring required.

Cold recall and feedback tightening (driven by review):

- after the "cold memory dead zone" risk was raised, SKILL.md gained the **cold recall ladder**: with no keywords, probe from any entity hint → walk time neighbors → browse titles in a time window via `retrieve_v2.py --window`; demoted entries stay reachable on all three paths;
- `retrieve_v2.py` gained `--window` (`2025-03` or `2025-03:2025-08`): everything inside the window returns regardless of keyword hits;
- feedback policy rewritten to "default is not to record": silence, topic changes, and short replies produce no feedback; only explicit corrections, explicit misses, and evidenced confirmations may be written, and `note` must quote the user's words as evidence. `corrected` is the only signal that drives review priority — guarding against the model grading its own homework.

## 2.0.0 — 2026-08-22 (the architecture leap)

A full architectural jump, not a timeline reskin:

- Immutable user verbatim capture chain: save the complete original words first, derive everything else after;
- New `memory/v2/`: fragments, timeline, entities, contexts/facets, followups, hypotheses, relations, current-state, and indexes;
- One 0–3 `salience` memory-weight axis across the timeline, eliminating the double core/important/background taxonomy;
- Entity profiles extended beyond people: schools, places, objects, works, games, concepts, living environments;
- Cross-entity context cards ("school × football") reachable from either side;
- Follow-up scheduling with due-date proactive questions;
- Candidate causal hypothesis layer requiring mechanism, supports, limits, alternatives, and scope;
- `validate_memory.py` upgraded to clean / warnings / failed three-state validation, with `--strict` for migration acceptance;
- `review_v2.py --deep` reporting missing verbatim, summary debt, date gaps, orphaned entities, and pending follow-ups as review risks;
- MCP write entries gained verbatim capture, follow-ups, and candidate hypotheses — and reject bare `current-conversation` writes;
- Retrieval re-centered on the v2 spine: survey → event/entity/facet probe → verbatim deep read;
- Dashboard rebuilt around overview, timeline, entities, context cards, hypotheses, follow-ups, sources, and files;
- Legacy records, sources, and indexes kept; legacy summaries honestly marked `summary_only` — lost originals are never fabricated back into existence.

## 0.6.0 and earlier

Early-history notes live in the migration backups and file history. Runtime rules are governed by 2.0.0 and later.
