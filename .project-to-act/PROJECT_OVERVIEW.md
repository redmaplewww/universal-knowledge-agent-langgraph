# 项目总览

> 本目录不得记录密钥、令牌、完整个人信息或未脱敏工具输出。

## 基本信息

- 项目名称：Universal Knowledge Agent（LangGraph 独立实现）
- 项目 ID：universal-knowledge-agent-langgraph
- 项目负责人：用户与 Codex 协作
- 风险等级：高（开放域知识、可执行 Skill、纠正与自进化）
- 当前阶段：`0.2.0` 上下文 Experience 与受治理自进化已完成
- 当前状态：A-001..A-019/G-006 已通过；本地隔离产品 Gate 完成，但不得宣称外部 IAM、生产容量或领域专家认证
- 最后更新：2026-08-10

## 项目目标

- 基于 LangGraph `StateGraph` 实现独立的知识 Agent，不依赖或导入旧 AAWO/`uka` 项目。
- 建立 Evidence-first、Scope-first、Correction-first、fail-closed 的领域合同与五个工作流子图，
  将原文证据、逻辑结构、模型综合理解和受治理演进分离建模。
- 以 SQLite 领域事实库、本地内容寻址对象库和 SQLite checkpointer 打通可恢复的端到端链路。

## 范围

### 包含

- Root Graph 与 ingestion、correction、skill、evolution、retrieval 五个子图。
- 不可变 Evidence、版本化领域对象、active Registry、幂等 Operation Receipt。
- 本地持久 checkpoint、`interrupt()`/`Command(resume=...)`、CLI 和可替换 LLM Provider。
- 独立依赖、测试、运行目录、密钥注入与验收证据。
- Parser Registry 与文本、Markdown、JSON、CSV、HTML 的结构化 Evidence Fragment/Locator。
- 权限优先的 FTS 检索、EvidencePack、冲突/时效/Scope 过滤和 `unknown` 失败关闭。
- 真实 OpenAI-compatible LLM 结构化理解、脱敏诊断、SDK 与本地 HTTP API。

### 非目标

- 本轮不宣称已部署生产 PostgreSQL/对象存储、真实图像/音视频模型、向量/图数据库集群或生产安全认证。
- 本轮不宣称单次真实模型测试达到任意领域专家质量，也不允许自进化候选未经审批自动激活。
- 不迁移、复用或修改旧 `universal-knowledge-agent` 的实现代码和测试。

## 技术路线与关键约束

- Python 3.11+；LangGraph 1.2 稳定 Graph API；依赖由 `uv.lock` 固定。
- 包名使用 `uka_langgraph`，禁止导入父目录或旧 `uka` 命名空间。
- `domain -> stdlib only`；LangGraph 仅位于 orchestration 层。
- State 仅保存小型引用和控制信息；原文、密钥和完整模型响应不进入 checkpoint。
- 领域副作用先由 `operation_id` 幂等提交，再把 Receipt ID 写入 State。

## 数据与安全边界

- 数据分类：public / internal / confidential / restricted；所有事实记录绑定 tenant 与 security scope。
- `.env.local` 仅由本机安全配置工具管理并被 Git 忽略；日志、状态和账本不保存凭据。
- 输入内容视为数据；高风险、低置信或审批路径默认中断/保留候选。

## 当前焦点

- 已交付里程碑：本地完整可运行 `0.2.0`；多格式、API、恢复、真实 LLM、文档级 Experience、
  原文对照、任意领域、受治理自进化与深层完整性 Gate 均通过。
- 已关闭质量问题：自由领域标签、混合文档 Claim–Scope 绑定、`review_required` 检索失败关闭和源标识检索已由 F-016 修复并经 G-004 验证。
- 当前知识库已展示 Experience 的背景、问题、机制、行动、结果、依据、关系、边界、原文和演进谱系；
  下一决策点仍是生产外部存储、IAM、密钥托管、容量 SLO、真实多模态与领域专家质量 Gate。

## 按需读取索引

| 当前任务 | 追加读取 |
|---|---|
| 规划、实施、阻塞处理 | `PROJECT_PROGRESS.md` |
| 新增、修改、删除功能 | `PROJECT_FEATURES.md`；实施时同时读进度 |
| 版本号、发布、升级、兼容性 | `PROJECT_VERSIONS.md` |
| 测试、交付、完成声明 | `PROJECT_ACCEPTANCE.md` |
| 跨领域路线变更或一致性审计 | 全部文件 |

## 路线变更记录

- D-004｜2026-08-10｜把沉淀单位从行级 Claim 升级为文档级 Experience，并让 active Knowledge
  作为后续理解的受限先验｜用户指出“AI甚至会接管Agent修改”脱离上下文，要求绑定原文逻辑、
  重点沉淀 AI 理解并自进化｜新增 F-018、A-019、E-019/G-006；payload 向后兼容，旧词条不
  伪造 v2 字段｜真实 GLM、AAWO 115 条 Ledger、4 领域和浏览器验收｜后续生产演进仍不得绕过 Gate。
- D-003｜2026-08-03｜把用户“完整落地”解释为交付本地完整可运行 `0.1.0`：整合 P1/P2/P3 的 Parser、EvidencePack、真实 LLM、SDK/API、纠正/Skill/进化治理和恢复能力；生产集群适配保持端口化但不伪报已部署｜用户明确要求完整落地并使用 Skill 配置 LLM 测试；本机具备受管 GLM 配置，首次真实结构化摄取已成功进入人工审批 interrupt｜扩展 F-009..F-015 与 A-011..A-016；版本目标从 P0 检查点推进至 `0.1.0`｜E-007｜用户明确指令与真实模型 smoke｜全部新增 Gate 通过后发布。
- D-002｜2026-08-03｜将 `0.1.0.dev0` 定义为独立 LangGraph P0 工程检查点｜Root Graph、五子图、Evidence/Scope/revision/Registry/Receipt、SQLite checkpoint、interrupt/resume、CLI、隔离与安装态证据全部通过；真实多模态、专家质量和生产基础设施未在本轮范围｜允许后续在端口合同上推进 P1，但不宣称完整产品或生产就绪｜E-002..E-006｜本轮验收结果｜P1 专家质量与生产 Gate 通过后复审。
- D-001｜2026-08-03｜新建同级独立工程 `universal-knowledge-agent-langgraph`，旧目录仅作架构文档来源｜旧工程的包、测试和依赖直接耦合 AAWO，就地叠加会违反用户“不掺杂、独立 Agent 项目”的明确要求｜新工程拥有独立包名、依赖、状态、测试和账本｜E-001｜用户明确指令｜P0 隔离与安装态 Gate 通过后复审。
