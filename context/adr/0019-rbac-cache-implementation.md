# ADR-0019: RBAC 与缓存内核实现边界

- 状态: accepted
- 日期: 2026-08-04
- 关联: [kernel/rbac.md](../kernel/rbac.md)、[kernel/cache.md](../kernel/cache.md)、[ADR-0008](0008-rbac-minimal.md)

## 决策

1. RBAC 只暴露 DTO、`Principal`、Capability 注册表、纯 Policy、Checker 与显式 UoW Service；ORM、Repository 和迁移仍留在内核组件内部。
2. `role_permissions` 与 `user_roles` 是关联表，使用联合主键并由数据库保证幂等；它们是全局 UUID 主键约定的明确关联表例外。
3. Capability 别名由代码登记表和 seed 清单共同约束。`require_capability` 在构造依赖时拒绝未登记别名；启动 wiring 可调用 `validate_capability_registry` 做 fail-fast 校验。
4. 缓存值统一为字符串。Memory 实现提供进程内 TTL 与每 key 单飞锁；Redis 实现只负责远端存取，连接或操作失败时降级到同一实例的 Memory 实现并记录内部日志，不把缓存故障传播到业务请求。
5. 缓存工厂保持同步构造 API；Redis 的可用性在首次异步操作时确认，避免启动阶段阻塞事件循环。

## 后果

- 权限变更不依赖旧快照；登录或请求装配 Principal 时重新查询角色能力。
- 多进程之间的缓存一致性和失效广播仍不是本期目标。
- 关联表不适用通用单主键 Repository；RBAC UoW 使用专用查询。
