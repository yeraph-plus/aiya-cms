# HTTP 与 OpenAPI 规格

`inc/api` 是 release 的 HTTP 适配层：解析 Pydantic DTO、施加认证/授权依赖、调用公开 Command/Query/feature gateway，并映射稳定错误。router 不访问 ORM/Repository/Session，不拼跨 capability 查询，也不自行选择 adapter。

唯一 schema 来源为 `release` manifest。admin schema 包含已装配的 `/api/v1/admin/**` capability 管理面和 `content_bucket` feature；user schema 仅包含公开 content/community/comments 与认证/OIDC 所需面。两者均不含 `/api/v1/me`、用户资料/上传、签到、积分/会员购买、支付、退款或 webhook HTTP 路由。

settings Field API 只返回机器 metadata；显示文本由管理端本地化。通知模板 API 只接受注册 trigger 和严格 variables/schema。图片 API 使用命名 upload/finalize/status/delete 操作而非对象存储直通。

每次 HTTP 合同改变必须重新生成 admin/user OpenAPI snapshots 和 admin TypeScript 类型。OpenAPI 生成不应因外部 SMTP、S3、PayPal、Epay 的缺配置而连接或失败；OIDC filesystem key 由测试临时目录显式准备。
