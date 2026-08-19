# 管理员端规格

`admin/` 是 release 的独立 Vue SPA，只通过 `openapi.admin.json` 的生成类型调用 `/api/v1/admin/**` 和 OIDC/认证公共端点。完整 `openapi.json` 仅用于系统验证，不参与管理员端类型生成。它不读取 Python、数据库、manifest 内部表或手写 DTO。后端始终是授权边界；前端 capability set 只用于菜单和操作可见性。

管理员使用 first-party public OIDC client 的 Code + PKCE，token 仅在内存，callback 后读取 `/api/v1/admin/session`。注册、邮箱验证、密码重置可调用 auth 公共端点；不得调用 `/api/v1/me`、用户资料、购买、支付、退款或 webhook 路由。

普通 `/admin` capability CRUD 直接对应公开 capability Command/Query。记录详情使用 Drawer，小型创建/确认使用 Dialog；不把 detail 再注册为子路由。`content_bucket` 是例外的跨能力 feature，提供管理员上传 intent、finalize、处理状态轮询和删除。

Settings 表单只根据 OpenAPI 返回的 `group_key`、`slug`、`type`、`type_sub`、default、敏感性、option value 与约束选择控件。所有 label、description、placeholder 和 option 文案均以 `group + slug + option value` 映射 `zh-CN`/`en-US` 本地词典；不得期待或显示后端 title/desc/label。

release 当前页面只注册已有 router/permission 的 admin 工作台（内容、社区、身份/access、OIDC、audit/operations、assets/content bucket、通知、settings 等）。用户中心、积分/会员购买、payment orders/webhook/refund 页面不注册、不进菜单、不使用 placeholder。生产使用正式静态文件服务，不运行 Vite dev server/preview。

每次 OpenAPI 变化必须重新生成 schema/types，并通过 format、lint、typecheck、unit、build；两套 i18n key 必须一致，后端英文 `message` 与 request ID 原样保留。
