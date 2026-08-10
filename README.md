# Universal Knowledge Agent — LangGraph

独立的 Evidence-first、Scope-first 知识 Agent。它先按原始文档理解上下文和逻辑关系，再把
模型的综合理解沉淀为可追溯 Experience、Scope 和版本化 Knowledge，并通过 LangGraph 编排
摄取、检索、纠正、Skill 和受治理 Evolution 生命周期。

仓库名：`universal-knowledge-agent-langgraph`  
当前版本：`0.3.1`
运行时：Python 3.11+、LangGraph 1.2.10、SQLite、FastAPI

> 本项目是独立实现，不导入、不依赖同级旧 `universal-knowledge-agent` 或 AAWO 运行时。
> 当前是可审计的本地完整产品，不宣称已经完成生产 IAM、集群容量、专家质量认证或真实多模态部署。

## 你可以用它做什么

- 将 TXT、Markdown、JSON、CSV、HTML 保存为内容寻址 Evidence，并生成精确 Locator。
- 用受管 OpenAI-compatible LLM 在文档级生成自包含 Experience：标题、背景、问题、机制、
  行动、结果、理解依据、适用边界、原文摘录和显式逻辑关系。
- Fragment 只承担精确 Evidence Locator，不再被逐句机械编译为脱离上下文的知识。
- 在高风险、低置信度、冲突或 Scope 不完整时进入人工审批，不直接生成确定答案。
- 审批响应提供受 tenant/scope 保护的 `approval_context`：候选 Experience、理解链、风险、
  适用边界、原文和 Locator 可在批准前完整核对，且原文不会进入 checkpoint。
- 按 tenant、security scope、active revision、领域、任务、主体、地域和时效过滤检索结果。
- 通过 EvidencePack 返回综合 Experience、Scope、原文摘录、Evidence hash、父 Evidence 和 Locator。
- 以 `interrupt()`/`resume` 实现跨进程审批恢复，以 Receipt 保证重试不重复副作用。
- 对知识纠正执行 expected-revision CAS，生成 ImpactSet 和 RegressionCase。
- 编译受限的 advisory Skill，并对 Evolution 执行 offline → shadow → canary → 人工审批。
- 新材料会检索相关 active knowledge 作为受限理解上下文；强化、修正或矛盾只生成带谱系的
  Evolution candidate，永不未经 Gate 自动替换旧策略。
- 当术语、上下文或因果链在现有证据和有限网络检索后仍无法可靠理解时，返回 `abstained`
  而不是猜测，并把问题、缺失证据、可能方向、检索记录和链接键保存为版本化 Knowledge Gap。
  后续材料可显式引用并关闭对应 Gap；只有关联候选获批激活后才会真正关闭。
- 通过 CLI、Python SDK 和本地 FastAPI HTTP API 使用。

## 快速开始

### 1. 安装

```powershell
uv sync --dev
uv run uka-lg --project-root . init
```

### 2. 配置 LLM

不要把 Key 放在命令行、源码、日志、Issue 或 README。使用本机的 `llm-api-config` 技能管理
profile 并注入项目 `.env.local`。项目只读取环境变量；`.env.local` 已被 Git 忽略。

```powershell
uv run uka-lg --project-root . doctor
uv run uka-lg --project-root . doctor --connect
```

没有 LLM 配置时可使用确定性离线 Provider：

```powershell
$env:UKA_USE_LLM = "0"
uv run uka-lg --project-root . doctor
```

### 3. 摄取并审批一条知识

```powershell
uv run uka-lg --project-root . ingest `
  --text "校准周期为 180 天。" `
  --tenant demo `
  --scope private `
  --thread-id ingest-001
```

默认会在人工审批前中断，并输出 `thread_id`。审批恢复：

```powershell
uv run uka-lg --project-root . resume `
  --thread-id ingest-001 `
  --decision approve `
  --tenant demo `
  --scope private
```

### 4. 检索

```powershell
uv run uka-lg --project-root . retrieve `
  --query "校准周期" `
  --domain maintenance `
  --tenant demo `
  --scope private
```

检索结果可能是 `answered`、`answered_with_gaps`、`abstained`、`review_required` 或 `unknown`。
`abstained` 会返回待补问题、缺失证据和可能方向；没有领域作用域时，当前版本
执行受控的宽检索，不保证自动推断唯一领域；生产使用建议显式传入 `--domain`，详见
[用户手册](docs/USER_MANUAL.md)。

## CLI 命令

```text
uka-lg init
uka-lg doctor [--connect]
uka-lg ingest --file <path>|--text <text> --tenant <id> --scope <id>
uka-lg retrieve --query <text> --tenant <id> --scope <id> [--domain ...]
uka-lg correct --target-id <id> --expected-revision <n> --file <path>|--text <text> ...
uka-lg build-skill --knowledge-id <id> --tenant <id> --scope <id>
uka-lg evolve --target-type <type> --baseline-revision <id> --candidate-revision <id> ...
uka-lg resume --thread-id <id> --decision approve|reject ...
uka-lg status --thread-id <id> --tenant <id> --scope <id>
uka-lg serve [--host 127.0.0.1] [--port 8765]
```

每个会改变状态的命令都应明确 tenant 和 security scope。HTTP thread 操作同样必须提供
匹配的租户和安全作用域。

## Python SDK

```python
from uka_langgraph import UniversalKnowledgeAgent

agent = UniversalKnowledgeAgent(project_root=".")
pending = agent.ingest_text(
    "校准周期为 180 天。",
    tenant_id="demo",
    security_scope_id="private",
    thread_id="sdk-ingest-1",
)

if "__interrupt__" in pending:
    active = agent.resume(
        "sdk-ingest-1",
        {"decision": "approve"},
        tenant_id="demo",
        security_scope_id="private",
    )
```

## HTTP API

启动本地服务：

```powershell
uv run uka-lg --project-root . serve --host 127.0.0.1 --port 8765
```

OpenAPI/Swagger：`http://127.0.0.1:8765/docs`

主要接口：

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 非秘密配置和可选 Provider 健康检查 |
| `POST` | `/v1/ingest` | 摄取文本并可能返回带 `approval_context` 的审批中断 |
| `POST` | `/v1/retrieve` | 受 tenant/scope/Scope 过滤的 EvidencePack 检索 |
| `GET` | `/v1/knowledge` | 展示 active Experience、原文对照、逻辑关系和演进谱系 |
| `GET` | `/v1/knowledge-gaps` | 展示当前 tenant/scope 中仍待补证的 Knowledge Gap 与检索轨迹 |
| `POST` | `/v1/knowledge-gaps/{gap_id}/supplements` | 对准一个开放缺口提交人工补证，并生成必须审批的候选 |
| `POST` | `/v1/corrections` | 创建纠正版本 |
| `POST` | `/v1/skills` | 创建 advisory Skill |
| `POST` | `/v1/evolution` | 创建 Evolution 提案 |
| `GET` | `/v1/threads/{thread_id}` | 查看受保护的线程状态 |
| `POST` | `/v1/threads/{thread_id}/resume` | 审批或拒绝中断线程 |
| `GET` | `/v1/threads/{thread_id}/events` | 查看脱敏运行事件 |

## 架构

```text
interfaces -> orchestration -> application -> domain
                  |                 ^
                  v                 |
             infrastructure --------+
```

- `domain`：只使用 Python 标准库，定义 Evidence、Experience candidate、LogicalRelation、Scope、Revision 和 EvidencePack。
- `application`：依赖 Parser、Provider、Repository、Object Store 端口；副作用携带
  `operation_id` 并写入 Receipt。
- `infrastructure`：Parser Registry、内容寻址对象库、SQLite Registry/FTS/Event Ledger、
  OpenAI-compatible Provider。
- `orchestration`：唯一导入 LangGraph；State 只保存引用和控制字段，不保存原文或 secret。
- `interfaces`：CLI、SDK、FastAPI。

完整链路见[实现架构](docs/IMPLEMENTATION_ARCHITECTURE.md)。

## 数据与安全边界

- 所有 Evidence、Scope、Knowledge 和线程都绑定 tenant 与 security scope。
- 原文先进入本地对象库；LangGraph checkpoint 不保存原文、密钥或完整模型响应。
- Evidence 哈希、父 Evidence、Locator 和 active revision 会在返回前校验。
- 高风险、低置信度、冲突和复核失败结果保持 `review_required`/`unknown`。
- `confidential`、`restricted`、`secret`、`prohibited` 分类的材料禁止外发网络检索；Gap 保留为
  `research_unavailable`，等待授权的本地或后续证据补充。
- “待补知识”支持直接展开人工补证表单。补证会携带精确 `gap_id` 重新理解，证据仍不足时追加
  Gap revision 而不伪造结论；形成候选时必须先展示完整审批决策单，批准后才关闭目标缺口。
- 中文来源要求模型生成的标题、问题、原因、方向、概览等自然语言字段保持简体中文；来源中的
  产品名、代码、标识符和原文术语保留原样。语言不一致会触发一次受约束修复，仍不合格则失败关闭。
- 当前 API 的 tenant/actor 是调用方输入，尚未替代生产 IAM；接入生产前必须由网关或服务端
  身份系统确定主体、租户、RBAC、配额和审计策略。

## 测试与验收

```powershell
uv run ruff check .
uv run pytest
uv run python -m compileall -q src
uv build
```

本地验收已覆盖 53 项离线测试；真实 `glm-5.2` 与真实 Web Search 的 Knowledge Gap AAWO HTTP
Gate 在工业校准、口述史、农学和软件工程代表性旅程中达到：模糊经验拒答 3/3、缺口检索拒答
3/3、已有核心答案保留 1/1、后续证据精确回链 1/1。此前上下文 Experience Gate 产生 115 条完整 Ledger
记录，验证了上下文综合、原文逻辑、原文对照、检索、知识复用、Evolution 不自动激活、
跨租户隔离，以及网络安全、财务、机械工程、教育 4 个领域。结果见
[上下文经验与自进化报告](docs/CONTEXTUAL_EXPERIENCE_AND_EVOLUTION_REPORT_2026-08-10.md)。
拒答与补证闭环见
[认识论拒答与 Knowledge Gap 报告](docs/EPISTEMIC_ABSTENTION_AND_KNOWLEDGE_GAP_REPORT_2026-08-10.md)。
人工补证中文旅程还验证了中文缺口、精确目标绑定、审批后关闭与桌面/390px 页面可用性，见
[人工补证与中文一致性修复报告](docs/MANUAL_GAP_SUPPLEMENT_AND_LANGUAGE_FIX_2026-08-11.md)。

## 文档导航

- [用户手册](docs/USER_MANUAL.md)：安装、概念、CLI/SDK/API、审批、纠正和排障。
- [运维手册](docs/OPERATIONS_MANUAL.md)：密钥、状态目录、备份、升级、发布和生产边界。
- [实现架构](docs/IMPLEMENTATION_ARCHITECTURE.md)：模块、图、数据流和替换边界。
- [LLM 配置与测试](docs/LLM_CONFIGURATION_AND_TESTING.md)：受管模型配置与真实测试方法。
- [任意领域修复报告](docs/ARBITRARY_DOMAIN_ROUTING_FIX_REPORT_2026-08-04.md)。
- [深层完整性修复报告](docs/DEEP_INTEGRITY_FIX_REPORT_2026-08-04.md)。
- [上下文经验与自进化报告](docs/CONTEXTUAL_EXPERIENCE_AND_EVOLUTION_REPORT_2026-08-10.md)。
- [认识论拒答与 Knowledge Gap 报告](docs/EPISTEMIC_ABSTENTION_AND_KNOWLEDGE_GAP_REPORT_2026-08-10.md)。
- [人工补证与中文一致性修复报告](docs/MANUAL_GAP_SUPPLEMENT_AND_LANGUAGE_FIX_2026-08-11.md)。

## 版本与授权说明

当前版本是 `0.3.1`。`pyproject.toml` 使用 `LicenseRef-Proprietary`；本仓库可公开查看，
但当前没有授予开源再分发、商用或修改授权。若需要以 MIT、Apache-2.0 或其他许可证公开，
请先明确授权后再补充 LICENSE 文件。

## 贡献与问题反馈

提交 Issue 或 PR 时请不要包含 API Key、`.env.local`、原始客户材料、完整模型响应或生产
数据库。请提供脱敏的复现步骤、版本、命令、退出状态和最小测试样例。
