# 发布质量门

> 下一用户站目标尚未实施。本文定义完成门，不把文档或局部构建当成发布证据。

发布目标是单一 `release` 组合：FastAPI、正式静态管理员 SPA、Astro SSR 用户站、持久 worker，以及 Compose 管理的 PostgreSQL/Redis。管理员管理面和用户站必须同时保持可验证，不能以新用户功能换取既有 management plane 回归。

## 必经验证

### 1. 架构与静态质量

- kernel/capability/feature/api/adapters 的 import 与数据所有权 guards 通过。
- membership 不依赖 points；user_center/business_center 不访问 capability ORM/Repository；API 无 Session、裸 SQL或业务计算。
- manifest/registry/provider catalog 的重复、缺失、未知依赖与未绑定 Port 均 fail-fast。
- backend format/lint/typecheck/compile、admin 和 site format/lint/typecheck/unit/build 全通过。

### 2. 数据库与 install

- 当前开发阶段以 SQLAlchemy metadata 合并重建 `release_0001` baseline；隔离空 PostgreSQL 从零升级到当前 head，不保留开发期旧 revision 或数据兼容路径。
- baseline 直接创建 archive、membership cycle 和 workflow 当前结构；验证 clean upgrade/downgrade 与 metadata 一致性，不验证旧 subscription/renewal 数据迁移。
- upgrade/downgrade（在规格允许范围内）、migration ownership check 和 revision 单头检查通过。
- `python -m inc.cli install` 重复执行幂等：OIDC key、管理员、OIDC clients、权限、settings、points behavior、产品与 feature 声明不重复。
- 不得在用户现有数据库或默认 Compose volume 上执行破坏性 clean migration 验证。

### 3. OpenAPI 与生成客户端

- frozen release schema 可以完整构建，生成过程不连接 SMTP/S3/payment/archive provider。
- `openapi.admin.json` 覆盖所有 `/api/v1/admin/**`，且不包含用户业务页面专用路由。
- `openapi.user.json` 包含 auth、`/me`、post/page/work、community、user_center 和 business_center，且不含 admin、webhook、secret DTO、内部 repair。
- projection allowlist、component pruning、稳定排序、operationId 唯一、snapshot/hash drift 测试通过。
- admin/site 类型分别由自己的投影生成，无手写后端 DTO 镜像和跨投影导入。

### 4. Capability 与 feature

- points：多桶余额、FIFO、debt、显式 expires_at、expiration、幂等与 reversal。
- membership：prepare/attach、周期重叠、未 attach 不生效、到期状态收敛。
- payments：CNY/金额、attempt、验签 webhook、重复 callback、capture/refund。
- gift_cards：verify/reserve/commit/cancel、secret 脱敏与并发兑换。
- archive：manifest、grant、delivery attempt、provider migration、到期和链接刷新。
- user_center：签到、积分购买、会员购买、周期积分、卡密两类兑换、退款补偿；每个提交点 crash/restart 不重复价值变化。
- business_center：受信报价、manifest 漂移、余额不足、一次 debit、履约重试、reversal、窗口内刷新不重复扣费。
- post/page/work：精确 taxonomy/comments/engagement/archive 组合，page 未声明端点为 404。
- community：最小 Flarum-like 列表、排序、搜索、讨论/回复与审核边界。

### 5. Adapter 合同

- SMTP/SMTP2GO/S3/PayPal/Epay/OpenList/Gofile 缺配置、timeout、认证失败、限流和恶意 payload 都返回 typed 脱敏错误。
- PayPal/Epay 的下单、查询、验签、重复 webhook、退款全部使用 HTTP mock 闭合。
- OpenList/Gofile 的列表、链接生成、有效期、secret header、权限拒绝和 provider unavailable 全部使用 HTTP mock 闭合。
- 启动只注册 lazy factory；不 probe 网络，也不按 provider 顺序静默回退。

### 6. 用户站与浏览器 E2E

- 公开 post/page/work 与社区 SSR、Markdown sanitizer、canonical/SEO、sitemap 和 no-JS 阅读。
- OIDC confidential code + PKCE 的 login/callback/logout、state/nonce、session rotation、expiry 和 Redis fail-closed。
- `/me` 资料/头像、签到、points buckets/ledger、membership、purchases 和 gift card。
- payment return 不可信、captured 后 fulfillment pending/complete、重复 webhook、refund。
- work 报价、确认扣费、余额不足、扣费后 archive 暂时失败恢复、grant/list/link refresh/expiry。
- 401/403、跨 subject/order/grant 访问、CSRF、open redirect、secret 泄漏和 request ID 映射。
- account/payment/download 页面 noindex/no-store，provider URL/header/token 不进入 HTML cache、telemetry 或截图 fixture。

## Compose 与生产路径

`compose.infra.yaml` 只管理 PostgreSQL/Redis；`compose.yaml` 部署 release backend/worker、生产静态 admin 和 Astro SSR site。运行时 issuer、origin、API/Redis URL、client 配置与 provider settings 由 Compose `environment`/`env_file` 注入，Dockerfile 不固化环境值。

必须分别验证：

- backend direct health/readiness；
- 入口代理后的 API health、OIDC discovery/callback 和 forwarded headers；
- admin 静态资源、fallback 与匿名 session 401；
- Astro SSR HTML、静态资源、cookie secure/domain/path 和 BFF API；
- worker/scheduler 重启后的 workflow、outbox/inbox 与 task 恢复；
- provider 未配置时启动成功，显式调用失败且脱敏。

生产不运行 Vite dev server、`vite preview` 或进程内 session。backend/worker 的写入拓扑必须与 lease、幂等和并发模型一致。

## 完成定义

不能以 Dockerfile、Compose config、迁移文件、页面存在、OpenAPI 文件存在、编译或单一 happy path 替代验证。发布报告必须分别列出：

1. 已实现范围；
2. 已通过的门及命令/环境；
3. 可重现的环境阻塞；
4. 未包含或仍待实现范围。

只有本文件所有适用门有证据时，才能宣称用户中心、积分/会员购买、卡密兑换、作品积分下载和社区最小用户站已经发布。
