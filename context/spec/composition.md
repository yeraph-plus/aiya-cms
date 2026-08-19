# 装配与生命周期规格

## 唯一发布组合

`inc/api` 是唯一组合根。唯一可部署 manifest 是 `release`；历史 profile、环境选择和兼容别名均不存在。测试可以在进程内构造最小 manifest，但不能成为部署 profile。

本文描述下一用户站版本的目标 `release`。当前代码与快照的迁移差异见 [`../user site spec/IMPLEMENTATION.md`](<../user site spec/IMPLEMENTATION.md>)；未完成该文档中的失败测试、删除清单和集成门前，不得把目标装配表述为已经上线。

目标 `release` 同时装配管理面、用户站、OIDC、用户中心和积分消费业务：

```text
api release composition root
  ├─ email.smtp
  ├─ email.smtp2go
  ├─ payments.paypal
  ├─ payments.epay
  ├─ storage.s3
  ├─ archive.openlist
  └─ archive.gofile
             ↓
       capability ProviderCatalog / Resolver
             ↓
       settings 当前 provider 选择
             ↓
       feature / capability 调用 Port
```

上图中的 provider 必须在启动构建阶段全部注册；注册 factory 只创建惰性 adapter，不探测网络、不建立 SDK 连接。catalog key 在 container freeze 前确定；实际 provider 配置、凭据和连通性仅在显式 `check_availability()` 或业务 Port 调用时读取当前 settings 快照。settings 分别选择当前 email、payments、storage 和 archive provider；未知选择或未注册 key失败，不按顺序回退。`oidc.filesystem_keys` 是独立的 SigningKeyStore Port，不属于 provider catalog，但同样由组合根显式绑定。

`release` 挂载：

- `/api/v1/admin/**` capability 管理面；
- 公开 post/page/work、taxonomy、community、comments 浏览面；
- 认证、OIDC 和 `/api/v1/me`；
- `user_center` 的签到、余额/流水、会员与积分购买、卡密兑换；
- `business_center` 的报价、积分消费和下载授权；
- payments provider 的受信 callback/webhook。

当前 admin API 中的普通 CRUD 直接调用所属 capability 的公开 Command/Query，不强行包一层 feature；注册、找回密码、用户中心购买/兑换、下载消费等跨能力多步骤流程才由 feature 编排。支付 callback router 只适配 provider 请求到 payments capability；它不在 HTTP 层授予积分或会员。

`gift_cards`、points、membership、payments 与 archive 均作为 capability 装配；`user_center` 组合签到、购买和兑换，`business_center` 组合积分扣费与业务履约。旧 `check_in`、`membership_grants`、`point_purchase`、`membership_purchase`、`content_engagement` feature/router key 必须在同一迁移中删除，禁止新旧路径并存。

## 分层和声明

- kernel 仅提供运行时、UoW、分页、registry 等技术原语。
- capability 拥有自身规则、表、原子 Command/Query/Activity 和 Port；不导入兄弟 capability 或建立跨 capability 外键。
- feature 只以公开 DTO/Command/Query/Activity/Port 编排跨能力流程，不访问 ORM、Repository 或表。
- api 只做 HTTP 适配、授权依赖、manifest 和组合：包括显式注册/绑定 Port、provider catalog、router/worker 及启动校验；不承载 capability 规则或 feature 业务流。

CapabilitySpec、FeatureSpec、RouterSpec、workflow/activity、event、Cron 和权限均使用稳定 key 显式注册。未由 `release` 选中的声明不得产生路由、订阅、线程、连接或后台任务。

## OIDC key 与启动顺序

OIDC 只绑定 `oidc.filesystem_keys`。部署必须挂载 `AIYA_OIDC_SIGNING_KEY_DIR` 持久目录；install 显式初始化 key material。应用 lifespan 在启动 worker 前要求一个可读取的 active key。目录、私钥、KeyRef 损坏或无 active key 一律以 `oidc.signing_keys_unavailable` 启动失败，绝不降级为进程内 key。

启动顺序为：验证配置 → 建 container/registry → 装载 release capability 和 feature → 注册所有允许 provider → 绑定普通 Port → 校验与 freeze → 建 FastAPI/router → 验证 active OIDC key → 启动 dispatcher/scheduler/worker。启动阶段不得探测外部邮件、支付或对象存储服务。

## HTTP 和 OpenAPI

router 只做 HTTP DTO、授权依赖和错误映射，禁止 ORM/Session/裸 SQL。OpenAPI 只从 `release` 生成：`openapi.json` 仅供系统验证且可停止产出，`openapi.admin.json` 是管理员 SPA 合同，`openapi.user.json` 是用户站合同。管理员前端只消费 `openapi.admin.json` 生成的类型；用户站只消费 `openapi.user.json`。支付 webhook、内部 workflow 修复端点和 provider secret DTO 不进入用户投影。

## 验收

- 历史 profile、开发支付 adapter、内存 OIDC key 和旧环境选择在发布代码、manifest、Compose 和快照中均不可引用。
- release router allowlist 明确包含认证、`/api/v1/me`、`user_center` 与 `business_center` 用户端点；支付 webhook 只存在于完整系统 schema，不进入 admin/user 客户端投影。
- 未配置外部 provider 不阻止启动；调用/显式检查得到无密钥泄露的 typed unavailable 错误。
- 空库迁移、install 重复执行、OIDC、正式 admin 静态服务与 Astro SSR 客户端均通过集成验证。
- 架构测试证明 `inc/api` 没有业务规则，membership 不导入/call points，业务中心不访问 capability ORM/Repository。
