# ADR-0014: request_id 传播契约

- 状态: accepted
- 日期: 2026-08-04
- 决策者: 项目所有者 + AI 协作
- 关联: [kernel/logging.md](../kernel/logging.md)、[kernel/errors.md](../kernel/errors.md)、[kernel/auth.md](../kernel/auth.md)、[admin/00-overview.md](../admin/00-overview.md)、[0013-browser-token-storage-cors-csrf.md](0013-browser-token-storage-cors-csrf.md)

## 背景

管理员 SPA 与 FastAPI 之间的请求需要可关联的追踪标识：一次失败请求从浏览器 → 中间件 → 结构化日志 → 错误响应都能归并到同一个 id，且 401 单飞刷新后的重放请求应沿用同一 id，便于联调排障。此前 logging/errors 规格要求 `request_id` 贯穿日志与错误响应，但未定义跨进程（前端 → 后端）的取值与传递规则。

## 决策

- **取值规则**：优先采用客户端 `X-Request-ID` 头（若存在且合法），否则由服务端生成 UUIDv7。合法格式：`[A-Za-z0-9_-]{8,64}`。
- **中间件职责**：api 层中间件在请求进入时解析/生成 request_id，写入 contextvar（`bind_context(request_id=...)`），请求结束回填 `X-Request-ID` 响应头。一次请求内所有日志自动携带。
- **错误响应**：`ErrorResponse.request_id` 与响应头 `X-Request-ID` 一致（见 [kernel/errors.md](../kernel/errors.md)）。
- **前端职责（A1.2 统一 HTTP 层）**：每个逻辑请求在发起时生成/复用 request_id，经 `X-Request-ID` 头发出；401 单飞刷新后的重放请求**沿用同一 id**，不重新生成，保证整条链路可关联。
- **不落库**：request_id 是请求追踪标识，不进入业务表；若审计行需要，经事件 payload 显式携带，不隐式穿透。
- **生成器**：服务端与前端均使用 UUIDv7（与主键同风格）。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| 仅服务端生成，不接收客户端 id | 实现最简 | 前端发起的同一逻辑操作（含重放）在服务端是多个 id，无法跨请求关联 | 无法满足「刷新重放沿用同一 id」的排障需求 |
| 前后端各用一个独立 id（服务端换新） | 双方日志独立可查 | 前端 ↔ 后端两侧无法直接 join | 不符合贯穿目标 |

## 后果

### 正面
- 浏览器 DevTools、structlog、错误响应三处 id 一致，联调排障链路闭合。
- 401 重放请求同 id，能一眼看出「第一次 401、重放成功」的关联关系。

### 负面 / 代价
- 需在统一 HTTP 层维护 request_id 生命周期与格式校验；生成逻辑两处实现（前端 fetch 适配层 + 后端中间件）。

### 逃生门
- 若接入分布式追踪（OpenTelemetry），以 trace_id/span_id 取代 request_id 或作为其上级维度，中间件注入点不变。
