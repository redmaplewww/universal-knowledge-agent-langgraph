# 批次聚类与跨学科知识图谱实现报告

版本：`0.4.0`

日期：2026-09-19

## 结论

系统已经从“按词条保存和检索”扩展为“按比例重复抽样、LLM 聚类、跨学科探索、图谱索引和图谱辅助检索”。聚类输出仍是可追溯的索引假设，不会绕过 Evidence、Scope、Knowledge Gap、人工审批和版本治理成为事实。

## 入库阶段的领域判别

每个 Scope 除了最终 `domain_ids`，现在还保存按概率排序的 `domain_hypotheses`：

- `domain_id`：受控 taxonomy 中的稳定领域 ID；
- `probability`：该领域的潜在可能性；
- `rationale`：模型选择该领域的依据；
- `missing_information`：要进一步确认该领域还缺什么信息。

这使系统可以同时表达“当前主分类”和“潜在交叉领域”，而不是只保存一个扁平标签。

## 批次比例采样

每轮最多抽取 64 条 active knowledge，默认批次为 24 条，分为四个采样桶：

| 采样桶 | 默认比例 | 作用 |
|---|---:|---|
| 领域覆盖 | 40% | 轮询不同主领域，避免大领域吞没小领域 |
| 信息缺失 | 30% | 优先抽取 Scope 低置信、未知项多、关联 Gap 多的知识 |
| 跨学科桥接 | 20% | 优先抽取多领域或多个领域概率接近的知识 |
| 关键知识重采样 | 10% | 让证据、逻辑关系和置信度较强的知识跨轮次重复参与聚类 |

当批次容量不小于正比例桶数量时，每个采样桶至少保留一条，避免小批次把 10% 重采样比例舍入为零。采样次数、最近采样时间、缺失分、潜在领域分、关键度和综合优先级均持久化。

## 聚类与涌现

LLM 每轮接收受限的知识摘要、领域候选、逻辑关系、采样信号和相关 Knowledge Gap，返回：

- 聚类名称、摘要、成员和关键词；
- 聚类级领域概率与缺失信息；
- 跨领域程度与聚类置信度；
- 知识之间的 `supports`、`requires`、`enables`、`analogous_to`、`applies_to`、`bridges` 等边；
- 值得继续补证的跨学科探索问题。

模型只能引用本批次中真实存在的 knowledge ID 和受控领域 ID。未知 ID、非法关系和自环边会在 Provider 合同层被过滤。如果模型形成了多成员聚类但漏掉语义边，系统会基于该聚类成员关系生成 `bridges` 或 `shares_domain_context` 索引边，并明确标注“用于检索扩展，不是新的事实断言”。

每个聚类还会生成三项可解释排序信号：`missing_score` 汇总聚类和领域候选中的缺失信息，
`potential_score` 表示领域概率的熵与剩余不确定性，`priority_score` 按 45% 信息缺口、35% 潜在
领域、20% 跨域程度合成。列表按综合优先级降序返回。探索问题若模型漏给 priority，不再静默
落为 0，而是根据缺失证据、关联知识数量和领域不确定性推导一个保守非零值。

## 知识图谱

图谱包含四类主要节点：

- `knowledge`：已激活知识；
- `domain`：受控领域；
- `cluster`：版本化聚类索引；
- `knowledge_gap`：待补证问题。

主要边包括：

- `belongs_to_domain`：知识到领域；
- `member_of_cluster`：知识到聚类；
- LLM 或聚类派生的知识语义边；
- `has_open_gap`：知识到开放缺口。

每条聚类语义边保存 `run_id`、Provider revision、置信度、理由和支持它的 knowledge ID。所有表均绑定 tenant 与 security scope。

## 图谱辅助检索

FTS 仍然负责第一阶段精确召回。系统只从前几个 FTS 种子沿置信度不低于 0.75 的图谱边扩展邻居，然后重新执行 Scope、时间、风险、冲突和 Evidence 完整性检查。图谱不能绕过现有检索门禁，也不会把低置信探索问题直接拼进答案。

## 自动与手工运行

- `UKA_CLUSTERING_ENABLED=true`：开启自动聚类，`Settings.load` 默认开启；
- `UKA_CLUSTER_AUTO_EVERY=12`：累计至少 12 条从未参与聚类的新知识后自动运行；
- `UKA_CLUSTER_BATCH_SIZE=24`：自动聚类批次大小；
- `UKA_LLM_TIMEOUT_SECONDS=120`：完整结构化理解和聚类的模型超时；
- `uka-lg cluster ...`：手工触发；
- `POST /v1/clustering/runs`：HTTP 触发；
- `GET /v1/clusters`：读取聚类；
- `GET /v1/knowledge-graph`：读取完整图谱。

## 测试证据

### 离线回归

- 65/65 pytest 全部通过，Ruff、compileall 和 `git diff --check` 通过；
- 比例采样四桶覆盖；
- 小批次每个正比例桶至少一条；
- 关键知识跨轮次重复采样；
- 聚类、成员、边、探索问题和采样统计持久化；
- 聚类优先级降序、旧数据库补列迁移、探索问题非零优先级和多 seed SQL 占位符通过；
- 高置信图谱邻居参与检索；
- 自动聚类阈值；
- 手工聚类 Provider 超时返回脱敏 `failed / clustering_failed` 终态，不泄露上游响应；
- Provider 合同过滤未知 ID 和非法关系；
- SDK、HTTP 和跨租户隔离。

### 真实 LLM Gate

受管 `glm-5.2` 在隔离状态库中完成 8 条跨域知识、两轮真实聚类和排序检查：

- 13/13 检查通过；
- 8/8 active knowledge 含领域候选概率；
- 4 条批次仍覆盖 coverage、uncertainty、bridge、replay 四个采样桶；
- 关键知识第二轮重复抽取，最大持久采样次数为 2；
- 最终图谱含 27 个节点、32 条边、6 个聚类和 6 个探索方向；
- 6 个聚类优先级按 `0.923927` 到 `0.741256` 降序；
- 6 个探索优先级为 `0.55` 到 `0.8`，无 0 值；
- 报告 SHA-256：`1c9cba80b9d88ba72f3e2accb2d6b2ff10977cf87c060f079b8ea0ec98ae355e`。

本轮第一次 hybrid 尝试中，真实 LLM 入库先成功，但 8 条聚类在 180 秒后返回
`APITimeoutError`。该失败没有改写为通过，并促成两项修复：手工聚类失败现在以脱敏终态返回，
Gate 状态库按输出目录隔离且支持小批次重试。此前固定 45 秒超时失败也继续保留。DeepSeek
`deepseek-v4.1-flash` 在本功能周期的外部配置检查仍为 `AuthenticationError`，没有宣称通过。

### AAWO HTTP Gate

纠正后的真实 HTTP 客户旅程 4/4 通过：

- 服务健康与自动聚类配置；
- 完整图谱读取；
- 真实 LLM 聚类 POST；
- 跨租户图谱隔离。

Evidence Ledger 共 20 条记录；最终报告 SHA-256：
`fe16d86043a9619cb9855c372165ea758e13fdca8c412a218da3ffda49389716`。本轮首次 AAWO
运行保留为 3/4：健康、真实 LLM 聚类和租户隔离通过，图谱读取仅因测试器按 Python 文本表示
检查 JSON 双引号而失败；失败报告 SHA-256：
`4ec8ff69b1fe83fbd1dc6b162a35d7ecc425e4923f30284972bd421e965d6341`。修正为稳定字段断言后
4/4 通过。更早一次因测试环境关闭自动聚类而失败的报告也继续保留。

### 构建与洁净安装

- `uv lock` 已把项目版本同步为 `0.4.0`；
- wheel SHA-256：`cd366e0d43bd30a0f2a6e3d9be27c35bb174872c2db3b5b1b3807ae3a8ae151a`；
- sdist SHA-256：`6fe7e812e56e1e284cd2ae67f4ec1c5b4e3517ff241374f5626828c0fa02b724`；
- Python 3.11 洁净环境安装 52 个兼容包，包版本和 graph version 均为 `0.4.0`，`uv pip check` 通过。

## 仍然不宣称的能力

- 聚类和知识图谱不等于领域专家认证；
- 聚类边不自动成为事实或可执行 Skill；
- 当前使用 SQLite 本地图谱表，不宣称图数据库集群、高可用或生产容量；
- DeepSeek 配置恢复鉴权前，不能宣称该模型的本次真实 Gate 通过。
