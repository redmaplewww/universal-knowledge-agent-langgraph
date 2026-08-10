# 项目版本

## 当前版本

- 版本号：`0.3.1`
- 发布状态：本地功能、真实 LLM Gate、wheel/sdist 构建与洁净安装验证全部通过
- 兼容性说明：Python 3.11+；LangGraph 1.2；与旧 `uka` 包无运行时兼容或导入关系；
  Experience v2、`approval_context`、Knowledge Gap 与人工补证请求使用向后兼容字段，旧 Knowledge 可读取；0.1.1 及更早的未完成
  checkpoint 不自动迁移到安全 namespace。
- 最后更新：2026-08-11

## 下一版本计划

- 目标版本：待生产目标明确后另行规划。
- 可选内容：生产存储与身份认证、多模态、混合检索、容量与领域专家评测。
- 进入条件：用户明确生产环境、数据边界、SLO 和部署目标；不得把本地 Gate 等同于生产认证。

## 版本历史

- `0.3.1`｜2026-08-11｜精确人工补证与中文一致性修复｜专用 Gap 补证 API/SDK/内联表单、
  target Gap 上下文优先注入、未解决项追加 revision、审批后关闭、来源语言提示、中文字段检测与
  受限修复、中文领域/状态展示｜用户指出缺口无法人工填补且中文对话出现英文缺口｜仅新增接口和
  可选 payload，不需要数据库破坏性迁移；旧英文演示 Gap 以追加 revision 本地化｜E-022｜G-009 通过。

- `0.3.0`｜2026-08-10｜认识论拒答与补证版本｜Knowledge Gap 版本对象、有限真实 Web Search、
  LLM reassessment、`abstained`/`answered_with_gaps`、后续证据精确回链、开放 Gap API/SDK/前端账本、
  机密外发阻断｜用户要求无法可靠理解时保留可能方向并支持后续注入链接｜SQLite payload/API
  向后兼容，无破坏性迁移；Python 3.11+、LangGraph 1.2.10｜E-021｜G-008 通过。
- `0.2.1`｜2026-08-10｜审批决策可见性与紧凑知识库｜授权响应动态解析候选 Experience、Scope、
  Evidence/Locator、风险和决策效果；明亮审批决策单、固定动作栏、默认 5 条紧凑知识行、单条展开、
  分页显示更多与移动端无横向溢出｜用户指出审批信息不足且知识库页面过长｜API 只新增
  `approval_context`，不改变 checkpoint/SQLite；旧客户端可忽略该字段｜E-020｜G-007 通过。
- `0.2.0`｜2026-08-10｜文档级上下文 Experience 与受治理自进化｜原文逻辑绑定、综合理解、
  原文对照、扩展 FTS、Knowledge library、EvidencePack Experience、active Knowledge 先验、
  确定性来源谱系与 Evolution candidate Gate｜用户明确要求修复机械拆解并让知识优化后续工作｜
  领域 revision/SQLite 向后兼容；API 仅新增字段和顶层 thread/evolution IDs｜E-019｜G-006 通过。
- `0.1.2`｜2026-08-04｜深层完整性与隔离修复版｜correction 全链路重分类与 active CAS、checkpoint 安全 namespace、Evidence 哈希失败关闭、过滤后 limit、保守冲突检测、Evolution 不可变评测证据、Parser 显式超限、内容寻址理解缓存｜用户要求继续检查并开始修复｜领域数据兼容；未完成 checkpoint 需显式迁移；Python 3.11+、LangGraph 1.2.10｜E-014｜G-005 通过；不等同生产 IAM/容量/专家认证。
- `0.1.1`｜2026-08-04｜任意领域可靠性纠正版本｜受控领域 ID/alias、确定性风险下限、Claim–Scope 显式 Evidence 绑定、混合文档细粒度解析、`review_required` 检索失败关闭、来源标识精确索引｜G-003 暴露五类能力缺口后用户授权修复｜与 0.1.0 payload/SQLite 数据向后兼容，无破坏性迁移；Python 3.11+、LangGraph 1.2.10｜E-013｜G-004 通过；不等同生产基础设施或领域专家认证。
- `0.1.0`｜2026-08-03｜本地完整产品 Gate 通过｜Parser Registry、FTS EvidencePack、真实 GLM、SDK/API、完整治理、观测、wheel/clean-install E2E｜用户要求完整落地并使用 Skill 配置 LLM 测试｜Python 3.11+、LangGraph 1.2.10；与旧 AAWO 工程隔离｜E-008..E-011｜G-002 通过；不宣称生产基础设施或专家质量认证。
- `0.1.0.dev0`｜2026-08-03｜P0 检查点通过｜独立 LangGraph Root/五子图、SQLite 事实库与 checkpoint、Evidence/Receipt、interrupt/resume、CLI、离线与可选模型 Provider｜用户明确要求独立实现｜不兼容且不依赖旧 AAWO 编排；Python 3.11+、LangGraph 1.2.10｜E-002..E-006｜G-001 通过；不代表 P1-P4 或生产就绪。
