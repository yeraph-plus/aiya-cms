# 装配与生命周期规格

## 1. 唯一组合根

`inc/api` 是唯一组合根。它选择本部署启用的能力和功能、创建依赖容器、绑定 Port、挂载 HTTP router，并控制 dispatcher/scheduler/worker 生命周期。

kernel、capability 和 feature 都不得读取环境后自行把自己挂入应用，也不得依赖 Python entry point、目录扫描或 import side effect。

## 2. 声明对象

### 2.1 CapabilitySpec

每个 capability 导出一个不可变声明，至少包含：

- 稳定 `name` 和 `schema_version`。
- 自有 tables/migration owner。
- commands、queries、events 和 error codes。
- activities、event handlers、Cron 声明。
- 所消费的 Port 与所提供的 adapter factory。
- diagnostics、metrics 和 admin readmodel providers。
- 可选 routers 与所需 access capabilities。

声明只包含类型、工厂和元数据，不持有数据库连接、SDK client 或可变 registry。

### 2.2 FeatureSpec

每个 feature 声明：

- 稳定 `name` 和版本。
- 所需 capability 名称与最低 schema/API 版本。
- content type、taxonomy dimension、points behavior 等业务注册项。
- workflows、activities、signals、events、Cron 和 routers。
- 所需 Port 绑定和 access capabilities。

FeatureSpec 不声明或拥有业务表；需要持久化的 feature 状态使用 kernel workflow state，或提升为独立 capability 后拥有表。

### 2.3 AppManifest

应用 manifest 必须显式列出：

- enabled capabilities。
- enabled features。
- Port -> adapter factory 绑定。
- routers、workers、Cron runner 是否启用。
- deployment profile 和安全相关配置引用。

首版至少提供用于测试的 `kernel_only`、`identity_provider` 和完整 `cms` 三种 manifest fixture；生产 manifest 只有一个明确入口。

## 3. 稳定 key

- key 使用小写 ASCII、点分命名，不以 Python import path 作为协议。
- capability：`content`、`oidc_provider`。
- feature：`post`、`point_purchase`。
- event：`content.published.v1`。
- workflow/activity：`post.submit.v1`、`notification.deliver.v1`。
- capability permission：`content.publish`、`points.adjust`。
- error code：`content.invalid_transition`。

稳定 key 一经随新基线发布，不得无迁移直接复用为不同语义。事件和持久化 workflow 的破坏性变化必须新增版本。

## 4. Port 与 adapter

- Port 由消费方定义。例如 OIDC 定义 `SubjectClaimsReader`，由组合根用 identity adapter 实现。
- adapter 库位于 `inc/api/adapters/`，按消费方 capability 分目录组织；完整目录合同、已装配/计划实现与占位规则见 [`adapters.md`](adapters.md)。
- capability 不得为了复用实现而导入 provider capability。
- adapter 只能通过 provider 的公开 Query/Command 获取数据，不能读取其 Repository/ORM。
- 一个 Port 可以有 production、sandbox、in-memory adapter，但同一 manifest 中绑定必须唯一。
- 外部 provider adapter 负责 SDK 初始化、认证、超时、限流、错误归一化和资源关闭。
- 必需 Port 未绑定、绑定重复或配置不完整必须在启动前失败。

## 5. 启动顺序

启动严格执行：

1. 读取并验证 config，不连接业务外部服务。
2. 创建 application container 和局部 registries。
3. 注册 kernel providers。
4. 载入 manifest 指定的 CapabilitySpec。
5. 载入 FeatureSpec。
6. 绑定并解析 Port/adapter。
7. 注册 commands、queries、events、workflow、activities、Cron、diagnostics 和 routers。
8. 校验 key 唯一性、依赖、版本、权限和完整性。
9. freeze registries。
10. 创建 FastAPI app 并挂载 routers。
11. 在 lifespan start 最后阶段启动 dispatcher/scheduler/worker。

任一步失败必须停止启动并释放已创建资源，不允许以部分注册状态继续服务。

## 6. 停止顺序

1. 停止接收新的后台领取任务。
2. 在配置的 grace period 内 drain 正在执行的 activity。
3. 释放 lease 或让其按期限安全过期。
4. flush 可观测数据。
5. 关闭外部 SDK clients、Redis 和数据库 engine。

HTTP server 停止不能把尚未提交的 activity 标记为成功；恢复后必须能重新领取。

## 7. HTTP 装配

- capability/feature 可以导出 `RouterSpec`，但不得自行调用 `include_router`。
- manifest 明确允许哪些 router；api 统一施加路径前缀、request ID、异常映射和授权依赖。
- OIDC 协议端点使用其标准路径和错误响应，不套普通 `/api/v1` 业务包装。
- OpenAPI 只包含当前完整产品 manifest 的公开 HTTP 面；测试 manifest 可生成独立临时 schema，不覆盖根 snapshot。

## 8. request-scoped AppContext

HTTP 层可以注入一个 request-scoped `AppContext`，其中只包含：

- 当前 Principal/subject。
- request/trace ID 和 Clock。
- 已注册的 Command/Query gateways。
- 当前 UoW factory，而不是已打开 Session。

AppContext 不得成为任意 service locator。调用未在 RouterSpec 声明的 gateway 应在测试或启动校验中失败。

## 9. 校验与测试

- import 每个 package 后，线程、连接、router 和 registry 数量不变。
- 同一声明以不同导入顺序装配得到相同注册清单。
- 重复 key、未知 capability、循环 Port、未绑定 adapter 和权限缺失均启动失败。
- registry freeze 后注册会抛出稳定错误。
- 空/最小/完整 manifest 的激活范围与预期一致。
- shutdown 中断测试证明任务不会丢失或被错误确认。
