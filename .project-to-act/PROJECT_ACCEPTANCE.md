# 项目验收

## 当前验收结论

- 结论：`0.3.1` 的 A-001..A-022/G-009 全部通过
- 验收范围：独立 LangGraph P0、本地完整产品 Gate、任意领域路由/分类，以及文档级 Experience、
  原文逻辑对照、受治理自进化、审批可见性、紧凑知识库、认识论拒答/补证闭环和中文人工补证 Gate
- 最后检查：2026-08-11
- 遗留问题：无作用域查询尚无自动领域推断且结果纯度不足；未知标签 taxonomy 回退仍可动态生成 ID；
  GitHub Actions 尚未上传（OAuth 缺少 `workflow` scope）；生产存储/身份认证/容量压测、真实多模态、
  向量或图混合检索和领域专家质量认证仍未在本轮验收范围

## 验收标准

| 标准 ID | 标准 | 状态 | 验证方法 | 证据 ID |
|---|---|---|---|---|
| A-001 | 新项目不导入旧 `uka`/AAWO 或父目录源码 | 通过 | 静态隔离测试与依赖审计 | E-003,E-004 |
| A-002 | 领域层不依赖 LangGraph/模型/数据库驱动 | 通过 | import AST 测试 | E-003 |
| A-003 | Evidence 在理解前持久化且内容寻址 | 通过 | ingestion 集成测试 | E-003,E-005 |
| A-004 | Root Graph 与五子图均可编译和路由 | 通过 | graph 测试 | E-003 |
| A-005 | State 不保存原文或 secret | 通过 | checkpoint/State 测试 | E-003,E-006 |
| A-006 | Receipt 保证恢复/重试不重复副作用 | 通过 | 幂等与故障恢复测试 | E-003,E-005 |
| A-007 | interrupt 可跨进程恢复 | 通过 | SQLite checkpointer 重开测试 | E-003,E-005 |
| A-008 | 权限和 active/scope 过滤早于返回 | 通过 | 租户与检索安全测试 | E-003 |
| A-009 | 完整测试、Ruff、构建、洁净安装通过 | 通过 | 标准验证命令 | E-003,E-004 |
| A-010 | CLI 端到端 smoke 可复现 | 通过 | 安装态 CLI smoke | E-005 |
| A-011 | 五种文本载体经 Parser Registry 生成可追溯 Fragment/Locator | 通过 | parser/ingestion 合同与攻击测试 | E-008 |
| A-012 | EvidencePack 执行权限、active、Scope、时效、冲突优先过滤 | 通过 | 检索安全与冲突测试 | E-008,E-010 |
| A-013 | 真实 LLM 受管配置、脱敏诊断与结构化摄取通过 | 通过 | GLM 连接/合同/E2E 测试 | E-009,E-010 |
| A-014 | SDK 与 HTTP API 全接口、审批和错误合同通过 | 通过 | API/SDK 合同测试 | E-008,E-011 |
| A-015 | 纠正、Skill、进化的影响/回归/审批/恢复路径通过 | 通过 | 生命周期与故障恢复测试 | E-008,E-011 |
| A-016 | `0.1.0` 全测、构建、洁净安装、安装态真实 LLM smoke 通过 | 通过 | 发布 Gate | E-010 |
| A-017 | 任意领域知识可用稳定类别路由、逐 Claim 正确绑定 Scope、需复核知识失败关闭并保持源标识可检索 | 通过 | AAWO 真实 HTTP 客户旅程、真实 GLM、多格式混合输入与 SQLite 关联审计 | E-013 |
| A-018 | 纠正内容重新分类且 stale revision 失败；checkpoint 不可跨 tenant/scope 复用；Evidence 不完整失败关闭；Scope/时效过滤不受 limit 掩盖；冲突、Evolution 评测证据与 Parser 超限均受强制 Gate | 通过 | 隔离失败复现、单元/集成、真实 HTTP/GLM、AAWO 纠正驱动回归、数据库完整性审计 | E-014 |
| A-019 | 完整文档生成自包含 Experience 并绑定原文逻辑/Locator；Knowledge library 与 EvidencePack 可对照原文；active Knowledge 实际参与后续理解；演进只生成不可自动激活的候选；4 领域与跨租户通过 | 通过 | 47 项离线测试、真实 GLM、AAWO HTTP 20 项检查/115 条 Ledger、SQLite 审计、浏览器 UI/检索验收 | E-019 |
| A-020 | 审批人在决定前可看到候选 Experience、理解链、Scope/risk、原文逻辑、Evidence/Locator/hash 和决策效果；原文不进入 checkpoint；知识库默认 5 条紧凑行、单条展开、可继续加载，桌面/390px 无溢出 | 通过 | API/SDK 合同、checkpoint 约束、真实 GLM 高风险候选、浏览器桌面/移动端交互、全量回归与洁净安装 | E-020 |
| A-021 | 无法可靠理解的经验在有限真实研究后保持 `abstained` 并版本化保存 Gap；检索仍拒答；已有核心答案不被外围 Gap 抹掉；新证据经审批后精确关闭目标 Gap；跨租户隔离且机密材料零外发 | 通过 | 51 项离线回归、真实 GLM/Web Search/HTTP、AAWO 三轮纠正驱动、SQLite/ledger 审计、浏览器缺口检索、构建与洁净安装 | E-021 |
| A-022 | 用户可对准一个开放 Gap 手工提交事实与来源说明；证据不足或拒绝时不关闭，批准激活后才精确关闭；中文来源的生成字段为简体中文且专名/原文保留；界面完整中文展示并在桌面/390px 可用 | 通过 | 53 项回归、真实 `glm-5.2`/HTTP 中文补证旅程、历史 Gap revision 审计、桌面/390px 浏览器、控制台、构建与洁净安装 | E-022 |

## 证据索引

| 证据 ID | 时间 | 方法或命令 | 退出状态 | 版本或文件哈希 | 结果摘要 | 证据位置 | 有效期 |
|---|---|---|---|---|---|---|---|
| E-001 | 2026-08-03 | 项目根/旧依赖审计与账本初始化 | 0 | 架构文档 2026-08-03 | 旧项目含 AAWO 依赖；新同级根已隔离并通过账本校验 | 新旧 `pyproject.toml`、`.project-to-act/` | 本开发周期 |
| E-002 | 2026-08-03 | 官方 LangGraph Graph API/Send/Command/interrupt/persistence 核对；PyPI 版本核对；`uv lock` | 0 | `uv.lock` SHA-256 `FB8EDF7F...A15696` | 固定 LangGraph 1.2.10 与 sqlite checkpointer 3.1.1 | `uv.lock`、官方文档 | 依赖升级前 |
| E-003 | 2026-08-03 | `uv run ruff check .`；`uv run pytest`；`compileall` | 0 | Python 源码/测试组合 SHA-256 `E71E2849...B8717` | Ruff 通过；13 项测试全部通过；编译通过 | `src/`、`tests/` | 本源码 revision |
| E-004 | 2026-08-03 | `uv build`；洁净 venv wheel 安装；两环境 `uv pip check` | 0 | wheel SHA-256 `E2F7D30F...47FEBE` | sdist/wheel 构建成功；Python 3.11 洁净安装和依赖一致性通过 | `dist/`、`build/verify-venv-20260803/` | 本 wheel |
| E-005 | 2026-08-03 | 安装态 `uka-lg init/ingest/retrieve/status` 与独立进程 `ingest -> interrupt -> resume` | 0 | wheel `E2F7D30F...47FEBE` | Evidence→Knowledge→检索与 SQLite checkpoint 跨进程审批恢复成功，Receipt ID 进入 State | `build/verify-root-20260803/` | 本 wheel/状态快照 |
| E-006 | 2026-08-03 | 本机受管 `glm` 配置注入与非秘密 doctor 检查 | 0 | `pyproject.toml` SHA-256 `10F8833B...34A68` | `.env.local` 已受管注入且被 `.gitignore` 覆盖；日志/State 未输出凭据；测试未调用真实模型 | `.env.local`（不读取）、`.gitignore`、doctor 摘要 | 配置变更前 |
| E-007 | 2026-08-03 | `llm-api-config Status/Inject(glm)`；`UKA_USE_LLM=1` 的隔离状态真实摄取 | 0 | 受管 profile 元数据 `glm/openai-compatible/glm-5.2` | 凭据未显示；真实模型返回结构化 Claim/Scope 并因 Scope review_required 正确进入人工审批 interrupt | `build/llm-smoke-current/`、thread `llm-smoke-current` | Provider/模型/config 变更前 |
| E-008 | 2026-08-03 | `uv run pytest`；`uv run ruff check .`；`compileall`；API/SDK/parser/retrieval/lifecycle/security 合同测试 | 0 | 源码/测试清单 SHA-256 `C79BA8BD...2983AA`；`pyproject.toml` `88732331...E400AD0`；`uv.lock` `F7E04C74...5749C7` | 27 项离线测试全部通过；五格式 Locator、Send 并发、FTS EvidencePack、API/SDK、ImpactSet/RegressionCase、Skill 沙箱、进化发布与脱敏事件通过 | `src/`、`tests/` | 本源码 revision |
| E-009 | 2026-08-03 | 受管 `glm` 的 `doctor --connect`、JSON 与 Markdown 真实摄取 Gate | 0 | Provider revision `openai-compatible:glm-5.2` | 诊断仅暴露配置状态和 revision；JSON 4 个 Fragment 完成审批/激活/检索，Markdown 6 个 Fragment 进入审批；修复 null 数组、并发 State 写入和定性置信度后回归通过 | `build/llm-release-gate/` | Provider/模型/config 变更前 |
| E-010 | 2026-08-03 | `uv build`；最终 wheel 洁净安装；安装态离线 ingest/retrieve；安装态真实 GLM `doctor -> ingest -> interrupt -> resume -> retrieve` | 0 | wheel SHA-256 `2F284D95...FA3647` | wheel/sdist 构建、49 个依赖安装与 `pip check` 通过；安装态 API OpenAPI 9 路径；真实模型将高风险规则激活后检索仍 fail-closed 为 `review_required / unknown` | `dist/`、`build/release-venv-010/`、`build/final-wheel-llm/` | 本 wheel |
| E-011 | 2026-08-03 | 安全/隔离/观测复核：thread/API 所有权、事件最小化、CLI 错误脱敏、旧项目导入禁止 | 0 | graph/API version `0.1.0` | 运行事件只含 ID/计数/错误类型；thread 操作必须 tenant/scope 匹配；未读取或输出 `.env.local`；旧项目保持未修改 | `tests/`、`src/uka_langgraph/interfaces/` | 本源码 revision |
| E-012 | 2026-08-03 | `aawo-agent-tester` 真实 HTTP/GLM 任意领域 Gate；10 独立领域、混合纯文本、JSON、Markdown、恶意/未知/隔离/重复输入；SQLite 关联审计；`pytest`/Ruff/compileall | 1（能力 Gate 失败；回归命令为 0） | 报告 `EB888689...9DE0FF`；EvidenceLedger `ABD24E05...8D679`；四份 JSON `6E584A58...D619E`/`ED8387AB...5FCF2`/`181C2872...CC9F`/`D60B7655...9F024` | 82 条旅程 75 通过/7 失败；Ledger 419 条且完整；独立领域语义分类 10/10，精确生成标签命中 10/10；规范领域名仅 5/10；review_required 10/10 被直接回答；混合 Scope 3/3 过宽；Markdown 1 条证据错配；源标识 2/6 不可检索；原有 27 项回归通过 | `docs/ARBITRARY_DOMAIN_ROUTING_TEST_REPORT_2026-08-03.md`、`build/arbitrary-domain-gate-20260803/evidence/` | Provider/源码/评测数据变更前 |
| E-013 | 2026-08-04 | F-016 纠正驱动回归：真实 GLM/HTTP、82 条 AAWO 旅程、结构化数据库审计、来源编号精确检索；`pytest`/Ruff/compileall/`uv pip check`/`uv build`/洁净安装 | 0 | 主报告 `A0638BB1...CFFA2`；别名 `D65309EB...0B4F4`；结构化 `F11D1144...A2525`；编号 `BBBFC041...35DA4`；Ledger `53934F29...8693A`；wheel `26BE4314...F7743` | 主旅程 62/62、别名 10/10、结构化知识 6/6、编号检索 6/6；关联错配/复核泄漏/Scope 过宽/编号丢失均为 0；Ledger 445 条完整；离线 32/32；0.1.1 构建和洁净安装通过 | `docs/ARBITRARY_DOMAIN_ROUTING_FIX_REPORT_2026-08-04.md`、`build/arbitrary-domain-gate-20260804d/evidence/`、`dist/universal_knowledge_agent_langgraph-0.1.1-py3-none-any.whl` | Provider/模型/taxonomy/评测合同变更前 |
| E-014 | 2026-08-04 | F-017 纠正驱动回归：44 项离线测试、Ruff/compileall、真实 GLM/HTTP/AAWO、真实高风险 correction/stale revision、构建/洁净安装 | 0 | 主报告 `1A611A0F...BCD69`；alias `147C04B3...E5783`；结构化 `D423C107...71E9B`；编号 `FEA7E5E3...DFE8A`；Ledger `3C5B4ACD...BFDA9`；wheel `57AA3198...42DF6` | 主旅程 62/62、alias 10/10、结构化 6/6、编号 6/6、Ledger 412 条完整；高风险 correction 强制审批且 stale 未激活；离线 44/44；0.1.2 洁净安装通过 | `docs/DEEP_INTEGRITY_FIX_REPORT_2026-08-04.md`、`build/deep-integrity-gate-20260804c/evidence/`、`dist/universal_knowledge_agent_langgraph-0.1.2-py3-none-any.whl` | Provider/模型/完整性合同变更前 |
| E-015 | 2026-08-05 | `llm-api-config` 受管 `glm` 注入与 `doctor --connect`；五领域真实 HTTP/GLM/AAWO ingest→approve→retrieve；SQLite 分类/证据关联审计；跨租户负例；44 项 pytest 与 Ruff | 0（已声明的五领域核心门禁通过；无作用域纯度为诊断项） | 报告 SHA-256 `EC16067E...AF3ADE`；EvidenceLedger `098B3AFC...23F51`；provider revision `openai-compatible:glm-5.2` | 5/5 稳定分类、证据绑定和带领域别名精确检索；环境领域正确 `review_required`；跨租户为 `unknown`；Ledger 105 条且完整；无作用域改写查询目标命中 5/5，但 4/5 混入其他领域结果，宏平均纯度约 53% | `build/five-domain-gate-20260805/evidence/five-domain-gate-report.json`、`build/five-domain-gate-20260805/evidence/evidence-ledger.sqlite3` | Provider/模型/检索或 taxonomy 合同变更前 |

| E-016 | 2026-08-05 | `gh repo create --public`、`git push -u origin main`、`gh repo view`、远端 commit API 核验 | 0 | commit `697f645c6c406b4a1634be394b9ec7dc6b420a75`；仓库 `https://github.com/redmaplewww/universal-knowledge-agent-langgraph` | 仓库为 PUBLIC，默认分支 `main`；62 个源码/测试/文档文件已推送；`.env.local`、状态、build/dist 未纳入；因 OAuth 缺少 `workflow` scope，CI workflow 未上传 | GitHub 远端仓库与本地 `git status` | 后续提交前 |
| E-017 | 2026-08-09 | `llm-api-config` 注入 `glm`；`doctor --connect`；AAWO `HttpAdapter`/`CustomerSimulationRunner` 真实 HTTP 回归；SQLite 数据库审计；`pytest`/Ruff/账本校验 | 0（领域/对抗 Gate）；1（生命周期 Gate，保留失败） | 领域报告 `CEC6CB5B...88649C1A`；领域 Ledger `6CD29B32...7FF6FF0E`；生命周期报告 `04B192E1...9EAE473C`；生命周期 Ledger `F4E6E04D...1106DB5B`；provider `openai-compatible:glm-5.2` | 62/62 领域与对抗旅程通过；领域 Ledger 310 条、完整性错误 0；生命周期 8 个 AAWO 运行通过，Skill/纠正/stale/Evolution fail-closed/错误合同通过；1 个接口契约失败：线程状态返回 200 但顶层缺少 `thread_id`；离线 44/44、Ruff、project-to-act 校验通过 | `build/aawo-complete-gate-20260809/arbitrary-domain-gate-report.json`、`build/aawo-complete-gate-20260809/evidence/lifecycle-gate-report.json`、对应 SQLite Ledger | 修复 API 响应合同或变更测试合同前 |

| E-019 | 2026-08-10 | F-018 真实上下文 Experience Gate：受管 `glm-5.2`、AAWO HTTP、4 领域、知识复用/演进、SQLite、47 项 pytest、Ruff、Node、浏览器验收与发布包洁净安装 | 0（最终 Gate）；1（首次纠正驱动运行，保留） | 最终报告 `0955737E...05BB437`；首次失败 `3310BE5E...79BD6E91`；中间通过 `A90617CA...258EE2`；wheel `F5E0CEA5...7506F06`；Provider `openai-compatible:glm-5.2` | 最终 20/20、网络安全/财务/机械/教育 4/4、Ledger 115 条且完整性错误 0；单篇 Agent 材料不再产生孤句；原文对照/检索/lineage/evolution candidate fail-closed/跨租户通过；浏览器一键检索 `ANSWERED / 1 EXPERIENCE`、控制台错误 0；0.2.0 wheel/sdist 构建、洁净 Python 3.11 安装及 49 个依赖一致性通过 | `docs/CONTEXTUAL_EXPERIENCE_AND_EVOLUTION_REPORT_2026-08-10.md`、`build/contextual-experience-gate-20260810d/evidence/`、`dist/universal_knowledge_agent_langgraph-0.2.0-py3-none-any.whl` | Provider/Experience 合同/检索/演进或前端变更前 |
| E-020 | 2026-08-10 | F-019 审批可见性与紧凑知识库：`llm-api-config` Status/Inject、真实 `glm-5.2` 摄取、浏览器桌面/390px、API/SDK 合同、47 项 pytest、Ruff/Node/compileall、wheel/sdist 与洁净安装 | 0 | wheel `FA04030F...552269`；Provider `openai-compatible:glm-5.2`；graph/API `0.2.1` | 真实高风险生产补丁候选完整展示标题/概览/六段理解/3 条逻辑/Scope/risk/原文/hash，拒绝后保持非 active；知识库默认 5/7、同时只展开 1 条、显示更多至 7；390px 无横向溢出；控制台错误 0；Python 3.11 洁净安装和 49 个依赖一致性通过 | `src/uka_langgraph/orchestration/runtime.py`、`frontend/`、`docs/FRONTEND_PREVIEW.md`、`dist/universal_knowledge_agent_langgraph-0.2.1-py3-none-any.whl` | 审批响应/前端/版本变更前 |
| E-021 | 2026-08-10 | F-020 认识论拒答与 Knowledge Gap：受管 `glm-5.2`、真实 Web Search、AAWO HTTP 三轮、SQLite/JSONL 审计、浏览器、51 项 pytest、Ruff/Node/compileall、wheel/sdist 与洁净安装 | 0（最终）；1（前两轮失败均保留） | 最终报告 `2D3724B4...3F1378F`；Ledger `5E94B6AD...A1B478`；首次失败 `E38F4BA5...F5595`；二次失败 `6C1E9457...447EA`；wheel `27EAA5EB...AB87DE`；sdist `CE7A391D...5C0756`；Provider `openai-compatible:glm-5.2` | 模糊经验拒答 3/3、Gap 检索拒答 3/3、核心答案保留 1/1、后续证据精确回链 1/1；跨租户与无关 Gap 保留通过；机密外发单测通过；51/51；Python 3.11 洁净安装和 49 个依赖一致性通过 | `docs/EPISTEMIC_ABSTENTION_AND_KNOWLEDGE_GAP_REPORT_2026-08-10.md`、`build/knowledge-gap-aawo-gate-20260810c/evidence/`、`dist/universal_knowledge_agent_langgraph-0.3.0-py3-none-any.whl` | Provider/研究/Gap/检索合同变更前 |
| E-022 | 2026-08-11 | F-021 精确人工补证与中文一致性：受管 `glm-5.2` 真实 HTTP 旅程、53 项 pytest、Ruff/Node/compileall、桌面/390px 浏览器、历史 Gap 追加 revision、wheel/sdist 与洁净安装 | 0 | 报告 `507056DE...FFA6EB25`；wheel `549D045B...A53DA3AC`；sdist `B7FE502A...1348D4D`；Provider `openai-compatible:glm-5.2`；graph/API `0.3.1` | 中文模糊材料生成中文 Gap；人工证据生成中文候选并精确绑定目标 Gap；批准后开放 Gap 归零；历史英文演示 Gap 追加中文 revision 2；桌面/390px 无横向溢出、控制台错误 0；53/53；Python 3.11 洁净安装和 49 个依赖一致性通过 | `docs/MANUAL_GAP_SUPPLEMENT_AND_LANGUAGE_FIX_2026-08-11.md`、`scripts/run_manual_gap_language_smoke.py`、`frontend/`、`dist/universal_knowledge_agent_langgraph-0.3.1-py3-none-any.whl` | Provider/补证/语言/前端合同变更前 |

## Gate 记录

| Gate ID | 日期 | Gate | 对象 | 结果 | 证据 ID | 豁免与确认人 |
|---|---|---|---|---|---|---|
| G-001 | 2026-08-03 | P0 独立实现 Gate | `0.1.0.dev0` | 通过 | E-001..E-006 | 无；仅限 P0 范围 |
| G-002 | 2026-08-03 | `0.1.0` 本地完整产品 Gate | `0.1.0` | 通过 | E-007..E-011 | 无；仅确认本地完整产品，不豁免生产基础设施与专家质量 Gate |
| G-003 | 2026-08-03 | 任意领域路由、分类与沉淀可靠性 Gate | `0.1.0` | 失败 | E-012 | 无；不得以 27 项既有回归或单领域语义正确豁免 |
| G-004 | 2026-08-04 | G-003 纠正回归 Gate | `0.1.1` | 通过 | E-013 | 无；保留 G-003 原失败事实，不把代表性领域 Gate 解释为所有知识的数学穷举或专家认证 |
| G-005 | 2026-08-04 | 深层完整性与隔离修复 Gate | `0.1.2` | 通过 | E-014 | 无；保留两次真实 Gate 失败记录，且不豁免生产 IAM/容量/专家认证 |
| G-006 | 2026-08-10 | 上下文 Experience、原文逻辑与受治理自进化 Gate | `0.2.0` | 通过 | E-019 | 无；保留首次 AAWO 失败，不把 4 领域代表性 Gate 宣称为任意领域数学穷举或专家认证 |
| G-007 | 2026-08-10 | 审批决策可见性与紧凑知识库 Gate | `0.2.1` | 通过 | E-020 | 无；只确认本地授权响应和浏览器可用性，不豁免生产 IAM、审计策略或外部部署 Gate |
| G-008 | 2026-08-10 | 认识论拒答、有限研究与补证回链 Gate | `0.3.0` | 通过 | E-021 | 无；保留两轮真实失败，不把代表性领域 Gate 宣称为任意领域穷举或专家认证；不豁免生产 IAM、来源信誉与外发策略 Gate |
| G-009 | 2026-08-11 | 精确人工补证与中文输出一致性 Gate | `0.3.1` | 通过 | E-022 | 无；只确认指定真实模型旅程和本地浏览器可用性，不豁免生产 IAM、来源信誉、容量或领域专家认证 |

## 验收记录

- 2026-08-11｜精确人工补证与中文一致性｜E-022｜真实 `glm-5.2`/HTTP 中文旅程从拒答、Gap、
  人工证据、完整审批到精确关闭通过；历史英文 Gap 追加中文 revision；53/53、桌面/390px、控制台、
  构建和洁净安装通过｜A-022/G-009 通过。

- 2026-08-10｜认识论拒答与 Knowledge Gap 补证闭环｜E-021｜真实 GLM/Web Search/HTTP 的三轮
  纠正驱动测试保留 9 项与 3 项失败，最终四项核心比率均为 1.0；跨租户、无关 Gap、机密零外发、
  51/51、构建和洁净安装通过｜A-021/G-008 通过。
- 2026-08-10｜审批决策单与紧凑知识库｜E-020｜真实 GLM 高风险候选的模型理解、Scope/risk、
  原文关系、证据和决策效果均在批准前可见；测试候选被拒绝且未激活；5/7 紧凑列表、单条展开、
  390px、控制台、47/47、构建和洁净安装通过｜A-020/G-007 通过。
- 2026-08-10｜上下文 Experience 与自进化纠正回归｜E-019｜首次 AAWO 运行保留
  `review_required` 断言误配和顶层 `evolution_ids` 契约失败；修正后扩展至 4 领域，最终 20/20、
  Ledger 115 条、完整性错误 0，47/47 与浏览器验收通过｜A-019/G-006 通过。
- 2026-08-09｜AAWO 真实 LLM 完整回归｜E-017｜领域/对抗客户旅程 62/62 通过；生命周期检查保留 1 个线程状态响应契约失败，2 个 HTTP 422 是预期安全拒绝的失败终态；未将失败改写为通过，A-001..A-018/G-005 状态不变，待修复后重跑生命周期 Gate。

## Frontend preview acceptance (E-018)

- `frontend/index.html`, `frontend/styles.css`, and `frontend/app.js` form a standalone browser control room with no build-time dependency.
- Real browser verification against an isolated `demo-ui/private` backend passed: provider health (`glm-5.2`), intake, approval resume, retrieval, evidence-pack display, and event timeline.
- Preview endpoints remain loopback-only: frontend `127.0.0.1:8890`, API `127.0.0.1:8877`.
- This acceptance covers local preview usability; it does not claim production hosting, IAM, gateway policy, or capacity readiness.

## Frontend readability refinement

- The local preview now uses a light paper-surface palette with dark ink, high-contrast controls, and amber-only approval emphasis.
- Browser screenshots and DOM inspection confirm the primary desktop layout remains readable after the theme change.

## Knowledge library and retrieval guidance

- `GET /v1/knowledge` returns only active knowledge from the requested tenant/security scope and includes resolved scope metadata.
- The frontend shows five active entries in the isolated preview, including domain, content summary, subjects/tasks, confidence, revision, and evidence count.
- A card's “用于检索” action fills the query and domain; browser verification returned an `ANSWERED` evidence pack for the selected Software Engineering entry.
- `actor_id`/`control-room` semantics are explained in the UI and `docs/FRONTEND_PREVIEW.md`.

## Approval decision brief and compact library (E-020)

- Interrupted ingest and thread status responses dynamically include tenant/scope-protected
  `approval_context`; checkpoint State continues to contain references rather than source text.
- The decision brief exposes the candidate synthesis, six-part logic, source relations, Scope/risk,
  preconditions/exclusions, caveats, original Evidence/Locator/hash, and decision effects.
- The active library renders five compact rows by default, closes the previous row when another is
  opened, and exposes show-more/collapse controls; 390 px has no horizontal overflow.
- 2026-08-05｜公开仓库与手册交付｜E-016｜远端仓库为 PUBLIC，main 已跟踪远端，README、用户手册、运维手册和架构文档可访问；凭据扫描无匹配，运行目录未上传；CI workflow 受 GitHub OAuth scope 限制未提交｜公开发布完成；Actions 待重新授权后另行启用。
- 2026-08-05｜五领域真实 LLM 诊断｜E-015｜网络安全、化学、土木工程、环境、心理学的分类/证据/作用域检索/隔离核心项全部通过；高风险失败关闭正常；未限定领域时目标召回 5/5，但结果纯度不足，故只登记诊断证据，不新增或提升生产 Gate｜A-001..A-018/G-005 状态不变。
- 2026-08-04｜深层完整性与隔离纠正回归｜E-014｜首次 59/62 与二次 60/61 失败均保留并驱动冲突规则、revision 幂等与理解缓存修复；最终真实主旅程及全部扩展回归通过，44 项离线测试和 0.1.2 洁净安装通过｜A-018/G-005 通过。
- 2026-08-04｜任意领域可靠性纠正回归｜E-013｜上一轮五类失败全部修复；真实 GLM/HTTP 的 82 条 AAWO 旅程全部通过，数据库关联、审核失败关闭、混合文档与来源编号审计均无失败；32 项离线测试和 0.1.1 洁净安装通过｜A-017/G-004 通过；G-003 原失败记录保留。
- 2026-08-03｜任意领域路由、分类与沉淀可靠性验收｜E-012｜82 条 AAWO 客户旅程与真实数据库审计完成，原有回归 27/27 通过，但 A-017 因 Scope 失败关闭、稳定 taxonomy、混合文档绑定与源标识检索问题失败｜G-003 未通过；不能宣称任意领域可靠性。
- 2026-08-03｜`0.1.0` 本地完整产品全量验收｜E-007..E-011｜A-001..A-016 全部通过；真实 GLM 和最终 wheel 安装态闭环通过；高风险检索保持 fail-closed｜G-002 通过；不宣称生产集群部署或领域专家认证。
- 2026-08-03｜独立 LangGraph P0 全量验收｜E-001..E-006｜A-001..A-010 全部通过；未跳过测试｜P0 通过，P1-P4 未验收。
- 2026-08-03｜创建验收合同｜E-001｜尚未执行测试｜未验收。
