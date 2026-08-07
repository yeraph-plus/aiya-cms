# Adapters 规格

## 1. 定位

adapter 是组合根（`inc/api`）一侧的 Port 实现库，按消费方 capability 分目录组织。capability 定义 Port（`notification.ports.NotificationProvider`、`payments.ports.PaymentProvider`、`assets.ports.ObjectStorageProvider` 等），adapter 实现它们；api 层的 manifest 显式选择 adapter 并绑定到 Port，未绑定的必需 Port 启动失败。

adapter 与 capability、feature 同级是规格的一等成员：capability 只声明接口契约，feature 只编排业务，adapter 只负责外部集成（SDK client、凭据、超时、限流、webhook 验签和错误归一化）。业务层永远不直接实例化 provider SDK。

## 2. 目录合同

```text
inc/api/adapters/
  registry.py                  # 组合根解析与内存/dev adapter（identity/auth/taxonomy/assets）
  <capability>/                # 按消费方 capability 分目录
    __init__.py                # 目录说明与占位声明
    <provider>.py              # 一个外部集成一个文件
```

- 目录名使用消费方 capability 名：`notification`、`payments`、`content`。
- 每个 adapter 文件只实现一个 Port 契约，使用 provider 的公开 Query/Command 获取数据，不读取其 Repository/ORM。
- adapter 属于 `inc/api`，可导入 capability/feature 的公开声明；capability、feature 不得反向导入 adapter。
- adapter 只声明与冻结契约对齐的稳定 key（如 `email.smtp`）；manifest 以 key 引用，禁止 import 即注册。

## 3. 已装配与计划 adapter

### 3.1 notification（消费 `NotificationProvider`）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `notification/email_smtp.py` | 已实现（key `email.smtp`） | aiosmtplib 封装；错误分类、稳定 idempotency key 透传、超时归 unknown |
| `notification/smtp2go.py` | 计划占位 | Smtp2Go 事务邮件 SDK 接入；provider 契约冻结后实现 |

SMTP 连接参数与凭据（host/port/username/password/from_address、use_tls/starttls）由 `site_settings` feature 的 `notification` settings 组填写；adapter 在装配时从该组构造 `SmtpSettings`。凭据字段登记为 sensitive，不进入公共 DTO、事件、日志和审计摘要。

### 3.2 payments（消费 `PaymentProvider`）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `payments/paypal.py` | 计划占位 | PayPal Orders API v2；webhook 验签（transmission-id/signature/timestamp） |
| `payments/epay.py` | 计划占位 | Epay（易支付）网关 SDK；webhook 验签与回调归一化 |

provider 连接配置与凭据在 provider 契约冻结后按 settings 组或 secret provider 约定补充，不提前写死字段。

### 3.3 content（消费 `ObjectStorageProvider` 等）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `content/s3.py` | 计划占位 | AWS S3/S3-compatible（boto3）：presigned 上传/读取 URL、stat、幂等 delete |
| `content/openlist.py` | 计划占位 | OpenList 内容分发 SDK；目标 Port 待冻结 |

开发期对象存储使用 `registry.py` 的 `InMemoryObjectStorage`（key `dev_memory`），生产 manifest 禁止绑定（`kernel.adapter_production_denied`）。

## 4. 占位文件规则

- 计划中的集成只创建占位文件：文档说明目标 Port、计划厂商和契约要点；不得有 SDK 依赖、网络调用、凭据读取或运行时副作用。
- import 占位文件不得改变线程、连接、路由或 registry 状态。
- 提供方契约未冻结前不得实现；实现后必须同步本规格、合同测试和管理员消费层。

## 5. 装配与校验

- adapter 由 `registry.py` 的解析函数按 manifest 绑定创建；重复绑定、未知 adapter、必需 Port 未绑定均启动失败。
- 生产环境只允许已审计的 provider adapter，dev 专用 adapter（`dev_memory`）显式拒绝。
- adapter 的稳定 key、依赖和配置校验在容器 freeze 前完成。

## 6. 验收

- 单独导入任意 adapter 目录/占位文件无副作用。
- 未装配 capability 的 manifest 不连接任何外部 provider。
- SMTP 凭据只来自 settings `notification` 组，不来自环境变量或代码常量；sensitive 字段不出现在公共读取/事件/日志。
- 计划占位文件可安全导入，且不产生运行时注册。
