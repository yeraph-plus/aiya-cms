# 装配与生命周期规格

## 唯一发布组合

`inc/api` 是唯一组合根。唯一可部署 manifest 是 `release`；历史 profile、环境选择和兼容别名均不存在。测试可以在进程内构造最小 manifest，但不能成为部署 profile。

`release` 装配管理端、公开内容浏览和 OIDC：

```text
api release composition root
  ├─ email.smtp
  ├─ email.smtp2go
  ├─ payments.paypal
  ├─ payments.epay
  ├─ storage.s3
  └─ oidc.filesystem_keys
             ↓
       capability ProviderCatalog / Resolver
             ↓
       settings 当前 provider 选择
             ↓
       capability / feature 调用 Port
```

注册 factory 只创建惰性 adapter，不探测网络、不建立 SDK 连接。catalog key 在 container freeze 前确定；实际 provider 配置、凭据和连通性仅在显式 `check_availability()` 或业务 Port 调用时读取当前 settings 快照。未知选择或未注册 key 失败，不按顺序回退。

`release` 挂载 `/api/v1/admin/**` 的 capability 管理面、公开 content/community/comments 浏览和 OIDC/认证端点。客户端不装配用户中心、积分、会员、购买或支付业务路由；payments 本次不挂 webhook、购买、退款 HTTP 路由。管理员普通 CRUD 直接调用 capability 的公开 Command/Query；注册、找回密码、图床处理等跨能力流程才由 feature 编排。

## 分层和声明

- kernel 仅提供运行时、UoW、分页、registry 等技术原语。
- capability 拥有自身规则、表、原子 Command/Query/Activity 和 Port；不导入兄弟 capability 或建立跨 capability 外键。
- feature 只以公开 DTO/Command/Query/Activity/Port 编排跨能力流程，不访问 ORM、Repository 或表。
- api 只做 manifest、Port 绑定、授权依赖、HTTP 映射、router/worker 装配和启动校验。

CapabilitySpec、FeatureSpec、RouterSpec、workflow/activity、event、Cron 和权限均使用稳定 key 显式注册。未由 `release` 选中的声明不得产生路由、订阅、线程、连接或后台任务。

## OIDC key 与启动顺序

OIDC 只绑定 `oidc.filesystem_keys`。部署必须挂载 `AIYA_OIDC_SIGNING_KEY_DIR` 持久目录；install 显式初始化 key material。应用 lifespan 在启动 worker 前要求一个可读取的 active key。目录、私钥、KeyRef 损坏或无 active key 一律以 `oidc.signing_keys_unavailable` 启动失败，绝不降级为进程内 key。

启动顺序为：验证配置 → 建 container/registry → 装载 release capability 和 feature → 注册所有允许 provider → 绑定普通 Port → 校验与 freeze → 建 FastAPI/router → 验证 active OIDC key → 启动 dispatcher/scheduler/worker。启动阶段不得探测外部邮件、支付或对象存储服务。

## HTTP 和 OpenAPI

router 只做 HTTP DTO、授权依赖和错误映射，禁止 ORM/Session/裸 SQL。OpenAPI 只从 `release` 生成；admin 和 user 投影均不得包含未装配的用户中心、购买、支付或 webhook 路由。管理员前端只消费由该 OpenAPI 生成的类型。

## 验收

- 历史 profile、开发支付 adapter、内存 OIDC key 和旧环境选择在发布代码、manifest、Compose 和快照中均不可引用。
- release router allowlist 明确排除 `/api/v1/me`、购买、支付和支付 webhook。
- 未配置外部 provider 不阻止启动；调用/显式检查得到无密钥泄露的 typed unavailable 错误。
- 空库迁移、install 重复执行、OIDC、正式 admin 静态服务与 Astro SSR 客户端均通过集成验证。
