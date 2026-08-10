# 用户手册

## 1. 适用范围

本手册面向使用 Universal Knowledge Agent 的开发者、知识管理员和测试人员。它覆盖本地
安装、知识摄取、人工审批、作用域检索、纠正、Skill、Evolution、SDK/API 和常见故障。

本版本是本地可运行产品。生产使用还需要外部 IAM、可靠对象存储、数据库、高可用、配额、
保留/删除策略和容量 Gate。

## 2. 核心概念

### Evidence

Evidence 是不可变、内容寻址的输入或派生片段。它保存内容 hash、来源、父 Evidence 和
Locator。理解前先持久化 Evidence，保证模型结果可以回到原始材料。

### Experience、Scope、Knowledge

- Experience：模型基于整篇原文形成的自包含经验，不是单句摘录。它包含标题、背景、问题、
  机制、行动、结果、理解依据、适用边界、原文摘录和逻辑关系。
- Scope：经验适用的领域、任务、主体、地域、有效期、风险和置信度。
- Knowledge：经过审批后进入 active Registry 的版本化 Experience。

原文与 Experience 分开保存：原文是不可变 Evidence，用于对照和追溯；Experience 是 AI 对
原文逻辑的综合理解，用于检索和后续工作。Fragment 只负责 Locator，不会被逐行机械变成知识。

### tenant 与 security scope

tenant 是租户边界；security scope 是租户内的安全数据边界。两者必须同时提供。不同租户
或安全作用域之间不能复用 thread、checkpoint、Evidence、Knowledge 或 active revision。

### Knowledge Gap 与拒答

Knowledge Gap 不是失败日志，而是可检索、可补证、可版本化的“当前还不知道”。当模型在原文、
已有 active Knowledge 和有限网络检索后仍无法可靠解释一个术语、条件或因果链时，系统会：

1. 不生成貌似确定的 Experience；
2. 返回 `abstained` / `answer: unknown`；
3. 保存待回答问题、未决原因、缺失证据、可能方向、研究查询、链接键和研究轨迹；
4. 后续摄取新材料时把开放 Gap 作为受限上下文，并允许新候选通过 `resolves_gap_ids` 精确链接；
5. 只有该候选获批并进入 active Registry 后，才追加一个 `resolved` Gap revision。

开放状态包括 `research_exhausted`（搜过但证据仍不足）、`research_unavailable`（检索不可用或
因分类阻止外发）和 `partially_resolved`（出现可能解释但尚未完成审批闭环）。

### 状态值

- `accepted`：请求已接受，通常还在等待审批。
- `active`：知识已审批并进入 active Registry。
- `answered`：检索结果可在当前 Scope 和风险规则下返回。
- `answered_with_gaps`：已有核心答案可返回，但仍同时展示外围未决项。
- `abstained`：当前证据不足，主动拒绝给出确定答案，并返回开放 Knowledge Gap。
- `review_required`：需要人工复核，答案保持 `unknown`。
- `unknown`：没有可安全返回的匹配或完整性失败关闭。

## 3. 安装和初始化

```powershell
uv sync --dev
uv run uka-lg --project-root . init
uv run uka-lg --project-root . doctor
```

建议为每个环境使用独立的 `--project-root` 和状态目录，不要把测试状态与生产状态混用。

## 4. 受管 LLM 配置

使用 `llm-api-config` 的 profile 和注入流程：

1. 查看不含凭据的 profile 元数据。
2. 将选定 profile 注入项目 `.env.local`。
3. 运行 `doctor --connect`。
4. 用隔离 tenant/scope 执行一条无敏感样例摄取。
5. 确认结构化 Experience/Scope、审批中断、原文对照和 EvidencePack。

示例：

```powershell
uv run uka-lg --project-root . doctor --connect
```

禁止把 Key 放在 PowerShell 命令、GitHub Issue、测试 fixture、日志或文档中。离线回归使用：

```powershell
$env:UKA_USE_LLM = "0"
uv run pytest
```

## 5. 摄取知识

### 文本输入

```powershell
uv run uka-lg --project-root . ingest `
  --text "服务账号离职后必须立即撤销权限。" `
  --tenant demo `
  --scope private `
  --actor knowledge-admin `
  --thread-id ingest-001
```

### 文件输入

```powershell
uv run uka-lg --project-root . ingest `
  --file .\notes.md `
  --tenant demo `
  --scope private `
  --thread-id ingest-002
```

支持 UTF-8 文本、Markdown、JSON、CSV 和 HTML。输入先持久化为 Evidence，再解析为带
Locator 的 Fragment；模型仍按原始文档整体理解，避免丢失因果、条件、顺序、对比和例外。
Provider 合同失败、未知二进制、低置信度、高风险或 Scope 不完整会保留候选而不是直接激活。
如果保留的是理解缺口而非可审批结论，摄取响应会直接是 `abstained`，无需批准一个并不存在的
答案。公网研究只处理 `public`/`internal` 材料；机密及更高分类只保存 Gap，不外发查询。

## 6. 审批与恢复

默认摄取会进入 interrupt。使用相同 tenant/scope 恢复：

HTTP 摄取响应和线程状态会在中断期间提供 `approval_context`。它包含候选 Experience 的标题、
概览、背景、问题、机制、行动、结果、理解依据、置信度和演进谱系，以及解析后的 Scope 风险、
前提/排除项、未知项、原文逻辑关系、Evidence Locator、原文摘录和内容哈希。前端把这些信息组成
审批决策单；审批人应先对照原文和适用边界，再批准或拒绝。原文由受 tenant/scope 保护的仓储在
响应时动态解析，不会写进 LangGraph checkpoint。

```powershell
uv run uka-lg --project-root . resume `
  --thread-id ingest-001 `
  --decision approve `
  --tenant demo `
  --scope private
```

拒绝：

```powershell
uv run uka-lg --project-root . resume `
  --thread-id ingest-001 `
  --decision reject `
  --tenant demo `
  --scope private
```

检查线程：

```powershell
uv run uka-lg --project-root . status `
  --thread-id ingest-001 `
  --tenant demo `
  --scope private
```

Receipt 会让恢复和重试保持幂等。不要使用另一个 tenant/scope 绕过中断。

## 7. 检索知识

先查看当前作用域中的知识库：

```text
GET /v1/knowledge?tenant_id=demo&security_scope_id=private&limit=100
```

查看当前仍待补证的缺口：

```text
GET /v1/knowledge-gaps?tenant_id=demo&security_scope_id=private&limit=100
```

控制台的“待补知识”卡片可以直接点“手工补证”。请填写能回答该卡片问题的原始事实，可选填写
来源说明；前端会把目标 `gap_id` 一并提交，避免只靠关键词猜测关联。HTTP 调用方式如下：

```text
POST /v1/knowledge-gaps/{gap_id}/supplements
{
  "evidence_text": "现场手册明确写明……",
  "source_note": "设备手册第 4.2 节",
  "tenant_id": "demo",
  "security_scope_id": "private",
  "actor_id": "knowledge-admin"
}
```

补证不会直接把文字写成 active Knowledge。证据足够时响应返回 `approval_context`，审批人核对
模型理解、原文和拟关闭的 Gap 后再批准；证据仍不足时响应为 `abstained`，同一个 Gap 追加新 revision
并保留新的尝试记录。拒绝候选也不会关闭 Gap，只有批准激活后才会精确关闭目标项。

系统的生成语言跟随本次来源文本：中文来源的标题、概览、缺口问题、原因和可能方向应为简体中文；
设备型号、代码、专有名词和被引用的原始外文术语不会被强行翻译。历史英文演示数据不会被当成
中文对话新生成的内容。

每个词条会返回 Experience 字段、领域、前提/排除项、原文证据、完整性状态以及 learning /
evolution 谱系。前端控制台的 **Knowledge library** 可以按领域、主题、理解内容或原文筛选，
点击“用这条经验检索”会自动填入来源编号和正确领域。为控制页面长度，默认只显示前 5 条紧凑
词条，一次只展开一条完整经验；“显示更多”用于继续浏览，筛选仍会覆盖当前作用域的全部词条。

显式领域检索：

```powershell
uv run uka-lg --project-root . retrieve `
  --query "服务账号权限撤销" `
  --domain cybersecurity `
  --tenant demo `
  --scope private `
  --limit 5
```

还可以使用 `--task`、`--subject`、`--geography` 和 `--as-of`。Scope 过滤在最终 limit 前
执行，过期、非 active、冲突或完整性不通过的知识不会被拼入答案。EvidencePack 中的
`experience` 是综合理解，`evidence[].excerpt` 是对应原文，两者应一起审阅。

检索命中开放 Gap 且没有足够 active Knowledge 时返回 `abstained`。响应中的
`evidence_pack.knowledge_gaps` 可用于展示缺失证据与可能方向；如果已有可靠核心知识但还有
相关外围 Gap，则返回 `answered_with_gaps`，不会因一个外围未知项丢弃已有答案。

当前版本对未传领域的查询执行 FTS5 宽检索，不自动承诺唯一领域分类。对任意领域客户请求，
优先由调用方提供 `domain`；如果业务要求自动路由，应在网关增加领域推断和置信度 Gate。

## 8. 纠正知识

纠正需要目标 Knowledge ID 和期望 revision。系统会创建新 Evidence、Correction、ImpactSet
和 RegressionCase，审批后才移动 active 指针。

```powershell
uv run uka-lg --project-root . correct `
  --target-id <knowledge-id> `
  --expected-revision 1 `
  --text "修订后的知识内容。" `
  --tenant demo `
  --scope private `
  --thread-id correction-001
```

如果 revision 已变化，操作会失败关闭，不能覆盖最新版本。

## 9. Skill 生命周期

Skill 默认生成 advisory 制品，权限为空、网络拒绝、只做静态/沙箱检查：

```powershell
uv run uka-lg --project-root . build-skill `
  --knowledge-id <knowledge-id> `
  --tenant demo `
  --scope private
```

不要把生成的 Skill 当作生产执行器。任何需要外部写入、网络或凭据的能力必须通过独立的
权限评审和生产 Gate。

## 10. Evolution 生命周期

摄取新材料时，系统会先检索相关 active Knowledge，把有限的标题、理解、背景、依据和注意项
作为模型的先验上下文。模型可以把新经验标为 `reinforces`、`refines` 或 `contradicts`；系统
还会用相同来源编号建立确定性谱系。关联结果只会创建 evolution candidate：

- `derived_from_knowledge_ids` 记录参考过的旧知识；
- `knowledge_delta` 记录强化、修正或矛盾；
- `automatic_activation` 固定为 `false`；
- 候选必须经过 offline、shadow、canary、human Gate 才能替换策略。

这就是本版本的受治理自进化：既有知识会实际参与后续理解，但任何自我修改都不能绕过证据和
人工门禁。

Evolution 必须带有 offline、shadow、canary 评测证据，然后进入审批：

```powershell
uv run uka-lg --project-root . evolve `
  --target-type retrieval_policy `
  --baseline-revision v1 `
  --candidate-revision v2 `
  --offline-evaluation-id eval-offline-001 `
  --shadow-evaluation-id eval-shadow-001 `
  --canary-evaluation-id eval-canary-001 `
  --tenant demo `
  --scope private
```

评测指标不能只由候选自身声明；安全指标回退或证据缺失时必须拒绝。

## 11. Python SDK 和 HTTP API

SDK 入口是 `uka_langgraph.UniversalKnowledgeAgent`。HTTP 服务：

```powershell
uv run uka-lg --project-root . serve --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765/docs` 查看 OpenAPI。所有请求体都应包含：

```json
{
  "tenant_id": "demo",
  "security_scope_id": "private",
  "actor_id": "knowledge-admin"
}
```

HTTP thread resume 还必须提供与原线程匹配的 tenant 和 scope。服务端当前不提供生产级
身份认证；应放在受保护网关之后，并在服务端派生这些字段。

## 12. 排障

### `doctor --connect` 失败

检查 profile 是否已注入、Base URL 是否包含正确的 `/v1` 前缀、模型是否支持 JSON 结构化
输出。不要把 Key 打印出来。暂时可切换 `UKA_USE_LLM=0` 验证本地链路。

### 检索返回 `unknown`

检查 tenant/scope、domain、`as_of`、active 状态、风险和是否存在开放冲突。`unknown` 是
安全失败，不应通过放宽权限或删除 Scope 来解决。

### 恢复提示线程不存在或无权限

确认 thread ID、tenant 和 security scope 完全一致。不要用另一个租户重试。

### 纠正提示 revision 冲突

先重新检索目标 Knowledge，读取最新 revision，再决定是否基于新版本创建纠正。

## 13. 相关文档

- [README](../README.md)
- [实现架构](IMPLEMENTATION_ARCHITECTURE.md)
- [运维手册](OPERATIONS_MANUAL.md)
- [LLM 配置与测试](LLM_CONFIGURATION_AND_TESTING.md)
