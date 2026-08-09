# 运维手册

## 1. 运行边界

`0.2.0` 是本地持久化产品：SQLite 领域库、SQLite checkpointer 和本地内容寻址对象库组成
可恢复链路。它适合单机开发、评测和受控内部使用，不等于生产集群部署。

生产化前必须明确：外部 IAM/RBAC、租户解析、PostgreSQL/对象存储、密钥托管、备份恢复、
保留与删除、审计、配额、SLO、容量、灾备和领域专家评测。

## 2. 目录与状态

项目根通常包含：

```text
.env.local       # 受管本机配置，禁止提交
.uka-state/      # 本地默认运行状态，禁止提交
domain.sqlite3   # SQLite 领域事实库（由状态目录管理）
objects/         # 内容寻址 Evidence 对象
checkpoints/     # LangGraph SQLite checkpoint
```

实际路径以 `Settings` 和 `UKA_STATE_DIR` 为准。测试、开发和生产必须使用不同的状态根。

## 3. 密钥与配置

- 通过 `llm-api-config` profile 管理 LLM Provider。
- 通过 `Inject` 写入 `.env.local`，不要手工把 Key 写入 Shell 历史、源码或 CI 日志。
- `doctor` 和 `doctor --connect` 只允许输出非秘密元数据、Provider revision、合同状态和
  延迟摘要。
- `.env.local`、构建产物、运行状态和 Evidence 数据不应进入公开 Git 仓库。
- CI 应使用平台 Secret/Environment，并限制 Key 的模型、域名、预算和有效期。

## 4. 启停与健康检查

启动：

```powershell
uv run uka-lg --project-root . serve --host 127.0.0.1 --port 8765
```

健康检查：

```powershell
uv run uka-lg --project-root . doctor
uv run uka-lg --project-root . doctor --connect
```

生产部署不要把开发服务直接暴露到公网；使用反向代理、TLS、身份认证、请求大小限制、
超时、速率限制和结构化审计。

## 5. 备份与恢复

### 备份原则

必须一致性备份以下三类数据：

1. SQLite 领域事实库和 active Registry。
2. SQLite LangGraph checkpoint。
3. 内容寻址对象库及其 hash/locator 元数据。

只备份 SQLite 而遗漏对象库会导致 Evidence 完整性校验失败关闭；只备份对象而遗漏 Registry
会丢失 active revision 和审计关系。

### 恢复校验

恢复后至少执行：

```powershell
uv run ruff check .
uv run pytest
uv run uka-lg --project-root <restored-root> doctor
```

然后用隔离 tenant/scope 执行摄取、审批、检索和跨租户负例。不要把恢复快照直接当成生产
切换完成；需要核对 hash、active revision、checkpoint namespace 和事件完整性。

## 6. 升级

升级前记录：Python 版本、包版本、`uv.lock` hash、Provider revision、状态目录快照和未完成
thread 清单。

```powershell
uv sync --dev
uv run pytest
uv run ruff check .
uv build
```

`0.1.1`/`0.1.2`/`0.2.0` 的领域 revision、Evidence 和 active Registry 设计为兼容；`0.2.0`
新增的 Experience 与 learning 字段使用可选 JSON payload，旧 Knowledge 仍可读取但不会伪造
缺失的逻辑关系或原文摘录；未完成的旧
checkpoint 不会自动迁移到新的 tenant/scope 安全 namespace，升级前应完成、拒绝或执行显式
运维迁移。

## 7. 观测与告警

事件账本只应保存脱敏的 ID、计数、状态、错误类型和时间信息。禁止记录：

- API Key、Authorization header、Cookie；
- 原始客户文本和完整模型响应；
- 未脱敏的个人信息；
- 可直接恢复秘密的环境变量。

生产建议额外记录并告警：Provider 错误率、结构化合同失败率、`review_required` 比例、
`unknown` 原因分布、Evidence 完整性失败、重复 Receipt、checkpoint 恢复失败、请求延迟、
Token/成本和队列/配额使用量。

## 8. 安全运行规则

- tenant/actor 不能只信任客户端输入；由网关或服务端身份系统派生。
- 所有 thread、retrieve、resume、correction 和 lifecycle 操作都必须校验 tenant/scope。
- 高风险和低置信知识保持人工审批；不能用 `auto_approve` 绕过生产策略。
- Skill 默认无网络、无权限、无副作用；生产执行能力必须单独隔离。
- Evolution 必须绑定不可变评测证据；候选不能自报指标后自动激活。
- 对外部输入执行大小、类型、编码和解析深度限制。

## 9. 发布检查清单

```powershell
uv run ruff check .
uv run pytest
uv run python -m compileall -q src
uv build
```

发布前还应：

- 检查 `git diff --check`；
- 确认 `.env.local`、`.uka-state`、`build`、`dist` 未被追踪；
- 执行一次隔离真实 Provider smoke（如本次发布需要）；
- 验证 `doctor --connect` 不泄露凭据；
- 验证 ingest → interrupt → resume → retrieve；
- 验证跨租户查询返回 `unknown`；
- 验证高风险知识返回 `review_required`；
- 记录版本、命令退出状态、报告路径和 hash。

## 10. 生产替换边界

应用层通过端口隔离 Parser、Provider、Repository 和 Object Store。生产适配应实现：

- PostgreSQL 或等价事务事实库；
- 对象存储和内容 hash 校验；
- 分布式 checkpoint/outbox/inbox；
- 外部 IAM、RBAC、租户与配额服务；
- 向量/图/词法混合检索和可解释重排；
- 多模态 Parser/Provider Adapter；
- 指标、追踪、告警、备份和灾备。

不要把领域层直接绑定到某个数据库、LangGraph 扩展或供应商 SDK。

## 11. 事件与事故处理

发现 Evidence 完整性失败、跨租户访问、线程越权、密钥泄露或 Provider 合同漂移时：

1. 立即停止相关写入或切换到离线 Provider。
2. 保留脱敏事件 ID、时间、版本、状态目录快照和 hash。
3. 隔离受影响 tenant/scope，不删除原始证据。
4. 用最小复现和回归测试确认修复。
5. 只有在离线回归、真实旅程和安全审计重新通过后再恢复写入。

## 12. 相关文档

- [用户手册](USER_MANUAL.md)
- [实现架构](IMPLEMENTATION_ARCHITECTURE.md)
- [LLM 配置与测试](LLM_CONFIGURATION_AND_TESTING.md)
