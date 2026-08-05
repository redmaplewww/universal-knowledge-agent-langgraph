# LLM 配置与测试

项目通过 `llm-api-config` 管理本机配置。配置流程不得在终端参数、源码、日志或对话中出现
API Key：

1. 用技能的 `Status` 查看不含密钥的 profile 元数据；
2. 用 `Inject -Profile <name> -TargetPath <项目根> -EnvStyle auto` 写入受管 `.env.local`；
3. 运行 `uka-lg doctor --connect`，只检查连接、JSON 根合同、provider revision 和延迟；
4. 用隔离 tenant/security scope 摄取无敏感测试样例，并在人工审批中断后检查 Claim、Scope、
   Fragment Locator 和 EvidencePack；
5. 日志只保存错误类型、ID、计数和状态，不保存鉴权头、输入全文或模型原始响应。

配置完整时 `UKA_USE_LLM=auto` 会使用真实 Provider。离线回归设置 `UKA_USE_LLM=0`，确保
测试不产生费用且可确定性复现。模型、URL 和密钥始终从环境变量读取。

