# LLM 配置与测试

项目通过 `llm-api-config` 管理本机配置。配置流程不得在终端参数、源码、日志或对话中出现
API Key：

1. 用技能的 `Status` 查看不含密钥的 profile 元数据；
2. 用 `Inject -Profile <name> -TargetPath <项目根> -EnvStyle auto` 写入受管 `.env.local`；
3. 运行 `uka-lg doctor --connect`，只检查连接、JSON 根合同、provider revision 和延迟；
4. 用隔离 tenant/security scope 摄取无敏感测试样例，并在人工审批中断后检查 Claim、Scope、
   Fragment Locator 和 EvidencePack；
5. 日志只保存错误类型、ID、计数和状态，不保存鉴权头、输入全文或模型原始响应。

配置完整时 `UKA_USE_LLM=auto` 会使用真实 Provider。离线回归设置 `UKA_USE_LLM=0`，确保
测试不产生费用且可确定性复现。模型、URL 和密钥始终从环境变量读取。

## Knowledge Gap 的模型与网络测试

`0.3.0` 在首次理解后增加一次受限 Web Search 与 LLM reassessment。默认
`UKA_WEB_RESEARCH=auto`：真实 LLM 可用时启用，离线 Provider 时禁用。可用以下变量收紧预算：

```powershell
$env:UKA_WEB_RESEARCH = "1"
$env:UKA_WEB_SEARCH_COUNT = "5"
$env:UKA_WEB_SEARCH_MAX_QUERIES = "4"
$env:UKA_WEB_SEARCH_TIMEOUT_SECONDS = "20"
```

优先使用配置模型供应商的结构化搜索端点；不可用时退回只读搜索结果页。搜索摘要按不可信观察
处理，先保存为 Evidence，再交给模型复核；不能仅凭一个摘要形成确定知识。研究生成的补证结论
至少要求两个独立来源域且置信度不低于 0.75。

真实测试应同时覆盖：模糊经验拒答、Gap 可检索、已有核心答案不被外围 Gap 抹掉、补证候选
在拒绝后不关闭 Gap、批准后精确关闭、跨租户隔离，以及机密分类零公网调用。AAWO 脚本：

```powershell
uv run --no-sync python scripts/run_knowledge_gap_gate.py `
  --base-url http://127.0.0.1:8884 `
  --output-dir build/knowledge-gap-aawo-gate/evidence
```

脚本必须指向真实 HTTP 边界和真实 LLM 服务；最终报告与 JSONL ledger 都应保存 SHA-256。
