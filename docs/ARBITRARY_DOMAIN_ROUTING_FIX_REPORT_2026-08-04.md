# 任意领域路由、分类与沉淀修复报告

日期：2026-08-04  
发布版本：`0.1.1`  
结论：上一轮 E-012 暴露的五类可靠性问题均已修复，纠正回归 Gate 通过。

## 修复内容

1. 引入稳定的受控领域 ID、跨语言 alias 与确定性风险下限；保留模型原始领域标签作为展示信息。
2. Candidate 与 Scope 通过显式 `scope_ids` 和共享 Evidence 绑定；关联缺失或歧义时失败关闭，不再按列表位置配对。
3. 纯文本按非空行拆分 Claim；Markdown 标题只作为定位上下文，不再被错误沉淀为独立知识。
4. 检索同时执行 `risk`、`review_required`、冲突和租户/安全域门禁，需复核知识不再直接回答。
5. 原始来源编号进入 Candidate、Knowledge 与 FTS 文档；精确编号查询优先匹配标识，避免 OR 检索产生跨知识误命中。
6. 保持旧 payload 兼容：历史自由领域标签在查询时规范化，无需破坏性数据库迁移。

## 验证结果

| 验证面 | 结果 |
|---|---:|
| 真实 GLM + HTTP 主客户旅程 | 62/62 通过 |
| 中英文/规范领域别名回归 | 10/10 通过 |
| JSON/Markdown 结构化摄取 | 6/6 知识分类正确 |
| Candidate–Scope 关联审计 | 0 错配 |
| 来源编号保留与精确检索 | 6/6 通过 |
| `review_required` 直接回答泄漏 | 0 |
| 混合文档 Scope 过宽 | 0 |
| EvidenceLedger 完整性 | 445 条记录，0 完整性错误 |
| 离线单元/集成测试 | 32/32 通过 |
| Ruff、compileall、依赖一致性 | 全部通过 |
| wheel/sdist 与洁净安装 | 通过，安装态版本 `0.1.1` |

真实 LLM 使用本机 `llm-api-config` 管理的 `glm` profile（OpenAI-compatible，模型 `glm-5.2`）。测试过程只使用脱敏配置状态，未读取、记录或输出密钥。

## 证据

- 主 Gate：`build/arbitrary-domain-gate-20260804d/evidence/arbitrary-domain-gate-report.json`，SHA-256 `A0638BB165DC8DB9663E52CF4BACDFC0A6426E194937B48EEA10812D55CCFFA2`
- 别名回归：`build/arbitrary-domain-gate-20260804d/evidence/alias-regression-report.json`，SHA-256 `D65309EB349430DF5F9EBA6C19ED3CFDA892A504A69C81D8403852AE2900B4F4`
- 结构化输入：`build/arbitrary-domain-gate-20260804d/evidence/structured-domain-gate-report.json`，SHA-256 `F11D114431B4ACFA365180C6E85745A4809159B544765420A66CFB667A2A2525`
- 编号检索：`build/arbitrary-domain-gate-20260804d/evidence/code-lookup-gate-report.json`，SHA-256 `BBBFC0413600490858D18F2137AA4F529849480D40EF4E55CC30C876B8535DA4`
- AAWO EvidenceLedger：`build/arbitrary-domain-gate-20260804d/evidence/evidence-ledger.sqlite3`，SHA-256 `53934F29F9BC5E4C300CB23A092C4699E87FB33B62E0D56FD58A09D85E38693A`
- wheel：`dist/universal_knowledge_agent_langgraph-0.1.1-py3-none-any.whl`，SHA-256 `26BE4314E8B50FDF150BB14FCE80A4B8C3CA899D2075BA9FAFEC31E688CF7743`

## 边界

本次 Gate 证明的是代表性开放领域、混合输入、危险输入、隔离、重复摄取和可追溯检索合同已经满足；它不等同于对数学意义上的“所有领域”逐一穷举，也不替代生产 IAM、外部存储、容量压测、真实多模态与各领域专家认证。

该实现仍位于独立目录 `universal-knowledge-agent-langgraph`，未导入、复用或修改旧 `universal-knowledge-agent` 的产品代码和状态。
