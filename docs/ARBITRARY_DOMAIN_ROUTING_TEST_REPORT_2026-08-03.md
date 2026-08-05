# 任意领域知识路由、分类与沉淀测试报告

## 结论

本次能力 Gate **未通过**。Agent 已能对独立、单领域、短文本知识完成语义分类、审批、持久化和检索，但当前不能可靠宣称“可正确路由任意领域知识并分类整理沉淀”。失败集中在分类治理和 Claim–Scope 绑定，不是 HTTP、LangGraph 或 SQLite 基础运行故障。

原有 `0.1.0` 合同回归仍为 27/27 通过；本报告新增的是更严格的任意领域可靠性合同。

## 测试边界

- 目标：本机真实 HTTP API `http://127.0.0.1:8876`，测试后已关闭。
- 状态：独立 fixture `build/arbitrary-domain-gate-20260803/state`，不接触既有运行数据。
- 模型：受管 OpenAI-compatible `glm-5.2`；密钥未读取、未输出、未写入证据。
- 执行层：`aawo-agent-tester` 的 `HttpAdapter`、`CustomerSimulationRunner` 与 append-only `EvidenceLedger`。
- 副作用：仅在隔离 fixture 中摄取、批准或拒绝测试知识。
- 输入：10 个独立领域、一个三领域纯文本、三领域 JSON、三领域 Markdown、提示注入、无意义文本、未知查询、跨租户查询和重复输入。

## 结果总览

| 检查 | 结果 |
|---|---:|
| AAWO HTTP 客户旅程 | 82 |
| 旅程通过 / 失败 | 75 / 7 |
| EvidenceLedger 记录 | 419 |
| Ledger 完整性错误 | 0 |
| 真实 LLM 理解调用 | 19 |
| 独立领域语义分类（修正多语言评测器后） | 10/10 |
| 使用模型实际生成的精确 Scope 标签检索 | 10/10 |
| 使用常见规范领域名检索 | 5/10 |
| 结构化源标识单独检索 | 4/6 |
| `review_required` 知识仍被直接回答 | 10/10，失败 |
| 混合纯文本 Claim 获得过宽 Scope | 3/3，失败 |
| Markdown Claim–Scope 证据错配 | 1 条，失败 |
| 原有项目回归 | 27/27 通过 |

最终隔离数据库沉淀了 15 个原始 Evidence、22 个派生 Fragment、26 个 Candidate、23 个 Scope、24 个 Active Knowledge。提示注入和无意义文本均进入人工门禁后被拒绝，没有生成 Active Knowledge。

## 通过项

1. 机械、财务、医疗、法律、软件、农业、教育、天体物理、物流、语言学十个独立事实都得到语义合理的领域分类。财务事实返回中文“财务与会计”；原英文关键词评测器因此产生一次假阴性，修订为多语言同义词后通过。
2. 每条独立知识均保留 Evidence、Fragment、Candidate、Scope、Knowledge 和 Active Registry 链路。
3. 使用数据库中实际生成的领域标签进行 Scope 检索时 10/10 命中；故意错误的 Scope、未知查询和跨租户查询均返回 `unknown`。
4. 提示注入与无意义文本没有绕过审批，拒绝后保持非 Active。
5. 重复输入没有返回 500；AAWO 旅程通过。
6. AAWO EvidenceLedger 的 419 条记录全部通过内容哈希复核。

## 主要发现

### F-ADG-01：`review_required` 未在检索端失败关闭（高）

十个独立领域 Scope 都因未知适用期、地域或其他前提被标记 `review_required=true`，但风险值不是 `high/prohibited` 时检索仍返回 `answered`。医疗急症事实还被模型标为 `risk=normal`。

原因定位：摄取评估会读取 `review_required`，但检索只检查 `risk in {high, prohibited}` 和冲突，未检查 Scope 的 `review_required` 字段。见 `src/uka_langgraph/application/services.py` 的摄取判断约第 260 行与检索判断约第 719、752 行。

影响：需要人工复核的知识可在激活后被直接作为答案返回，违反 Scope-first/fail-closed 目标。

### F-ADG-02：自由文本领域标签无法稳定路由（高）

模型可以输出 `Industrial Equipment Maintenance`、`财务与会计`、`Medical / Emergency Care` 等自由标签；检索 Scope 使用大小写不敏感的精确字符串相等。客户使用 `Mechanical Engineering`、`Finance`、`Medicine`、`Legal`、`Software Engineering` 时 5/10 返回 `unknown`。

原因定位：Provider 提示词没有受控领域本体或规范 ID；`_scope_matches` 对 `domain` 做精确值比较。

影响：分类看似合理，但下游无法用稳定类别进行路由、统计、权限策略或复用。

### F-ADG-03：混合纯文本被整理为过宽 Scope（高）

没有空行的三行纯文本只生成一个 Fragment。模型返回三个 Claim 和一个 `Mixed (Mechanical, Financial, Agricultural)` Scope，三个知识条目都继承全部领域、Subjects 和 Preconditions。

原因定位：PlainTextParser 只在空行处分块；一个 Fragment 内的多个 Claim 只共享一个 Scope。

影响：机械、财务和农业知识不能独立分类，Scope 过滤和适用条件被交叉污染。

### F-ADG-04：Markdown 标题产生伪 Claim，并出现 Claim–Scope 错配（高）

Markdown 标题 `Mechanical Maintenance` 和 `Financial Accounting` 被模型沉淀成“主题是……”的额外知识。后者被绑定到 Agriculture Scope，且 Knowledge 与 Scope 的 Evidence ID 无交集。

原因定位：MarkdownParser 把标题放入待理解文本；`compile_knowledge` 使用列表索引 `scope_ids[min(index, ...)]` 配对，而不是按共同 Evidence ID 绑定 Claim 与 Scope。

影响：混合结构化文档可能产生伪知识及跨领域错配。

### F-ADG-05：模型改写导致源标识丢失（中）

JSON 中 `JSON-FIN-22` 和 `JSON-AGRI-33` 被模型从 Claim 文本中移除。FTS 仅索引 Active Knowledge 内容，因此只使用原始 Evidence 标识检索时 2/6 返回 `unknown`。

影响：Evidence 仍可审计，但客户不能稳定用源编号找回知识。

## 建议的纠正驱动回归

1. 引入规范 `domain_id` 与多语言 alias 表；保留模型 `domain_label` 仅作展示。
2. Retrieval 将 `scope.review_required`、低置信、未知适用条件与风险统一纳入 fail-closed 决策。
3. PlainTextParser 增加句子/行级语义边界；每个 Claim 独立产生或绑定 Scope。
4. ClaimCandidate 和 ApplicabilityScope 增加显式 `association_id` 或通过 Evidence ID 一对一/一对多关联，禁止按列表索引配对。
5. Markdown 标题作为上下文元数据，不单独生成 Claim；增加 heading-only 负面测试。
6. FTS 同时索引受控源标识、Evidence locator/path 和规范别名，不只索引模型改写后的 Claim。
7. 增加医疗、法律、财务等高风险领域的确定性风险策略，不把风险完全交给通用模型判断。

## 证据

- `build/arbitrary-domain-gate-20260803/evidence/evidence-ledger.sqlite3`：SHA-256 `ABD24E05BF34568D38C410A6993C95DDB88220160575D6945EB34E9ED138D679`
- `arbitrary-domain-gate-report.json`：SHA-256 `6E584A58958DDDEE58AE360F238E933E8CF58EE4A012F180D51C65EFD0DD619E`
- `alias-regression-report.json`：SHA-256 `ED8387ABA38CB481051EB37DA816EE626DD3C8B318EB24B07CD9ECBBDEB5FCF2`
- `structured-domain-gate-report.json`：SHA-256 `181C287205CEA784060EC29E4DB802955377235F97C4AE396E7A58BC4AEDCC9F`
- `code-lookup-gate-report.json`：SHA-256 `D60B7655E034F49454CD128D7F3BEF6D0D1D1B09023AC3810D3700FA8729F024`

## 限制

- 代表性领域覆盖不能证明数学意义上的“全部任意领域”。
- 本轮是文本和结构化文本测试，不包含当前产品合同之外的图像、音频和视频。
- 领域判断是工程一致性测试，不是医疗、法律或财务专家认证。
- 本机隔离 HTTP fixture 不代表生产容量、外部 IAM 或集群可靠性。
