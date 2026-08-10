# `0.3.0` 实现架构

```text
interfaces -> orchestration -> application -> domain
                 |                 ^
                 v                 |
            infrastructure --------+
```

- `domain` 只使用 Python 标准库，定义 Evidence、Experience candidate、LogicalRelation、
  Scope、Knowledge Gap、revision、Web Search observation 和 EvidencePack。
- `application` 只面向 Parser、Provider、Repository、Object Store 端口；副作用携带稳定
  `operation_id` 并生成 Receipt。
- `infrastructure` 提供 Parser Registry、内容寻址对象库、SQLite Registry/FTS/Event
  ledger 和 OpenAI-compatible Provider。
- `orchestration` 是唯一导入 LangGraph 的业务层。State 只保存引用、控制字段和小型输出。
- `interfaces` 提供 SDK、CLI 和 FastAPI，原始输入先进入对象库，图只接收 `input_refs`。

## 摄取链路

```text
stage -> preflight -> preserve original Evidence
      -> detect/parse -> derived Fragment Evidence + Locator
      -> regroup by parent Evidence -> document-level understanding
      -> Experience / Knowledge Gap + LogicalRelation + Scope/evaluate
      -> bounded web research + LLM reassessment
      -> abstain, or interrupt approval -> active Registry + expanded FTS projection
```

支持 plain text、Markdown、JSON、CSV 和 HTML。解析分片不会触发逐片模型理解；服务层按
`parent_evidence_id` 还原原始文档，一次性向 Provider 提供全文。Provider 返回自包含经验、
原文摘录与 `causes/condition/sequence/contrast/exception/supports/enables` 关系，服务层再把
摘录匹配回精确 Fragment。匹配失败时保守绑定整组 Evidence，不伪造句级精度。

未知二进制、任一 Provider 合同失败、低置信、高风险、Experience 缺少上下文/依据/原文摘录
或 Scope 不完整都会失败关闭；并发分支只写带 reducer 的 ID/warning/error。

### 认识论拒答与补证闭环

应用服务把 Provider 返回的候选再经过确定性证据闸门。低支持度、缺少原文摘录或带明确未知
边界的结论会被降为 `KnowledgeGapCandidate`。每个 Gap 使用稳定 ID 保存问题、原因、缺失证据、
可能方向、研究查询与 `linking_keys`。网络研究最多按轮次公平分配有限查询，搜索结果先作为
不可变 Evidence 保存，再由 LLM 二次评估；搜索摘要仅是不可信线索，不自动成为 active Knowledge。

研究生成的结论至少需要两个独立来源域且置信度不低于 0.75。仍无可靠结论时图以
`abstained` 结束，同时把 Gap 写入版本库。后续候选的 `resolves_gap_ids` 会进入审批上下文；
只有批准激活节点才追加 `resolved` revision，并记录 `resolved_by_knowledge_ids`。拒绝候选不会
关闭 Gap。`confidential`、`restricted`、`secret`、`prohibited` 分类在研究层失败关闭，查询不外发。

## 检索与回答

检索在一个受控查询中绑定 tenant、security scope、active revision 和 FTS，再由应用层过滤
Scope、valid_from/valid_until、风险与开放冲突。FTS 投影覆盖标题、综合内容、背景、问题、
机制、行动、结果、依据、注意项、原文摘录和来源编号。输出 EvidencePack，包含 Experience、
Scope、原文 excerpt、Evidence hash、父 Evidence 和精确 Locator。冲突或高风险结果返回
`review_required`/`unknown`，不会拼成确定答案。查询命中开放 Gap 而无足够 active Knowledge 时
返回 `abstained`；已有可用核心答案但仍存在相关外围 Gap 时返回 `answered_with_gaps`，EvidencePack
同时携带 Knowledge Gap 摘要。

## 纠正、Skill 与进化

- 纠正锁定 expected revision，追加 Correction、ImpactSet、RegressionCase 和新 Knowledge
  revision，审批后只移动 active Registry 指针。
- Skill 编译真实 `SKILL.md` 与 manifest 内容寻址制品，默认权限为空、网络拒绝，只执行无
  副作用静态/advisory sandbox 检查，审批后激活。
- 每次文档理解前先检索同 tenant/scope 的相关 active Knowledge，并把最小 Experience 视图作为
  fallible prior knowledge 注入 Provider。显式来源编号还会形成确定性 lineage。
- `reinforces/refines/contradicts` 会创建不可自动激活的 Evolution candidate，记录 baseline
  knowledge IDs 和 candidate knowledge ID；正式 Evolution 仍依次经过 offline、shadow、
  canary 和人工审批，安全指标回退立即拒绝。

## 持久化与恢复

LangGraph SQLite checkpointer 保存 thread 状态与 interrupt；SQLite Domain Store 保存事实、
Registry、Receipt、FTS 投影和脱敏 runtime event。checkpoint 不是事实源。恢复时节点先查询
Receipt，避免重复创建 revision 或重复移动 Registry。

## 生产替换边界

本版本是本地完整产品，不声称生产集群已部署。生产环境应通过现有端口替换 PostgreSQL、
对象存储、pgvector/图数据库、分布式 outbox/inbox、外部 IAM 和监控；真实多模态解析器也
应作为新的 Parser/Provider Adapter 加入，不能把领域对象绑定到供应商 SDK。
