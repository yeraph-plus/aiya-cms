# ADR-0013: 认证令牌浏览器存储与 CORS/CSRF 策略

- 状态: accepted
- 日期: 2026-08-04
- 决策者: 项目所有者 + AI 协作
- 关联: [kernel/auth.md](../kernel/auth.md)、[kernel/security.md](../kernel/security.md)、[admin/00-overview.md](../admin/00-overview.md) 第 4 节、[m1-a1-plan.md](../m1-a1-plan.md) G0

## 背景

管理员 SPA 与后端 FastAPI 之间需要确定 access/refresh 双令牌在浏览器的存储方式，以及随之而来的 CORS、CSRF 与注销策略。此前 [kernel/auth.md](../kernel/auth.md) 只定义了服务端生命周期（TokenPair 签发、旋转、吊销、refresh 只存哈希），未规定浏览器侧存储。admin 规格明确要求此项在 A1 实现前另立 ADR。

约束与驱动力：

- 管理员 SPA 是内部管理工具，用户会话需要跨页面刷新与多标签页持续（A1.3「启动恢复」）。
- XSS 防御优先：任何能被 JS `localStorage`/`sessionStorage` 读到的 token 都可能被窃取。
- CSRF 防御：唯一以 cookie 为凭证的接口必须限制跨站调用。
- 后端仍以 `Authorization: Bearer` 头承载 access token 作为常规鉴权；cookie 只承载 refresh。
- 生产环境 SPA 与 API 同源部署（同一 origin，nginx 或 FastAPI 静态托管）；开发环境 Vite(7000) → FastAPI(8000) 跨源。

## 决策

- **access token 只存内存**（Pinia store，不持久化到 localStorage/sessionStorage）。短生命周期（默认 900s），页面刷新后由 refresh 重新换取。
- **refresh token 存 httpOnly Cookie**：`HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`。浏览器不读写，XSS 无法窃取；`SameSite=Strict` 阻断跨站携带（CSRF）；`Path` 限定只随 auth 接口发送。
- **login/refresh 同时返回响应体 TokenPair 与 `Set-Cookie`**。SPA 使用响应体的 access；body 的 refresh 对浏览器流程不透明（cookie 为权威来源）。
- **refresh/logout 读取 refresh 的权威途径是 cookie**（path 限定自动携带）。`RefreshRequest` DTO 保留在 OpenAPI 中供非浏览器/API 消费者，浏览器流程不依赖其内容。
- **旋转与吊销保持 auth.md 语义**：refresh 每次旋转（旧吊销、新签发，Cookie 随之更新）；logout 吊销并清除 cookie；封禁/改密吊销该用户全部 refresh。
- **注销**：SPA 调 `POST /api/v1/auth/logout`（cookie 携带 refresh）→ 服务端吊销 + 清 Cookie + 客户端清空内存 access → 跳转登录页。所有非 auth 接口走 `Authorization: Bearer`，不依赖 cookie。
- **CORS**：开发环境仅放行 Vite origin（`http://localhost:7000`）且 `credentials: true`；生产同源无需 CORS（origin 白名单由 settings `cors_origins` 按环境配置）。
- **CSRF**：refresh cookie `SameSite=Strict` 已是主防线；额外约定 login/refresh/logout 必须 `Content-Type: application/json`，拒绝表单式跨站伪造。
- **多标签页**：refresh cookie 跨标签页共享，任标签页刷新即恢复会话；各标签页内存中的 access 相互独立，分别经 refresh 单飞换取。
- settings 新增字段：`cors_origins`、`cookie_name`（默认 `aiya_refresh`）、`cookie_secure`（prod 校验必须为 True）。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| access+refresh 全内存（无 cookie） | 零 CSRF 面、CORS 最简单、严格贴合 TokenPair 契约 | 页面刷新/换标签页会话丢失，需重新登录，违背「启动恢复」 | 管理员端会话需要跨刷新/多标签持续 |
| refresh 存 localStorage/sessionStorage | 实现简单 | XSS 可读；sessionStorage 每标签页独立、需各自登录 | 违背 XSS 优先原则 |
| cookie 承载 access + refresh 全走 cookie | 完全无 JS token | access 有效期短导致 cookie 高频往返；access 进 cookie 引入 CSRF 面（所有接口需防跨站） | `Authorization: Bearer` 头更贴合 REST 鉴权惯例 |

## 后果

### 正面
- XSS 窃取面大幅缩小：内存 access 有效期短，refresh 为 JS 不可读。
- CSRF 面收敛到 `/api/v1/auth/*` 且被 `SameSite=Strict` 与 JSON-only 双重限制。
- 会话跨刷新、跨标签页持续，A1.3「启动恢复」成立。

### 负面 / 代价
- 需要管理 Cookie 的跨源凭证（dev 需 `credentials: include`）与 `Set-Cookie` 的 domain/path 细节。
- body 与 cookie 双通道需在测试中固定「cookie 为权威」行为，避免双实现漂移。
- 非浏览器 API 消费者仍用 body refresh，需保持 `RefreshRequest` 契约不破坏。

### 逃生门
- 若未来跨域部署 SPA（CDN 或独立 origin），将 `SameSite=Strict` 调整为 `SameSite=None; Secure` 并显式允许 CORS 凭证——仅改 settings 与 CORS 配置，令牌语义不变。
- 若 XSS 威胁等级上升，可将 access 改为更短 TTL 并在内存基础上叠加操作级签名。
