# `0.1.2` 实现架构

```text
interfaces -> orchestration -> application -> domain
                 |                 ^
                 v                 |
            infrastructure --------+
```

- `domain` 只使用 Python 标准库，定义 Evidence、Claim、Scope、revision 和 EvidencePack。
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
      -> Send understand fan-out -> Scope/evaluate
      -> interrupt approval -> active Registry + FTS projection
```

支持 plain text、Markdown、JSON、CSV 和 HTML。未知二进制、任一 Provider 合同失败、低
置信、高风险或 Scope 不完整都会失败关闭；并发分支只写带 reducer 的 ID/warning/error。

## 检索与回答

检索在一个受控查询中绑定 tenant、security scope、active revision 和 FTS，再由应用层过滤
Scope、valid_from/valid_until、风险与开放冲突。输出 EvidencePack，包含 knowledge revision、
Scope、Evidence hash、父 Evidence 和精确 Locator。冲突或高风险结果返回
`review_required`/`unknown`，不会拼成确定答案。

## 纠正、Skill 与进化

- 纠正锁定 expected revision，追加 Correction、ImpactSet、RegressionCase 和新 Knowledge
  revision，审批后只移动 active Registry 指针。
- Skill 编译真实 `SKILL.md` 与 manifest 内容寻址制品，默认权限为空、网络拒绝，只执行无
  副作用静态/advisory sandbox 检查，审批后激活。
- Evolution 依次经过 offline、shadow、canary 和人工审批；安全指标回退立即拒绝。

## 持久化与恢复

LangGraph SQLite checkpointer 保存 thread 状态与 interrupt；SQLite Domain Store 保存事实、
Registry、Receipt、FTS 投影和脱敏 runtime event。checkpoint 不是事实源。恢复时节点先查询
Receipt，避免重复创建 revision 或重复移动 Registry。

## 生产替换边界

本版本是本地完整产品，不声称生产集群已部署。生产环境应通过现有端口替换 PostgreSQL、
对象存储、pgvector/图数据库、分布式 outbox/inbox、外部 IAM 和监控；真实多模态解析器也
应作为新的 Parser/Provider Adapter 加入，不能把领域对象绑定到供应商 SDK。
