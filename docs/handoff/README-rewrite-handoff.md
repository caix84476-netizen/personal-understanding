# Personal Understanding — README 重写交接文档（v3-final，2026-10-10）

> **任务已完成并归档。** commit `77cd89e` 已 push 到 origin main（2026-10-10）。本文件保留作叙事蓝本与决策记录，后续 README 微调可直接参考第五节事实源与第七节注意事项。

> 这是 README 重写任务的技术蓝本与跨会话交接。新对话开始前先读这份文件，再读仓库当前状态，就能无缝继续。
> 本文件由 v1/v2 合并而来（原 README-rewrite-handoff-v1.md 已改名）。
> v3 变更：用户否决 v2 成品（套用原 README 表达、名词无铺垫、链接笼统、结构散乱），本轮按「只能看本体」纪律全部重写。

## 〇、当前进度

**已完成（v3 重写，2026-10-10）：**

1. ✅ `docs/how-it-works.md`（137 行）——按「一条消息的一生」主线十节：两档闸门/原话保真/派生闭环/事实层级/三层检索/联想通道/聚合与冷回溯/词面层/质量回路/诚实边界。每节末尾链到对应 references 政策文件。
2. ✅ `docs/why-it-works.md`（88 行）——四节：主流做法三宗罪/设计哲学六条（每条带 references 链接）/事故修补全表（14 行，含被否决方案留档）/借鉴致谢五家（含实测否决项）。
3. ✅ `docs/install.md`（v2 建，未受否决影响，保留）——手动安装逐步教程。
4. ✅ `README.md`（119 行）——中文主版，全新结构（见下）。
5. ✅ `README.en.md`（119 行）——同结构英文版，链接统一指向文件根（不带 # 锚点）。

**剩余步骤：**

6. ⏳ 用户过目 v3 成品。
7. ⏳ 用户确认后提交 push——只含 README.md、README.en.md、docs/（含本文件）；**不混入**工作区 12 个未提交的 MCP 修复文件（CHANGELOG/SKILL/references/scripts/tests，10-05/10-09 两轮）。
8. ⏳ push 后归档本文件。

## 一、用户对 v2 的批评（写作时必须对照自查）

1. **套用原 README 嫌疑**：v2 的「这是啥」「它从哪来」段落、mermaid 架构图直接搬自旧 README。用户重申纪律：**完成前只能看本体（SKILL.md/references/CHANGELOG/git log），制作时不能看原 README**。v3 已执行：全部表达从 SKILL §1–11、14 份 references、CHANGELOG 反推；mermaid 图改为自绘的「一条消息的一生」ascii 流程。
2. **名词无铺垫**：「两档路由」「侦探拼图」等直接蹦出。v3 规矩：每个名词首次出现就地一句话定义，不依赖链接。
3. **链接笼统**：v2 多处只链到文件根。v3 规矩：功能条链接到 docs 具体小节（#锚点）；references 链接在 docs 里出现、README 功能条里也直接给。
4. **结构无条理**：v3 采用固定叙事骨架——「它是什么（对比法下定义+解释标题里的两组关键词）→ 一条消息的一生（流程）→ 功能地图（记/存/想/养四组，每条=功能+一句为什么+怎么做链接）→ 上手 → 设计思路 → 结构 → 数据主权 → 许可」。

## 二、任务目标（原始要求，v3 落地情况）

- 新一句话简介：**“一个带原话溯洄的模拟人脑联想、发散、聚合、逆向等的 agent 记忆系统。”** ✅（「溯洄」保留，不改成「溯源」）
- 删掉原 README「但每条结论都追得回你当时说的原话」那句。✅
- 不看原 README 结构，从本体反推功能再组织表达。✅（v3 重做）
- 第一个主要结构回答：有哪些功能/怎么做/为什么做/原本做法什么问题；怎么做、为什么做各给链接。✅（功能地图每条=功能+为什么一句+怎么做链接；原本做法什么问题在「它是什么」和 why-it-works 第 1 节）
- 长度受控；survey/probe/deep/联想（逆向/聚合/发散）放一起讲。✅（「想」组）
- 搜索关键词、目录结构、设计思路、借鉴致谢。✅
- 安装：智能体一条聚合命令；手动教程超链接。✅
- 每次会话结束更新交接文档。✅（本文件 v3）

## 三、已确认的决策

1. 借鉴来源按 git 实证写五家（SYNAPSE/HippoRAG/Generative Agents/Qiao & Sun/jieba），不写「清华论文」。
2. 安装保持现状（git clone + init_archive + install_mcp），不做 npm 包。
3. README.md（中文）与 README.en.md（英文）同结构重写。
4. 详文在 `docs/` 下，README 相对链接。
5. 不新建 GitHub Issue；直接在仓库改。
6. 本轮范围：全部做完，push 前用户过目。

## 四、v3 的 README 结构（已落地）

1. 标题 + 一句话简介 + 导航链 + badges + 关键词行。
2. **它是什么**——两句话：干什么用（装在客户端里跨会话记得你）+ 与主流做法的核心区别（顺序倒过来），就地解释「原话溯洄」和「联想/发散/聚合/逆向」两组关键词。
3. **一条消息的一生**——ascii 五步流程（预检→捕获→派生→闭环→回想），标注各步对应 how-it-works 节号。
4. **功能地图**——记/存/想/养四组，每条格式：功能名 + 一句说清是什么 + （为什么 + 链接）或（细则链接）。
5. **上手**——一条聚合命令 + install.md 链接。
6. **设计思路**——一段叙事 + 五家致谢（链 why-it-works 第 4 节）。
7. **项目结构**——精简树。
8. **你的数据归你 / 许可**。

## 五、事实源（写作时必须遵守；v1 以来未变）

- 版本 2.8.0；纯 Python 3.10+ 标准库；PyPI 有服务端但建议 clone。
- 数据流：preflight 分类（第一人称+标记词召回、强情感词无「我」也召回、技术语境否决、模型兜底）→ 暂存 UTF-8 原文 → capture 只传 id+turn_id 转正（SHA-256、同会话同哈希复用 turn_id）→ 派生台账 pending → 派生（事件/实体/情境卡/假设/待回访）→ 闭环（derived 须双向链 / no-derivation-needed 写明命中）→ session_check 硬闸门（light 默认毫秒级）→ 回答 → 反馈回路。
- 落盘：`sources/conversation/`（原话）、`memory/v2/`（fragments/timeline/entities/contexts/followups/hypotheses/knowledge/feedback/relations/current-state/index/pages/traces/manifest）。
- 检索预算：survey 48K / routing 68K / full 96K / probe 80K / deep 100K，确定性截断附元数据。
- 联想通道：PPR 4 次迭代局部扩散，种子=命中实体/概念卡，两级候选，via_entity+spread_score，候选池非排序，绝不混入 timeline；概念卡 aliases 是地基。
- 聚合读法：拆 2–4 probe（情绪/利益/人物线），三层回答（档案事实/模式观察/模型推断）。
- 冷回溯阶梯：线索 probe → 时间邻居 → --window 浏览认领 → phase 扫主轴；禁止宣布「查不到」。
- 词面层：jieba+档案自训练词表；ASCII 单字无资格；CJK/ASCII 粘连；OOV ×0.4 降权不删；IDF；锚定比值降权；recency 0.5^(age/180d) 缺日期中性 1.0；superseded 软降权 ×0.5 不过滤。
- 借鉴实证（commit 4c6f460，2026-09-05）：SYNAPSE（sigmoid 门控 γ=5 θ=0.5 + fan-effect；其时间衰减方案否决）、HippoRAG（非均匀 reset + damping 0.5；收敛式 PPR 否决）、Generative Agents（时间衰减）、Qiao & Sun（自训练词典）、jieba（MIT vendor）。PMI 词表内聚过滤否决留档。
- 事故史（CHANGELOG）：2.1.0 frontmatter 撕碎→原子写入；2.0.0/2.1.0 survey 818KB→90KB；2.4.0 轻量档死锁→废除并入完整档+足迹纪律；2.5.0 pending 误报 isError→isError 只答落位；2.5.0 跨词 n-gram 霸榜→锚定降权；2.6.0 足迹 fail-closed 锁死→maintenance 只读降级；2.6.0 词面零重叠→PPR+概念卡；2.6.1 分类器结构门（捕获率 0.438→1.000）；2.6.1 superseded 盖 current→软降权；2.6.1 缺日期衰减埋记录→中性 1.0；2.7.0 写入 6.4s/竞态→轻量落位+mtime 脏检测；2.7.0 闸门可绕→缺省审计最近 receipt；2.8.0 SKILL 44.1KB→20.0KB、工具 13→11。
- 设计哲学：原话优先/派生闭环/诚实边界（五层事实、candidate 假设、「档案里没有 X」需 probe 证据、先对日期再讲故事）/时间主干/召回归工具判断归模型/本地可审计/防过拟合三律。

## 六、提交前检查清单

- [ ] 用户过目 README.md / README.en.md / docs 三件。
- [ ] 提交只含 README.md、README.en.md、docs/；不混入 12 个 MCP 修复文件。
- [ ] 建议 commit message：`docs: rewrite README (zh main + en) from skill body; add docs/{how-it-works,why-it-works,install}.md`
- [ ] push 到 origin。

## 七、风险与注意事项

- 「溯洄」二字必须保留。
- 不写「清华论文」。
- 不提 npm/npx 安装。
- 工作区未提交代码改动与 README 提交严格分开。
- **GitHub 中文锚点规则**：CJK 标点（——（）：）会被剥除，纯汉字连写保留。v3 中文 README 的 docs 内链锚点线上验证**失效**（用户 2026-10-10 确认「功能地图点不了」），已在 commit 73ee39e 全部降级为文件根链接；链接文字保留小节名作指引。教训：跨文件中文锚点在 GitHub 上一律不用。
- v2 被否决的根本原因是「看着像原 README 改改」——任何后续润色若重新引入旧 README 的句式（「所以半年后它把你记错了，你能审计」「不是拍脑袋想出来的框架」等），视为回退。
- 原 README 的 demo.svg 两文件保留未动，新 README 未引用（与旧版一致）。

---

**交接文档维护规则**：本文件是 README 重写任务的唯一技术蓝本。每次会话结束必须更新；新会话开始先读它，再读仓库当前状态，确保叙事与代码一致。任务全部完成并 push 后，可归档本文件。
