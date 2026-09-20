# 认识论拒答与 Knowledge Gap 验收报告

日期：2026-08-10  
版本：`0.3.0`  
Provider：受管 OpenAI-compatible `glm-5.2`  
边界：真实本地 HTTP API、真实 LLM、真实 Web Search、隔离 SQLite 状态库

## 目标与结论

本轮解决的不是普通内容审核，而是“当前证据无法支持正确理解时，Agent 必须承认不知道”。
最终实现会把无法可靠解释的经验保留为可检索、可研究、可补证和可版本化的 Knowledge Gap；
后续材料可以精确链接到对应 Gap，但只有补证候选经审批激活后才关闭它。

最终 AAWO Gate 通过，四项核心比率均为 100%：

| 指标 | 结果 |
|---|---:|
| 模糊经验正确拒答 | 3/3 |
| Gap 检索继续拒答 | 3/3 |
| 已有核心答案保留 | 1/1 |
| 后续证据精确回链并关闭 | 1/1 |

三个拒答领域为工业校准、口述史和农学；核心答案保留与回链旅程覆盖软件工程及专有设备术语。
跨租户读取被拒绝，关闭一个 Gap 不会误关无关 Gap。该结论是代表性能力 Gate，不是所有领域的
数学穷举，也不替代领域专家认证。

## 行为合同

1. Provider 同时返回 Experience candidates 与 Knowledge Gap candidates。
2. 应用层再次执行确定性证据闸门，低支持度、缺原文摘录或仍含关键未知项的结论不进入审批。
3. 每个 Gap 保存问题、未决原因、缺失证据、可能方向、查询、链接键、来源摘录和相关知识 ID。
4. 有限查询按 Gap 轮转分配，防止第一个 Gap 独占预算。
5. 搜索观察先写为不可变 Evidence；搜索摘要视为不可信线索，不自动进入 active Registry。
6. LLM reassessment 仍无法满足两个独立来源域与 0.75 置信度时，保持拒答。
7. 新候选通过 `resolves_gap_ids` 链接 Gap；拒绝候选不改变 Gap，批准激活后追加 `resolved` revision。
8. 检索仅命中 Gap 时返回 `abstained`；有可靠核心答案且仅存在外围 Gap 时返回
   `answered_with_gaps`。

Gap 状态包括 `open`、`research_exhausted`、`research_unavailable`、`partially_resolved` 和
`resolved`。API/SDK 可通过 `GET /v1/knowledge-gaps` 或 `list_knowledge_gaps()` 读取开放项。

## 真实研究链路

首次调用供应商结构化 Web Search 端点时，当前受管套餐返回 HTTP 错误，因此系统没有伪报搜索
成功，也没有退回模型记忆作答案；随后只读 DuckDuckGo HTML fallback 返回了真实标题、URL 与
摘要，LangGraph 相关查询取得 3 条观察并全部保存为 Evidence。错误只记录类型，不记录密钥或
鉴权头。

外发安全闸门允许 `public`/`internal` 材料按配置研究；`confidential`、`restricted`、`secret`、
`prohibited` 分类直接记录 `classification_egress_blocked`，不发送查询，Gap 仍保留等待本地或
后续授权证据。

## 纠正驱动测试记录

测试使用 `aawo-agent-tester` 的合同发现、真实 HTTP 执行、证据 ledger 与纠正回归流程。失败
记录被保留，没有用最终结果覆盖：

| 轮次 | 结果 | 主要发现 | 报告 SHA-256 | Ledger SHA-256 |
|---|---|---|---|---|
| 1 | 失败，9 项 | 低置信候选未被 Gap 完全替代；`no_results` 状态误分；已批准核心经验被复核规则再次拒答 | `E38F4BA578697D615C563CBB4820A498A218252DF917FCB9DCC14EB0415F5595` | `2C811D4A6C9C210862125C98784A1D982C7360F23DD0232AEB2EE40E8E914D6C` |
| 2 | 失败，3 项 | 查询预算分配不公平；正常风险 active Experience 的审批完成标记未参与检索；测试错误要求一次补证关闭所有外围 Gap | `6C1E94578CBC006F0A9BA68C3B474FCB63661B813209EDB89671B07D172447EA` | `D35FED8CE8AB668416F8947118D3DB4AC3FB608E1EEECCDB7F4E899211B2CA79` |
| 3 | 通过，0 项 | 四项核心比率均为 1.0，隔离与无关 Gap 保留通过 | `2D3724B4F8BB2F36D726F82E3147DEA95B6CD26633C0499DE8F61A73E3F1378F` | `5E94B6ADDB30C1312CC36BD6A169B21C2B848573FB21013CC376A85760A1B478` |

最终证据位置：

- `build/knowledge-gap-aawo-gate-20260810c/evidence/knowledge-gap-gate-report.json`
- `build/knowledge-gap-aawo-gate-20260810c/evidence/knowledge-gap-evidence-ledger.jsonl`

## 前端验收

亮色控制台新增紧凑的 **Knowledge gaps** 区域，默认最多显示 3 条。每条可展开查看问题、原因、
缺失证据、可能方向、研究次数、链接键与 Gap ID，并可一键带入检索。真实模糊样例在页面显示
`ABSTAINED / 1 OPEN GAP`；Knowledge library 继续默认仅显示 5 条紧凑 Experience，避免页面无限
增长。

## 已知边界

- 搜索摘要不是权威原文；生产环境应增加允许域、页面抓取、来源信誉和引用快照策略。
- `internal` 是否允许公网研究取决于组织策略；当前为满足本地研究旅程而允许，可通过
  `UKA_WEB_RESEARCH=0` 全局关闭。机密及更高分类始终失败关闭。
- 代表性领域通过不证明任意新术语一定被正确分类；低证据时应继续增加拒答，而不是追求零拒答。
- 生产使用仍需外部 IAM、审计、保留/删除策略、配额、成本与容量 Gate。
