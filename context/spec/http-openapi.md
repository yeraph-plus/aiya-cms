# HTTP/OpenAPI 规格

## 1. 基础契约

- API 前缀为 `/api/v1`；`/healthz` 是进程存活检查，`/api/v1/health` 检查运行依赖。
- 全部响应使用 Pydantic DTO；错误统一包含 code、http_status、message、request_id。
- `X-Request-ID` 由客户端可传入，非法值由服务端生成并回传。
- 生产 Compose 采用 admin Nginx 同源代理 `/api`；开发 profile 由 Vite proxy 转发。

## 2. 安全

- refresh token 由 httpOnly Cookie 保存，access token 只在浏览器内存；CORS 仅开发跨源需要。
- 后端 `require_capability` 是授权权威；前端只做可见性和交互守卫。
- 敏感操作必须登记 Capability 并产生审计事件。

## 3. OpenAPI

- 根 `openapi.json` 与 `openapi.sha256` 是冻结快照。
- `inc.api.openapi dump/check` 负责生成和漂移检查；管理员类型由 openapi-typescript 生成。
- 管理员 API 适配器必须引用生成的 paths/operations 类型，不允许 unknown payload 或重复 DTO。
