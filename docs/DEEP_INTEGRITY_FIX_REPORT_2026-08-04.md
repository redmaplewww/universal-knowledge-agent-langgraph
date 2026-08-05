# `0.1.2` 深层完整性与隔离修复报告

日期：2026-08-04  
范围：F-017 / A-018 / G-005  
目标：纠正、checkpoint、Evidence、检索、冲突、Evolution 与 Parser 的失败关闭治理。

## 修复结果

- correction replacement 重新经过 preserve、parse、真实 Provider 理解、Scope/risk 分类；高风险结果不能由 `auto_approve` 绕过。
- correction 发布使用 active revision CAS；stale correction 与并发后发布者均不能覆盖当前 active revision。
- LangGraph checkpoint 使用 tenant、security scope 与公开 thread ID 的哈希 namespace；状态、恢复和事件读取必须携带完整安全上下文。
- Evidence 行、Locator、父 Evidence、对象文件或内容哈希任一不完整时，检索整体返回 `unknown`。
- FTS 候选先做 Scope/时效过滤和冲突检查，再应用最终 `limit`。
- 同一来源编号只在数量、否定极性或明确互斥值矛盾时产生冲突；兼容 Claim 不再误报。
- Evolution 不再相信请求中的 `passed` 布尔值，offline/shadow/canary 均须引用匹配候选且带完整 Evidence 的不可变 evaluation revision。
- Parser 超过 256 个 Fragment 时显式抛出 `FragmentLimitExceeded`，不再静默截断。
- 理解结果按 Evidence 哈希与 Provider revision 缓存，相同内容重复摄取不会因模型置信度漂移产生 revision 冲突。

## 纠正驱动测试

真实 HTTP/GLM Gate 保留了两次失败记录：

1. 首次 59/62：宽松来源冲突规则误判教育互补 Claim，重复摄取发生 revision 冲突。
2. 二次 60/61：冲突误判已关闭；重复摄取仍因真实模型输出置信度漂移失败。
3. 加入内容寻址理解缓存后，全新隔离状态第三次运行 62/62 通过。

最终 AAWO/真实 GLM 结果：

- 主客户旅程：62/62；十个代表领域分类 10/10；重复输入通过。
- alias：10/10。
- JSON/Markdown 结构化知识：6/6；关联错配 0。
- 来源编号检索：6/6。
- review-required 回答泄漏 0；混合 Scope 过宽 0；最终 EvidenceLedger 412 条且完整。
- 真实 correction：普通机械知识更正为医疗高风险内容时，即使 `auto_approve=true` 仍进入审批；批准后 active revision=2，检索为 `review_required / unknown / risk=high`；expected revision=1 的后续 stale correction 未激活。

## 发布证据

- Ruff、compileall、pytest：通过，44/44。
- wheel/sdist：构建通过。
- Python 3.11 洁净环境：49 个依赖安装、`pip check`、安装态 ingest/retrieve 通过。
- wheel：`dist/universal_knowledge_agent_langgraph-0.1.2-py3-none-any.whl`。
- wheel SHA-256：`57AA3198DA10E4B070078EBB26AF058911258C46767F010E32F02528BE442DF6`。
- 最终 Gate：`build/deep-integrity-gate-20260804c/evidence/`。

## 兼容性与边界

- revision、Evidence 和 active Registry 数据结构保持迁移兼容；`runtime_events` 自动增加 security scope 列。
- checkpoint key 从公开 thread ID 改为安全 namespace。`0.1.1` 及更早版本中未完成的 checkpoint 不自动迁移，需在升级前完成或由运维明确迁移。
- 本 Gate 是本地隔离产品验证，不等同外部 IAM、生产存储、容量、真实多模态或领域专家认证。
