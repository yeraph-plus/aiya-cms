# HTTP 与 OpenAPI 规格

`inc/api` 是 release 的 HTTP 适配层和组合根：解析 Pydantic DTO、施加认证/授权依赖、调用公开 Command/Query/feature gateway，并映射稳定错误；它还负责 manifest、Port/provider catalog、router 和 worker 的显式组合。router 不访问 ORM/Repository/Session，不拼跨 capability 查询，也不自行选择 adapter。

`/api/v1/admin/**` 中的普通 capability 管理 CRUD 直接调用所属 capability 的公开 Command/Query，不为形式统一再包 feature；只有注册、密码找回、用户中心购买/兑换、积分消费与下载履约等跨 capability 多步骤流程才调用 feature gateway。

唯一 schema 来源为 `release` manifest。系统完整 schema 可保留为根目录 `openapi.json`，仅用于系统验证和漂移检查，也可以在相同验证被其他产物覆盖后停止生产；生产环境不暴露完整 runtime OpenAPI，不把它作为客户端合同。

- `openapi.admin.json`：包含全部已装配的 `/api/v1/admin/**` 管理端点，以及管理 SPA 必需的 health/session/OIDC 协议端点；不得包含用户中心页面专用 API。
- `openapi.user.json`：包含公开 post/page/work、taxonomy、community/comments、认证 API、`/api/v1/me`、`user_center` 及 `business_center` 用户端点；不得包含管理员 CRUD、provider webhook、内部 workflow repair 或 secret DTO。

用户认证投影必须保留：

- `/api/v1/auth/register`
- `/api/v1/auth/verify-email`
- `/api/v1/auth/password-reset/*`
- `/api/v1/me`

现实法币购买入口属于 `user_center`，只接受受信 offer key；客户端不能提交最终 CNY 金额。payments provider callback/webhook 属于完整系统路由，但不进入 admin/user 客户端投影。积分消费入口属于 `business_center`，只接受 product key、target ref 和幂等键；客户端展示的报价不是扣费依据，执行时必须由服务端重新计算或验证 quote version。

## 投影规则

投影以规范化 path 为第一边界，再以显式 allowlist 补充协议路由；禁止通过 tag 名称或文件位置猜测。

1. 从冻结后的同一个 `release` FastAPI app 生成一次完整 schema。
2. admin 投影纳入所有 `/api/v1/admin/**` path，并显式加入 admin session、health 和 OIDC discovery/callback 所需 path。
3. user 投影只纳入用户 allowlist；`/api/v1/admin/**` 永远排除。
4. 对每个投影执行不可达 component pruning，只保留 path 实际引用的 schema/security/parameter。
5. 对 path、method、operationId 和 component key 稳定排序，消除生成顺序噪声。
6. 校验 operationId 在单一投影内唯一；同一路由不得同时以兼容别名出现。
7. 快照与生成结果不一致即失败，不由脚本静默覆盖。

所有消费端类型都由各自投影生成，不维护手写 DTO 镜像。admin 与 user 即使引用结构相似，也不得从另一投影的生成目录跨包导入。

settings Field API 只返回机器 metadata；显示文本由管理端本地化。通知模板 API 只接受注册 trigger 和严格 variables/schema。图片 API 使用命名 upload/finalize/status/delete 操作而非对象存储直通。

每次 HTTP 合同改变必须重新生成 admin/user OpenAPI snapshots，以及 admin/user 各自的 TypeScript 类型。OpenAPI 生成不应因外部 SMTP、S3、PayPal、Epay、OpenList、Gofile 的缺配置而连接或失败；OIDC filesystem key 由测试临时目录显式准备。

## 验收

- admin 快照完整覆盖当前所有 `/api/v1/admin/**` path，且 user 快照不含任何 admin path。
- user 快照含四组认证/自助路径、三种内容类型、社区最小面、用户中心和业务中心。
- 两个快照都不包含支付 webhook、provider token、外部 locator、secret headers 或内部修复 Command。
- projection 单元测试覆盖 path allowlist、component pruning、稳定排序、重复 operationId 和 snapshot drift。
- API 路由架构测试证明 handler 只做 DTO、授权依赖、gateway/Command/Query 调用和错误映射。
