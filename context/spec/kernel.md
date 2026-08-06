# Kernel 公共规格

## 1. 公共组件

稳定组件包括 config、errors、logging、db、cache、security、identity、auth、rbac、events、pipeline、tasks、mail、audit、settings、content、taxonomy、comment。

各组件只从其 `__init__.py` 导出公共 API；models、repositories、uow、internal registry 仅供组合根、迁移和测试使用。模块不得依赖未登记的深层实现路径。

## 2. 稳定契约

- DB：`Database`、`Base`、`UoWExecutor`、Repository/Page/UUIDv7/JsonBModel。
- Security/Auth：Principal、密码哈希、JWT 双令牌、登录/刷新/退出、身份状态机。
- RBAC：Capability 别名、PolicyContext、`require_capability`，后端是最终授权边界。
- Events：显式事件类型注册、异步 handler、失败隔离、`wait_idle()`；运行期禁止新增订阅。
- Pipeline：显式 key、read/write kind、before/core/after、事务 UoW 与扩展槽校验。
- Tasks：持久化状态机、重试/取消/回滚、Cron 注册和 LISTEN/NOTIFY 唤醒提示。
- Mail/Audit/Settings：outbox 重投、异步审计、登记式配置解释器与缓存。

## 3. CMS 通用内核

- Content、Taxonomy、Comment 的通用 ORM/Repository/UoW/Service/DTO/事件在 kernel。
- `ContentTypeRegistry` 显式注册、编译、校验、冻结；不提供自动发现。
- JSONB content data 只保存声明字段且所有持久化值为字符串。
- `comment_count` 通过评论事件维护，并由 recount 任务修复最终一致性。

## 4. 兼容性与测试

- 公开导入路径和关键签名由契约测试锁定；新增公开符号必须同步本规格与测试。
- 基础表结构只允许向后兼容迁移；迁移必须可 upgrade/downgrade/upgrade。
- kernel architecture tests 必须持续验证依赖红线、Session/DTO 边界、JSONB、裸 SQL 和登记完整性。
