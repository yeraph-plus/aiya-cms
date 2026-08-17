# 发布质量门

发布目标是单一 `release` 组合：FastAPI、正式静态管理端和 Astro SSR 客户端；客户端只支持公开浏览及 OIDC 登录/回调/登出。发布仅支持全新数据库。

## 必经验证

1. 空 PostgreSQL 执行 `python -m inc.cli migrate`，只有 `release_0001` baseline/head；已有业务表或旧 Alembic revision 明确失败，不自动删除、转换或兼容。
2. `python -m inc.cli install` 在 persistent OIDC key volume 初始化唯一 active key、管理员和必要 OIDC clients；重复执行幂等。
3. 运行 quality、backend tests、OpenAPI snapshot/type 生成与 migration check；管理端和 Astro 分别 format/lint/typecheck/unit/build。
4. 直接与 Nginx/SSR proxy 的 health、OIDC、公开内容、admin 管理路径和图床处理通过；外部 provider 用 HTTP mock 或受控测试依赖验证。
5. provider 缺配置/不可用、OIDC key 缺失/损坏、通知 trigger/variables、CNY/金额不匹配、图像格式/大小/炸弹与权限均有负向测试。

## Compose

`compose.infra.yaml` 只管理 PostgreSQL/Redis；`compose.yaml` 默认同时部署 release backend、生产静态 admin 和 Astro SSR site。运行时值由 Compose environment/env_file 注入，Dockerfile 不固化运行配置。backend 是唯一写实例和唯一 worker runtime；启动不探测外部邮件、对象存储或支付服务。

## 完成定义

不能以 Dockerfile、Compose config、编译或文件存在替代验证。发布报告分别列出已实现、已通过门、可重现环境阻塞和未包含范围；不得将本 release 宣称为用户中心、积分、会员或支付产品发布。
