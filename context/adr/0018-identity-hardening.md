# ADR-0018: Identity 事务边界与安全加固

- 状态: accepted
- 日期: 2026-08-04
- 决策者: 项目所有者 + AI 协作
- 关联: [ADR-0003](0003-repository-uow-dto.md)、[ADR-0017](0017-identity-user-system-design.md)、[kernel/db-uow-repository.md](../kernel/db-uow-repository.md)、[kernel/identity.md](../kernel/identity.md)

## 决策

1. Service 不再创建或提交事务。kernel/db 提供 `UoWExecutor`，由执行器持有 UoW 生命周期；Service 只向执行器提交读/写操作回调，写操作的 commit 只发生在执行器中。后续 Pipeline Executor 可替换该执行器并复用同一操作回调。
2. 状态转换使用 Repository 的 `SELECT ... FOR UPDATE` 锁定读取，确保 `deleted` 终态在并发 ban/unban/delete 下不可被覆盖。
3. 用户软删除时，所有 Identity 的 `provider_uid` 改为基于 identity id 的匿名值，`secret_hash` 清空、`verified` 置 false；这样原凭据不可再登录且原 email 可重新注册。
4. 生产 JWT secret 必须非空且至少 32 个字符。开发默认值只能在非生产环境使用。
5. FastAPI 请求校验错误移除不可 JSON 序列化的 Pydantic context 后再生成错误响应。

## 后果

- 用户注册等跨组件操作可在一个 Pipeline/UoW 事务中完成。
- 状态机测试需要覆盖并发转换；删除测试需要覆盖 password Identity 的凭据释放。
- Database 工厂由 kernel/db 创建，api 只消费 `session_factory`，不自行 import Session 类型。
