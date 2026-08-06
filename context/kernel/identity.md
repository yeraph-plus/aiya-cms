# Kernel / identity（Identity / User / Organization）

## 1. 设计目的

用户要素的稳定模型：**Identity（登录凭据/OAuth 身份）与 User（资料）分表**，Organization 保留最小稳定模型占位（本期不实现多租户逻辑）。对下游只暴露"用户要素查询"能力（Principal 所需），不暴露内部表细节。

非目标：用户资料扩展字段（由后期 profile 需求再议，users 表保持最小）；组织成员/多租户（占位表先稳定）。

## 2. 范围与依赖

- 代码位置: `inc/kernel/identity/`
- 依赖的 kernel 组件: db, security, errors, logging
- 被谁依赖: rbac, auth, audit, 全部 modules（仅经 `UserRead`/`IdentityService`）
- 外部依赖: 无新增

## 3. 领域模型

- **User**：系统主体。`username`（唯一，登录展示）、`email`（唯一，通知可达）、`display_name`、`avatar_url`、`status`。
- **Identity**：一个 User 可有多条身份。`provider`（`password` / 未来 `github`/`google`…）、`provider_uid`（password 时为 email；OAuth 时为外部 id）、`secret_hash`（仅 password 有值）、`verified`。唯一约束 `(provider, provider_uid)`。
- **Organization（占位）**：`name`、`slug`、`owner_id`。无成员表、无租户隔离逻辑——字段为后期扩展冻结最小集，模块**禁止**依赖 organizations 表做业务（ADR-0008 逃生门提到组织维度后期在 Policy context 扩展）。

## 4. 状态机

User.status:

| 当前状态 | 动作 | 下一状态 | 备注 |
|---|---|---|---|
| active | ban | banned | 触发审计 + `user.banned` |
| banned | unban | active | 触发审计 |
| active | delete | deleted | 注销：匿名化 email/username，保留行（外键完整） |
| banned | delete | deleted | 同上 |

deleted 不可逆；deleted 用户不能登录（AUTH_006）。

## 5. 数据库

三表均遵循 M1.2 表约定：`id` uuid PK `default=new_uuid7` + `TimestampMixin`（tz-aware `created_at`/`updated_at`）；本期无 JSONB 列。设计决策（三表分拆、软删除+匿名化、默认角色归属）见 [ADR-0017](../adr/0017-identity-user-system-design.md)，表约定守护见 [tests/architecture/test_db_conventions.py](../../tests/architecture/test_db_conventions.py)。

### 表: `users`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | UUIDv7 |
| username | str(32) | unique, not null | 登录名 |
| email | str(320) | unique, not null | 通知主通道 |
| display_name | str(64) | not null | 展示名 |
| avatar_url | str(512) | null | |
| status | str(16) | not null, default 'active' | active/banned/deleted |
| created_at / updated_at | timestamptz | not null | mixin |

索引: `users_username_key`(unique), `users_email_key`(unique)

### 表: `identities`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | |
| user_id | uuid | FK users.id, not null | |
| provider | str(32) | not null | password/github/... |
| provider_uid | str(320) | not null | password→email；OAuth→外部 id |
| secret_hash | str(256) | null | 仅 password |
| verified | bool | not null, default false | 邮箱验证标记 |
| created_at / updated_at | timestamptz | not null | |

索引: `identities_provider_uid_key` unique(provider, provider_uid), `ix_identities_user_id`

### 表: `organizations`（占位）

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | uuid | PK | |
| name | str(128) | not null | |
| slug | str(64) | unique, not null | |
| owner_id | uuid | FK users.id, not null | |
| created_at / updated_at | timestamptz | not null | |

JSONB 字段对应的 Pydantic Model: 无（本组件无 JSONB 列）。

## 6. 公开 API

```python
class UserCreate(BaseModel):  # username, email, display_name
    ...

class UserRead(BaseModel):  # id, username, email, display_name, avatar_url, status
    ...

class IdentityService(Protocol):
    async def create_user(self, dto: UserCreate) -> UserRead       # 唯一冲突 → DB_002
    async def get_user(self, user_id: UUID) -> UserRead            # 不存在 → USER_001
    async def get_users(self, user_ids: list[UUID]) -> dict[UUID, UserRead]  # 批量，防 N+1
    async def ban(self, user_id: UUID) -> UserRead                 # 非法转换 → COMMON_409
    async def unban(self, user_id: UUID) -> UserRead               # 非法转换 → COMMON_409
    async def delete(self, user_id: UUID) -> UserRead              # 注销：匿名化 + 终态
```

实现轮廓（对齐 M1.2 原语，见 ADR-0017 §7、ADR-0018）：`UserRepository`/`IdentityRepository`/`OrganizationRepository` 继承 `Repository[Model]`，`IdentityService` 经注入的 `UoWExecutor` 访问数据，不接收/导入 Session、不自行 commit（ADR-0003）；状态转换经 Repository 锁定读取；唯一冲突捕获 `IntegrityError` → `integrity_to_app_error` → DB_002（409），未命中 → USER_001（404）。

### HTTP API

| 方法 | 路径 | Capability | 请求 DTO | 响应 DTO | 说明 |
|---|---|---|---|---|---|
| GET | /api/v1/users/{id} | user:read_any | — | UserRead | 管理端 |
| GET | /api/v1/users | user:read_any | `UserQuery`: page/size/q/status/role/date ranges/sort/order | Page[UserRead] | 管理端列表；q 匹配 username/email/display_name |
| PATCH | /api/v1/users/{id} | user:update_any | UserAdminUpdate | UserRead | 管理端改资料 |
| POST | /api/v1/users/{id}/ban | user:ban | — | UserRead | 触发审计+事件 |
| POST | /api/v1/users/{id}/unban | user:ban | — | UserRead | 触发审计 |

## 7. Pipeline

无（内核基础组件不开放注入点；用户资料扩展后期经 profile 模块以读聚合注入）。

## 8. Event

- 发布: `user.banned`、`user.unbanned`、`user.deleted`（payload: `{user_id, actor_id}`）。
- 订阅: 无。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| USER_001 | 404 | 用户不存在 | get_user 未命中 |

## 10. Cron / 任务

无。

## 11. 测试边界

- 状态机非法转换（deleted→active）抛 COMMON_409。
- username/email 唯一冲突 → DB_002 包装。
- 用户列表筛选条件之间为 AND，q 在 username/email/display_name 内为 OR；排序字段由白名单登记并追加 id。
- 批量 get_users 一次查询（无 N+1），未命中 id 不出现在结果。
- delete 后 email/username 匿名化、所有 Identity 凭据失效且原 email 可重新注册。
- 并发状态转换不能覆盖 deleted 终态。
- 架构测试：modules 中不出现 `inc.kernel.identity.models` 的 import（只能用 UserRead/IdentityService）。

## 12. 未决事项

- OAuth 实装时 identities 表无需变更（provider 维度已就位），仅需新增 Provider 适配器与回调端点。
- 邮箱验证流程（verified 翻转）待 mail 组件就绪后在 auth 中实现。
- `user.banned`、`user.unbanned`、`user.deleted` 均在事务提交后发布，显式 wiring 负责审计与封禁令牌吊销。
