# Adapters 规格

## 1. 定位

adapter 是 `inc/adapters` 下的 Port 实现库，按消费方 capability 分目录组织。capability 定义 Port（`notification.ports.NotificationProvider`、`payments.ports.PaymentProvider`、`assets.ports.ObjectStorageProvider` 等），adapter 实现它们。普通 Port 由 api 层 manifest 显式选择并绑定；provider-valued Port 则在启动时把允许的 provider 全部放入 container-local catalog，再由 settings 的当前值解析运行时 provider。未绑定的必需 Port 启动失败。

adapter 与 capability、feature 同级是规格的一等成员：capability 只声明接口契约，feature 只编排业务，adapter 只负责外部集成（SDK client、凭据、超时、限流、webhook 验签和错误归一化）。业务层永远不直接实例化 provider SDK。

`inc/adapters` 不隶属于 `inc/api`，可被 api 与 feature 使用：api 经 manifest 显式装配并冻结 Port/catalog；feature 或 capability 只消费已注入的 Port/Resolver，不按请求重新实例化 adapter。capability 不得反向导入 adapter。未装配 capability 的 manifest 不得通过任何 adapter 连接外部 provider。

## 2. 目录合同

```text
inc/adapters/
  registry.py                  # 组合根解析与非 SDK adapter（identity/auth/taxonomy）
  <capability>/                # 按消费方 capability 分目录
    __init__.py                # 目录说明与占位声明
    <provider>.py              # 一个外部集成一个文件
```

- 目录名使用消费方 capability 名：`notification`、`payments`、`assets`、`content`、`membership`。
- 每个 adapter 文件只实现一个 Port 契约，使用 provider 的公开 Query/Command 获取数据，不读取其 Repository/ORM。
- adapter 属于 `inc/adapters`，可导入 capability/feature 的公开声明；capability 不得反向导入 adapter。
- adapter 只声明与冻结契约对齐的稳定 key（如 `email.smtp`）；manifest 以 key 选择 Port 的默认绑定，禁止 import 即注册。provider catalog 的注册顺序和 key 集合在 container freeze 前确定。

## 3. 已装配与计划 adapter

### 3.1 notification（消费 `NotificationProvider`）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `notification/email_smtp.py` | 已实现（key `email.smtp`） | aiosmtplib 封装；运行时开关、错误分类、稳定 idempotency key 透传、超时归 unknown |
| `notification/smtp2go.py` | 已实现（key `email.smtp2go`） | 使用 requests 调用 SMTP2GO REST `/v3/email/send`；固定 region endpoint、运行时开关、错误分类和 provider reference 归一化 |

邮件连接参数与凭据由 `site_settings` feature 的 `notification` settings 组填写；两个 adapter 复用现有 `default_from_name`、`smtp_from_address` 和 `email_enabled` 字段。`email.smtp` 额外读取 `smtp_enabled` 与现有 SMTP 字段，`email.smtp2go` 读取 `smtp2go_enabled`、`smtp2go_api_key` 与 `smtp2go_region`。adapter 每次投递时读取当前组值，不持有跨调用的设置快照。

`smtp2go_region` 只能映射到 SMTP2GO 官方 global/US/EU HTTPS endpoint，不允许由 settings 提供任意 base URL。SMTP2GO API key 与 SMTP password 登记为 sensitive；管理 HTTP 只返回是否已配置，不回显原值。requests 的同步调用必须放入有硬 connect/read timeout 的线程，不得阻塞异步 activity event loop，也不得对 POST 自动重试。

两个 Email adapter 在各自内部检查总开关和 provider 开关；禁用或缺少必需配置返回归一化 `unavailable`，不伪装为发送失败。notification 只经 Port 消费由组合根注入的 provider Resolver；Resolver 每次调用读取 settings 的 `notification.email_provider`，不导入 adapter 实现。

### 3.2 payments（消费 `PaymentProvider`）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `payments/dev_fake.py` | 已实现（key `payments.dev_fake`） | 开发/演示用确定性 fake provider：内存会话、HMAC-SHA256 webhook 签名（模块常量测试密钥）、capture/failure/refund 事件构造辅助；生产 manifest 禁止绑定（`kernel.adapter_production_denied`） |
| `payments/paypal.py` | 已实现（key `payments.paypal`） | `paypal-server-sdk==2.3.0`；Orders API v2、OAuth 凭据、minor-unit 金额转换、官方 webhook 验签端点与错误归一化 |
| `payments/epay.py` | 计划占位 | Epay（易支付）网关 SDK；webhook 验签与回调归一化 |

provider 连接配置与凭据在 provider 契约冻结后按 settings 组或 secret provider 约定补充，不提前写死字段。当前 `settings.payments.provider` 只选择已注册的 `dev_fake` 或 `paypal`；provider catalog 不代表生产允许 dev_fake，生产 manifest 仍必须 fail-closed。dev_fake 的 webhook 测试密钥是公开的模块常量，仅用于开发与测试闭环，不构成生产凭据。

### 3.3 assets（消费 `ObjectStorageProvider`）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `assets/s3.py` | 已实现（key `s3`） | AWS S3/S3-compatible boto3：按组合根选择系统/头像 bucket，presigned 上传/读取 URL、stat、幂等 delete；连接配置和凭据来自 `site_settings.object_storage` |

S3 adapter 每次 Port 调用读取当前 settings 组并创建本次调用的 SDK 配置；不持有跨调用的凭据快照。RustFS 作为 Compose 集成测试的 S3-compatible provider。

### 3.4 content（内容外部集成）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `content/openlist.py` | 计划占位 | OpenList 内容分发 SDK；目标 Port 待冻结 |

### 3.5 oidc_provider（消费 `SigningKeyStore`）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `oidc/signing_keys.py` | 已实现（key `oidc.filesystem_keys`） | 生产 KeyRef：RSA 私钥只写入部署持久卷，目录/文件分别使用 owner-only 权限，原子替换；数据库仅保存 public JWK 与生命周期元数据 |
| `oidc_provider.keys.InMemorySigningKeyStore` | 仅开发（key `oidc.in_memory_keys`） | 无持久化，进程重启后不可恢复；生产 manifest 绑定时以 `kernel.adapter_production_denied` fail-fast |

`management_plane` 必须显式绑定 `oidc.signing_keys -> oidc.filesystem_keys`，并由部署提供持久化 `AIYA_OIDC_SIGNING_KEY_DIR`；目录缺失、不可写或 key 文件丢失不得降级为内存私钥。私钥内容、路径和 PEM 不进入数据库、OpenAPI、日志、诊断或管理员响应。

### 3.6 membership（消费 `SubjectExistsPort`、`PointsLedgerPort`）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `membership/__init__.py` | 已实现 | `IdentitySubjectExists`（`membership.subject_exists`，经 identity 查询解析 opaque subject）与 `PointsGrantLedger`（`membership.points_ledger`，只向 points 公开 `CreditPoints` 传数值/到期时刻/幂等键） |

membership adapter 只传递数值与 opaque 引用，不读取 points 或 identity 的业务表；`membership.points_ledger` 使用 points 行为 `membership.grant`，由 `user_center` feature 声明该行为。

## 4. 占位文件规则

- 尚未冻结的集成只创建占位文件：文档说明目标 Port、计划厂商和契约要点；不得有 SDK 依赖、网络调用、凭据读取或运行时副作用。已冻结并实现的集成必须同步依赖、settings、manifest 和合同测试。
- import 占位文件不得改变线程、连接、路由或 registry 状态。
- 提供方契约未冻结前不得实现；实现后必须同步本规格、合同测试和管理员消费层。

## 5. 装配与校验

- 普通 adapter 由 `registry.py` 的解析函数按 manifest 绑定创建；provider-valued Port 由同一解析器按允许清单创建全部实现并注册到 `ProviderCatalog`。重复绑定、未知 adapter、必需 Port 未绑定、重复 provider key 或冻结后注册均启动失败。
- `ProviderResolver` 只读取 settings capability 的当前 provider key；缺省值回退到 manifest 选择的默认 provider，未知或未注册 key 拒绝请求，不按字典顺序静默切换。
- 生产环境只允许已审计的 provider adapter；当前完整 manifest 使用已审计的 S3-compatible adapter。
- adapter 的稳定 key、依赖和绑定配置校验在容器 freeze 前完成；由 settings 提供的运行配置在每次调用时验证。
- `taxonomy.target_exists` 的 `content.exists` adapter 把 taxonomy 的 opaque `target_type` 解释为 content type name：仅当内容存在且 `type_name` 匹配（如 post feature 声明 `target_types=("post",)`）时返回 true。taxonomy HTTP 路由必须经 manifest 绑定获取该检查，不得自建存在性逻辑。

## 6. 验收

- 单独导入任意 adapter 目录/占位文件无副作用。
- 未装配 capability 的 manifest 不连接任何外部 provider。
- SMTP 凭据只来自 settings `notification` 组；S3 凭据只来自 settings `object_storage` 组；sensitive 字段不出现在公共读取/事件/日志。
- 计划占位文件可安全导入，且不产生运行时注册。
