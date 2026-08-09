# 上下文经验沉淀与受治理自进化报告

日期：2026-08-10
版本：`0.2.0`
目标：修复逐句机械拆解，验证原文逻辑、综合理解、可检索展示和知识驱动的后续演进。

## 实现结论

- LangGraph 不再对每个 Fragment 单独调用模型；Fragment 只保留 Locator，理解按父 Evidence
  还原为完整文档后执行。
- Knowledge payload 升级为 Experience v2，保存标题、背景、问题、机制、行动、结果、理解依据、
  注意项、原文摘录和显式逻辑关系。
- `GET /v1/knowledge` 与 EvidencePack 同时返回模型理解和真实 Evidence excerpt，用户可以直接
  对照，而不是把原文复制品误当成经验。
- 新材料会检索相关 active Knowledge 作为受限先验；模型输出或相同来源编号可建立
  `derived_from_knowledge_ids`。`refines/reinforces/contradicts` 只生成 Evolution candidate，
  `automatic_activation=false`，且必须经过 offline、shadow、canary、human Gate。

## 真实模型与 AAWO 证据

受管 LLM 配置：`openai-compatible:glm-5.2`。`doctor --connect` 返回 `status=ok`，凭据未进入
日志、报告、源码或 Git。

最终 AAWO HTTP Gate：

| 项目 | 结果 |
|---|---|
| Adapter | 真实 `HttpAdapter`，目标 `127.0.0.1:8882` |
| 客户边界 | ingest → interrupt → approve → library → retrieve → refinement |
| 领域 | 网络安全、财务、机械工程、教育 |
| 最终状态 | `pass` |
| 检查项 | 20/20 通过 |
| EvidenceLedger | 115 条 |
| Ledger 完整性错误 | 0 |
| 报告 SHA-256 | `0955737EA96E70D0F0AC277A40EEE7F7A920044BE8D9228F2F0A62ED205BB437` |
| 本地证据 | `build/contextual-experience-gate-20260810d/evidence/` |

通过项包括：真实模型连接、单一上下文 Experience、逻辑关系、原文对照、EvidencePack、线程
顶层 `thread_id`、知识复用、`refines` 谱系、Evolution candidate 不激活、跨租户隔离，以及
4 个领域的分类、沉淀和带领域检索。

## 纠正驱动回归

第一次 AAWO 运行保留为失败证据：

- 报告 SHA-256：`3310BE5ED4F0D44A0CE8F3C17F47CDB6E9C7D347899EEF49199F3F279BD6E91`
- Ledger：52 条，完整性错误 0。
- 失败 1：测试错误地要求高风险知识返回 `answered`；实际系统正确返回
  `review_required`，同时保留 EvidencePack 供审阅。
- 失败 2：批准响应中的 `evolution_ids` 只位于 `response` 内，没有进入顶层线程状态。

修正后：检索断言接受并验证 fail-closed 语义；WorkflowState 新增顶层 `evolution_ids`。第二轮
报告 SHA-256 `A90617CA7C41B93751598820C3329E6D106BB7A5A913E44438FBD66D4C258EE2`，
50 条 Ledger、全部检查通过。随后扩展为最终 4 领域 Gate。

## 离线与前端验收

- `uv run pytest -q`：47/47 通过。
- `uv run ruff check src tests scripts/run_contextual_experience_gate.py`：通过。
- `node --check frontend/app.js`：通过。
- 浏览器真实连接 `127.0.0.1:8890` / API `127.0.0.1:8877`：7 条 Experience v2 可见。
- 浏览器筛选“形成性测验”后只显示 1 条；点击“用这条经验检索”自动填入
  `EDU-FBK-58` 和 `education`，返回 `ANSWERED / 1 EXPERIENCE`。
- 原文 Evidence 可展开，内容与 `EDU-FBK-58` 原材料一致；浏览器控制台错误为 0。

## 非声明范围

本报告证明隔离本地环境、代表性领域和真实 LLM 客户旅程通过，不等同于所有可能领域的数学
穷举、领域专家认证、生产 IAM、容量、灾备或外部存储认证。Evolution 的自动激活被明确禁止；
生产策略替换仍需要不可变评测证据和四阶段 Gate。
