# Kernel Foundation 规格

## 1. 配置

- 配置在启动阶段一次解析为不可变 Pydantic settings。
- 环境变量、secret file 和测试 override 的优先级必须显式；运行中不重新读取环境变量。
- 数据库与缓存连接参数拆分为独立字段（`AIYA_PG_HOST/PORT/USER/PASSWORD/DATABASE`、`AIYA_REDIS_HOST/PORT/DB/PASSWORD`），由代码组装 URL；显式 `AIYA_DATABASE_URL`/`AIYA_REDIS_URL` 覆盖优先。`production` 必须显式提供这两个 URL，禁止回退到本地默认端点；拆分字段仅供开发或特殊非生产部署。backend 不内管数据库，仅通过环境变量连接外部 PostgreSQL/Redis。
- secret 值禁止出现在 repr、日志、错误响应、OpenAPI example 或诊断输出。
- capability/provider 配置由所属包声明 schema，由组合根汇总；kernel 不维护业务配置 key。
- 必需配置缺失、未知安全枚举或相互冲突时启动失败。

## 2. 错误

通用错误至少包含：

- 稳定 `code`。
- 对外安全 `message`。
- HTTP 建议状态或 transport-neutral category。
- `request_id`/`trace_id`。
- 可选、可序列化且无 secret 的 details。

kernel 只定义 validation、conflict、not_found、unauthorized、forbidden、rate_limited、dependency_unavailable、internal 等类别。具体 `content.invalid_transition` 等 code 由 capability 拥有。

异常映射不得把堆栈、SQL、provider payload、token 或凭据返回给客户端。

## 3. 时间与 ID

- 持久时间全部为 UTC tz-aware datetime，数据库使用 `timestamptz`。
- 业务日、用户时区和过期窗口由调用方显式提供，禁止依赖主机本地时区。
- 所有可测试逻辑通过 `Clock` 获取当前时间。
- 默认实体 ID 使用 UUIDv7；协议要求随机不透明值时使用 CSPRNG，不把 UUID 误作 secret。
- 幂等键是调用方提供的稳定业务键，kernel 只校验长度、命名域和唯一性。

## 4. 序列化

- Service、Command、Query、Event、Workflow 边界使用 Pydantic DTO。
- 持久化 JSONB 必须绑定具体模型和 `schema_version`；禁止无约束 `dict[str, Any]` 作为长期状态。
- datetime、UUID、Decimal/整数金额和枚举的编码必须确定性。
- 未知字段的兼容策略由 DTO 版本明确，安全敏感输入默认拒绝未知字段。

## 5. 密码学与 secret 原语

kernel 可以提供：

- 密码哈希/校验 Port 与批准算法 adapter。
- 随机 token 生成、常量时间比较、digest 和签名/验签原语。
- KeyRef/KeyLoader/Signer Protocol。
- secret redaction 和轮换所需的无业务元数据类型。

kernel 不定义登录、OIDC token、scope、client 或用户凭据状态。算法参数必须可升级；持久 hash 携带算法版本，成功验证旧参数后是否 rehash 由 identity Command 决定。

## 6. 缓存

- cache 是可选 Port，不是事实来源。
- key 必须包含 namespace 和 schema version。
- 读缓存 miss 不得产生业务写入；填充缓存属于基础设施副作用且不得改变业务结果。
- 缓存不可用时，除明确的安全 fail-closed 场景外应降级到事实来源。
- 禁止使用进程锁或 Redis 锁替代数据库业务约束。

## 7. 验收

- fake Clock 能覆盖到期、重试和业务日测试。
- secret redaction 对嵌套 config/provider error 有测试。
- JSONB 无模型、naive datetime、浮点金额和非稳定枚举被架构/合同测试拒绝。
- 密码学测试包含算法版本、错误输入和常量时间比较接口。
