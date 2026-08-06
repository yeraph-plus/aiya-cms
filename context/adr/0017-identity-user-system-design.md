# ADR-0017: 身份系统设计（users / identities / organizations）

- 状态: accepted
- 日期: 2026-08-04
- 决策者: 项目所有者 + AI 协作
- 关联: [kernel/identity.md](../kernel/identity.md)（规格）、[kernel/auth.md](../kernel/auth.md)、[ADR-0003](0003-repository-uow-dto.md)（Repository/UoW/DTO）、[ADR-0008](0008-rbac-minimal.md)（Capability 别名）、[tests/architecture/test_db_conventions.py](../../tests/architecture/test_db_conventions.py)（表约定守护）、[ADR-0016](0016-openapi-contract-freeze.md)（契约冻结）

## 背景

用户系统是 auth / rbac / audit 与全部模块的主体基础（Principal 查询依赖）。M1.2 已交付 db 原语（`TimestampMixin`、`new_uuid7`、`Repository[Model]`、`AbstractUnitOfWork`、`Page[T]`、`JsonBModel`）并建立了表约定架构守护；身份设计必须直接对齐这些原语，并把此前散落在规格中的取舍固化为决策。本期不做 OAuth、邮箱验证与组织多租户（均为规格明确延期项），但表结构须为它们预留零迁移扩展位。

## 决策

1. **三表分拆**：`users`（展示资料）、`identities`（登录凭据 / OAuth 身份）、`organizations`（占位）。
   - 一个 User 可绑定多 Identity（`password` + 未来 `github`/`google`…），凭据数据（`secret_hash`）与展示资料隔离，OAuth 扩展只加 provider 行，不动 users 表。
   - `organizations` 无成员表、无租户逻辑，冻结最小字段（`name`/`slug`/`owner_id`）；模块禁止依赖 organizations 表做业务（ADR-0008 逃生门：组织维度后期在 Policy context 扩展）。
2. **表约定直接对齐 M1.2**：三表均 `id uuid PK default=new_uuid7` + `TimestampMixin`（tz-aware `created_at`/`updated_at`）；本期无 JSONB 列。唯一约束：`users.username`、`users.email`、`identities(provider, provider_uid)`。
3. **状态机（`User.status`: active / banned / deleted）**：
   - `active → banned`（ban，触发审计 + `user.banned`）；`banned → active`（unban，触发审计）；`active|banned → deleted`（delete）；deleted 不可逆、不可登录（AUTH_006）。
   - 非法转换抛 COMMON_409。
4. **删除策略 = 软删除 + 匿名化（非物理删除）**：保留行以维持 `refresh_tokens`、组织 `owner_id` 等外键引用完整性；email/username 匿名化为 `deleted-<uuid7>@invalid.local` / `deleted-<uuid7>`，同时释放唯一约束供新主体复用。
5. **默认角色归属**：identity 组件不依赖 rbac；auth 注册（M1.8）在同一事务内创建 User + password Identity + 默认 `reader` 角色（角色分配属 rbac M1.6）。identity 只保证"注册所需的用户状态机与唯一约束"。
6. **对外查询边界**：模块只经 `UserRead` / `IdentityService` 消费用户要素；`get_user(user_id)`（未命中 → USER_001）与 `get_users(user_ids)`（批量一次查询，防 N+1）。架构守护禁止 modules import `identity.models`。
7. **实现轮廓（对齐 M1.2 原语）**：
   - `UserRepository` / `IdentityRepository` / `OrganizationRepository` 继承 `Repository[Model]`；`IdentityService` 经 `AbstractUnitOfWork` 访问数据，不接收/导入 Session（ADR-0003）。
   - 唯一冲突捕获 `IntegrityError` → `integrity_to_app_error` → DB_002（409）；未命中 → USER_001（404）。
   - HTTP 层（M1.12）：`GET /api/v1/users`、`GET /api/v1/users/{id}`、`PATCH /api/v1/users/{id}`、`POST /api/v1/users/{id}/ban|unban`，Capability `user:read_any` / `user:update_any` / `user:ban`。
8. **事件与审计**：ban / delete 触发 `user.banned`（`{user_id, actor_id}`），审计监听器（M1.11）消费；delete 为不可逆敏感操作，必审计。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| A 三表分拆（采用） | 凭据/资料/组织解耦；OAuth 免表变更 | 查询多一次 join | 多登录方式与 OAuth 预留是确定需求 |
| B user 单表含 `secret_hash` | 表最少 | OAuth 多身份需加列/改表；凭据与资料耦合 | 与"provider 维度就位、OAuth 免迁移"冲突 |
| C 物理删除 | 无幽灵行 | 外键引用断裂；审计引用丢失 | 需要保留行（refresh_tokens / 组织 owner） |

## 后果

### 正面
- 凭据与展示资料解耦，OAuth 扩展零迁移。
- 软删除 + 匿名化保住外键完整性与审计连续性。
- 对外只暴露只读 `UserRead`，模块不触碰表细节，与 ADR-0003 数据边界一致。

### 负面 / 代价
- 三表增加一次 join；删除匿名化需保证生成值不碰撞唯一约束（`deleted-<uuid7>` 方案已覆盖）。

### 逃生门（如适用）
- 组织多租户成熟时按 ADR-0008 在 Policy context 扩展维度，organizations 表字段冻结不返工。
