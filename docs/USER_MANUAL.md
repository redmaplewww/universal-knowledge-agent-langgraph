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

### Claim、Scope、Knowledge

- Claim：从一个 Evidence 片段中提取的可检索主张。
- Scope：主张适用的领域、任务、主体、地域、有效期、风险和置信度。
- Knowledge：经过审批后进入 active Registry 的版本化主张。

### tenant 与 security scope

tenant 是租户边界；security scope 是租户内的安全数据边界。两者必须同时提供。不同租户
或安全作用域之间不能复用 thread、checkpoint、Evidence、Knowledge 或 active revision。

### 状态值

- `accepted`：请求已接受，通常还在等待审批。
- `active`：知识已审批并进入 active Registry。
- `answered`：检索结果可在当前 Scope 和风险规则下返回。
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
5. 确认结构化 Claim/Scope、审批中断和 EvidencePack。

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

支持 UTF-8 文本、Markdown、JSON、CSV 和 HTML。输入先持久化为 Evidence，再解析、理解和
评估。Provider 合同失败、未知二进制、低置信度、高风险或 Scope 不完整会保留候选而不是
直接激活。

## 6. 审批与恢复

默认摄取会进入 interrupt。使用相同 tenant/scope 恢复：

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
执行，过期、非 active、冲突或完整性不通过的知识不会被拼入答案。

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
