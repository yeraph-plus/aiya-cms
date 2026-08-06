# ADR-0015: 健康检查契约（/healthz 与 /api/v1/health）

- 状态: accepted
- 日期: 2026-08-04
- 决策者: 项目所有者 + AI 协作
- 关联: [admin/00-overview.md](../admin/00-overview.md) 第 4 节、[m1-a1-plan.md](../m1-a1-plan.md) G0 与 M1.12、[kernel/config.md](../kernel/config.md)

## 背景

M0 已有非版本化 `/healthz`。管理员 SPA 需要供生成客户端调用的版本化健康检查（真实联调时页面展示 PostgreSQL/Redis 依赖状态），且健康检查必须严格只读。计划要求 G0 决策：保留 `/healthz`，并评估是否新增 `/api/v1/health`。

## 决策

- **保留 `/healthz`（非版本化，基础设施存活探针）**：进程活着即返回 200 `{"status": "ok"}`，不探依赖。用于 Docker/编排/K8s liveness 与运维探活。
- **新增 `GET /api/v1/health`（版本化，管理员生成客户端调用）**：

  ```json
  {
    "status": "ok" | "degraded",
    "environment": "dev",
    "version": "0.1.0",
    "dependencies": {
      "postgres": "ok" | "down",
      "redis": "ok" | "down"
    }
  }
  ```

  - `status=ok`：进程与所有依赖可用；任一依赖不可用 → `status=degraded`，HTTP 仍返回 200（页面据此展示状态，不触发告警误报）。
  - `postgres` 探针：`SELECT 1`（async 引擎执行，不落业务数据）；`redis` 探针：`PING`。
  - **只读纪律**：探针不得写业务表、不得发业务事件、不得走 pipeline；失败按依赖级降级，不抛 AppError。
  - 依赖检查带超时（如 2s），超时按 `down` 处理；依赖探针结果可短时缓存（如 5s），避免健康检查自增负载。
- **auth**：`/healthz` 与 `/api/v1/health` 均公开、无 Capability 要求。
- **实现位置**：M1.12 api 组合根（app factory 内注册），dependencies 探针由 db/cache 组件提供只读能力。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| 只保留 `/healthz` | 端点最少 | 无法用生成客户端调用、无法表达依赖状态 | 不满足 A1.4 依赖状态展示需求 |
| 单一 `/api/v1/health`，探到依赖失败返回 503 | 语义直白 | 编排探活与页面状态混用，依赖抖动会造成误报重启 | 需要进程级与依赖级两个探针 |
| 每个依赖独立端点 | 精细 | 端点爆炸、客户端复杂度上升 | 一个聚合响应即可满足页面展示 |

## 后果

### 正面
- 运维探活（`/healthz`）与应用可观测（`/api/v1/health`）职责分离。
- 管理员端可在真实联调中无副作用地展示后端与依赖状态。

### 负面 / 代价
- 两个健康端点需在文档与测试中固定契约，避免与只读纪律冲突。
- 依赖探针的缓存与超时阈值需登记，防止健康检查自身成为负载来源。

### 逃生门
- 若引入更多依赖（Meilisearch、队列等），扩展 `dependencies` 映射即可，契约向后兼容。
