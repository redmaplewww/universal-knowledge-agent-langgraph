# 项目进度

## 当前任务

| 任务 | 状态 | 负责人 | 完成条件 | 证据 ID | 最后更新 |
|---|---|---|---|---|---|
| 独立 LangGraph P0 基线 | 已完成 | Codex | F-001..F-008 通过对应验收 | E-002..E-006 | 2026-08-03 |
| `0.1.0` 本地完整产品 | 已完成 | Codex | F-009..F-015 与 A-011..A-016 通过 | E-008..E-011 | 2026-08-03 |
| 任意领域路由、分类与沉淀能力 Gate | 已完成 | Codex | 真实 HTTP/LLM、多领域、混合输入、安全与数据库审计完成 | E-012 | 2026-08-03 |
| 任意领域分类路由可靠性修复 | 已完成 | Codex | F-016 完成且 A-017/G-004 通过 | E-013 | 2026-08-04 |
| 深层完整性与隔离修复 | 已完成 | Codex | F-017 完成且 A-018/G-005 通过 | E-014 | 2026-08-04 |
| 五领域真实 LLM 诊断与优化审计 | 已完成 | Codex | 5/5 分类、证据、作用域检索和隔离通过；记录无作用域自动路由缺口 | E-015 | 2026-08-05 |
| GitHub 公开仓库发布与手册交付 | 已完成 | Codex | 公开仓库、首个 main 提交、README/用户手册/运维手册可访问 | E-016 | 2026-08-05 |
| AAWO 真实 LLM 完整回归 | 部分通过 | Codex | 领域/对抗 62/62 通过；生命周期发现线程状态响应契约缺口 | E-017 | 2026-08-09 |
| 上下文 Experience、原文对照与受治理自进化 | 已完成 | Codex | F-018 与 A-019/G-006 通过，前端展示真实 4 领域知识 | E-019 | 2026-08-10 |

## Frontend preview update (2026-08-09)

- Added a standalone static control-room frontend under `frontend/`.
- Added a local-only CORS allow-list for the preview origins in `src/uka_langgraph/interfaces/api.py`.
- Started an isolated real-LLM preview (`glm-5.2`) on `127.0.0.1:8877` and the frontend on `127.0.0.1:8890`.
- Browser verification passed for health, `accepted -> interrupt -> approve -> active`, scoped retrieval, evidence-pack rendering, and thread event timeline.
- Detailed evidence and run instructions: `docs/FRONTEND_PREVIEW.md`.

## Frontend readability refinement (2026-08-09)

- Reworked the control room from dark mode to a high-contrast light theme after visual review.
- Browser verification confirms the hero, metric cards, intake form, retrieval panel, and evidence trail remain readable on the running preview.

## Knowledge library and retrieval guidance (2026-08-10)

- Added tenant/scope-protected `GET /v1/knowledge` and SDK listing support with resolved domain, subjects, tasks, confidence, revisions, classifications, and evidence IDs.
- Added the frontend Knowledge library section with filtering and one-click scoped retrieval actions.
- Added an explicit explanation of `actor_id` and the default `control-room` audit label.
- Hardened FTS retrieval with prefix matching for Latin tokens adjacent to CJK text; regression coverage passes.

## 阻塞项

| 阻塞 | 影响 | 解除条件 | 状态 |
|---|---|---|---|
| 无本地实施阻塞 | 无 | 不适用 | 无 |

## 下一步

1. 优先为未提供 `query_scope.domain` 的查询增加受控领域推断/路由，并以结果纯度与未知域失败关闭作为验收条件。
2. 收紧未知 LLM 领域标签的 taxonomy 回退；评估 FTS5 与语义检索/查询扩展的混合召回。
3. F-017 已完成；后续变更必须保持 44 项深层完整性回归与 E-014 纠正旅程。
4. 生产部署仍需独立实现外部存储、IAM、密钥托管、配额/保留/删除策略和容量压测。
5. GitHub Actions workflow 尚未上传；当前 OAuth Token 缺少 `workflow` scope，如需启用 CI 需由仓库所有者重新授权后单独提交。
6. `GET /v1/threads/{thread_id}` 顶层 `thread_id` 已由 F-018 修复并经真实 AAWO 通过；后续可重跑旧
   E-017 全生命周期矩阵以形成独立替代报告。

## 进度历史

- 2026-08-10｜完成 `0.2.0` F-018｜从逐 Fragment 理解改为文档级 Experience；存储综合理解、
  LogicalRelation 与原文对照；active Knowledge 参与后续理解并生成不自动激活的演进候选；首次
  AAWO 52 条 Ledger 暴露检索断言和顶层 evolution IDs 契约问题，修正后 50 条通过，最终扩展
  4 领域后 115 条、20/20、完整性错误 0；47/47、Ruff、浏览器一键检索通过｜E-019｜G-006。
- 2026-08-09｜完成 AAWO 真实 LLM 完整回归｜受管 `glm-5.2` 注入且 `doctor --connect` 为 `ok`；10 个领域、混合输入、提示注入/未知输入、Scope 正负例、跨租户、重复输入共 62/62 通过；EvidenceLedger 310 条完整；生命周期 AAWO 8 个运行通过、2 个预期 HTTP 422 以失败终态观测、1 个真实契约失败：thread status 200 但顶层缺少 `thread_id`；离线 44/44、Ruff、账本校验通过｜E-017｜保留失败，不修改生产源码。
- 2026-08-05｜创建并推送公开 GitHub 仓库 `redmaplewww/universal-knowledge-agent-langgraph`｜提交 `697f645c6c406b4a1634be394b9ec7dc6b420a75`；远端 `PUBLIC`、默认分支 `main`；上传源码、测试、README、用户手册、运维手册、架构和验收文档；确认未上传 `.env.local`、状态目录、build/dist；GitHub Actions 因 OAuth 缺少 `workflow` scope 暂不上传｜E-016｜用户明确要求推送并公开。
- 2026-08-05｜完成五领域真实 LLM 诊断与 T4 风险审计｜受管 `glm-5.2` 连通，网络安全/化学/土木工程/环境/心理学 5/5 分类、证据绑定、带领域别名检索和跨租户隔离通过，环境高风险正确 `review_required`；无领域作用域查询虽 5/5 命中目标，但 4/5 混入跨域结果，宏平均结果纯度约 53%，确认自动查询域路由与混合检索为下一优化点；44 项离线测试与 Ruff 通过｜E-015｜未修改生产源码，未新增生产就绪声明。
- 2026-08-04｜完成 F-017 与 `0.1.2` 发布｜修复 correction 重分类/CAS、checkpoint namespace、Evidence 完整性、Scope-limit、冲突、Evolution 评测证据、Parser 超限与重复理解漂移；真实 Gate 经两次纠正后第三次 62/62，全部扩展回归、44 项离线测试和洁净安装通过｜E-014｜A-018/G-005 通过。
- 2026-08-04｜启动 F-017 深层完整性与隔离修复｜隔离复现确认跨租户 thread_id 劫持、纠正风险旁路和 stale revision 覆盖；静态审计确认 Evidence 缺失、Scope-limit、冲突生产、Evolution 自报指标和 Parser 静默截断缺口｜待 E-014｜用户明确授权“开始修复”。
- 2026-08-04｜完成 F-016 与 `0.1.1` 发布：受控 taxonomy、显式 Claim–Scope 关联、逐行/标题上下文解析、复核失败关闭与来源编号索引落地；82 条 AAWO 旅程、32 项离线测试、构建与洁净安装通过｜E-013｜A-017/G-004 通过；保留 G-003 原失败记录。
- 2026-08-04｜启动 F-016 修复：稳定 domain ID/alias、Claim–Scope 显式关联、混合文档粒度、`review_required` 失败关闭和源标识索引｜E-012｜将以原失败旅程做纠正驱动回归｜用户明确授权“修复一下”。
- 2026-08-03｜完成任意领域可靠性测试：82 条真实 HTTP 客户旅程、19 次真实 GLM 理解、419 条 AAWO EvidenceLedger 记录和 SQLite 沉淀审计｜E-012｜独立单领域分类通过，但规范领域名仅 5/10 命中，`review_required` 10/10 被直接回答，混合 Scope 过宽、Markdown 出现一条 Claim–Scope 错配、源标识检索 2/6 失败｜G-003 未通过；未修改生产代码。
- 2026-08-03｜完成 `0.1.0`：多格式 Evidence、FTS EvidencePack、真实 GLM、SDK/API、纠正/Skill/进化治理、脱敏事件、构建与洁净安装全部通过｜E-008..E-011｜本地完整产品 Gate 通过；不等同于生产集群部署或专家质量认证｜G-002。
- 2026-08-03｜启动 `0.1.0` 本地完整产品实现；通过 `llm-api-config` 重新注入受管 `glm` 配置，真实 GLM 结构化摄取成功并在 Scope review Gate 中断｜E-007｜尚待多格式、API、完整回归和发布 Gate｜用户明确要求。
- 2026-08-03｜完成独立 LangGraph P0：领域/应用/基础设施/编排分层、五子图、Evidence Vault、Receipt、SQLite checkpoint、CLI、模型配置接入和安装态恢复验证｜E-002..E-006｜生产 PostgreSQL、多模态与专家质量仍属后续范围｜按用户指令。
- 2026-08-03｜完成独立根目录与唯一项目账本初始化，确认旧工程只读边界｜E-001｜待实现代码与验收｜按用户指令。
