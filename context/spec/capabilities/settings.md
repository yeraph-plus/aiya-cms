# Settings Capability 规格

## 1. 职责

settings 保存由代码注册的结构化配置组及其运行值，提供字段定义、默认值、校验、公开/私有读取、缓存失效和审计。它不读取环境 secret，不执行数据库内脚本，也不负责具体前端组件实现。

基础设施 secret 继续由 kernel config/secret provider 管理；adapter 外部集成凭据可按对应契约由 settings 组或 secret provider 管理。由 settings 承载的凭据字段必须显式登记为 `sensitive`，并受公共面排除约束。

settings 是被动宿主：它不自行声明业务设置组，不允许运行时通过数据库创建设置字段，也不依赖数据库中的字段定义解释业务值。组和字段均由 feature/组合根显式注册。

## 2. 核心概念

### 2.1 SettingGroupSpec

下游 feature/组合根注册一个 `SettingGroupSpec`，至少包含：

- 稳定的 `group_key` 和 `schema_version`。
- 有序的 `SettingFieldSpec` 集合。
- 用于完整值校验的 Pydantic group value schema。
- 组级更新权限、cache policy 和变更事件策略。
- 可选的跨字段 validator。

注册只声明 schema，不自动创建数据库行。未知 group、重复 group key、重复 field slug、字段与 value schema 不一致或无法序列化的默认值必须在启动校验阶段失败。

### 2.2 SettingFieldSpec

字段的稳定身份是 `slug`。本期不分配数据库 field UUID，也不使用展示标题作为身份；数据库列名为 `field_slug`，值通过 `(group_key, field_slug)` 定位。

每个字段至少包含：

| 属性 | 约束 |
|---|---|
| `slug` | 小写 snake case 稳定 key，组内唯一，不得随意改名 |
| `title` | 管理员界面展示标题，不参与身份判断 |
| `desc` | 管理员界面辅助说明，可为空 |
| `type` | `bool`、`text`、`textarea`、`select`、`radio`、`mult`、`upload` |
| `type_sub` | 按 `type` 约定的子类型；没有子类型时为 null |
| `default` | 系统有效默认值，必须可 JSON 序列化并通过字段/组 schema 校验 |
| `metadata` | 受 Pydantic 模型约束的表单元数据 |
| `public` | 是否允许进入公共设置投影 |
| `sensitive` | 是否为敏感字段；不得与 `public` 同时为真 |

`title`、`desc`、`type` 和 `metadata` 是表单描述，不是后端授权边界。后端仍必须按注册的 Pydantic schema 校验值，管理员端不得仅依赖这些元数据进行安全校验。

Field 的默认值与 Pydantic value schema 的默认值不得维护为两套不一致事实。注册时必须检查一致性，或由实现从同一声明源生成其中一方。

### 2.3 Field type 语义

- `bool`：布尔值。
- `text`：单行文本。
- `textarea`：多行文本。
- `select`：从 options 中选择一个值。
- `radio`：以单选控件呈现并选择一个值。
- `mult`：有明确元素类型的一维数组；`type_sub` 声明元素类型，禁止以无约束 JSON 代替元素 schema。
- `upload`：一个 asset opaque ID 或 asset opaque ID 数组；单值/多值由 `type_sub` 或受约束的 metadata 明确声明。

`select`/`radio` 必须在 metadata 中声明稳定的 option value 和展示 label；`type_sub` 必须限制 option value 的实际类型，例如 `string` 或 `integer`。`mult`、`upload` 的 cardinality 和元素类型必须能由 schema 验证，不能只由前端约定。

metadata 可包含 `options`、`placeholder`、`rows`、`accept`、`max_length`、`max_size` 等 UI 约束，但不得包含凭据、signed URL 或其他运行期 secret。

## 3. 持久化模型

### 3.1 `settings_values`

settings capability 拥有 `settings_values` 表，每一行保存一个设置字段的持久化值，而不是保存完整 group JSON 对象：

| 列 | 含义 |
|---|---|
| `id` | UUIDv7 主键 |
| `group_key` | 注册的设置组 key |
| `field_slug` | 注册的 Field slug |
| `schema_version` | 写入该值时使用的 group schema version |
| `value` | 单字段 JSONB payload |
| `group_version` | 该行所属设置组的版本；同一组成功更新后保持一致 |
| `updated_by` | 最后修改者，可为空 |
| `created_at` / `updated_at` | UTC 时间 |

数据库约束：

- `UNIQUE (group_key, field_slug)`。
- `group_key` 和 `field_slug` 必须对应已注册的 group/Field；业务层拒绝未知项，数据库不建立跨 capability 外键。
- `value` 必须绑定 Pydantic JSONB payload；不能使用无模型的裸 JSONB。
- `group_key` 必须有查询索引；联合唯一约束满足单字段读取。

单字段 JSONB payload 只包装该字段值，不再使用旧的 `values` 字典 envelope。`schema_version` 作为列保存，避免在每个值中重复保存同一版本。

### 3.2 默认值和缺行

缺少某个 Field 行不代表值为 null。Query 必须按以下顺序构造有效值：

1. 读取该 group 已持久化的 field rows。
2. 对缺失的 registered Field 使用其 `default`。
3. 合并后的完整 group 值通过 Pydantic schema 验证。

读取不得插入默认行。显式 `ResetSettingGroup` 或设置安装/种子命令可以在事务中写入默认值，但注册和普通 Query 不产生写副作用。

### 3.3 组级版本和事务

虽然数据库一行一个 Field，公开写入仍以设置组为原子单位：

- `group_version` 是组版本，不是独立的字段版本。
- 一次成功的 group update/reset 必须在同一事务中锁定并更新该组所有已声明字段行，使其具有同一个新版本。
- PostgreSQL 在组尚无任何行时必须使用事务级数据库锁协调首次创建；禁止使用进程内锁或 Redis 锁替代数据库约束。
- 缺失行按默认值参与完整校验；成功写入后可补齐该组字段行。
- 更新必须检查 expected group version；并发冲突返回 `settings.version_conflict`。
- 组读取不得向调用方暴露半更新状态。
- 首次没有任何行时，版本为 `0`；首次成功写入后进入版本 `1`。
- 单字段直接读取可以按 `(group_key, field_slug)` 查询，但不提供绕过组 schema、权限、审计和版本控制的通用字段写入 CRUD。

这样拆分存储只改变物理行粒度，不改变设置组的完整校验、原子更新和权限语义。

## 4. Commands 与 Queries

- `UpdateSettingGroup`：接受字段值映射；未知 slug 拒绝；将当前值/默认值合并后进行完整 group schema 校验，再以 expected group version 原子写入所有字段并发布事件。
- `ResetSettingGroup`：显式恢复 registered Field defaults，更新组版本并审计。
- `GetSettingGroup`：返回 group 元数据、Field 定义、有效值、schema version 和 group version。
- `GetSettingValue`：按 registered `group_key + field_slug` 读取单字段有效值，不产生写副作用。
- `ListSettingGroups`：返回已注册组及其有效值和 Field 定义。
- `GetPublicSettings`：只返回 `public=true` 且 `sensitive=false` 的字段值；不返回私有 Field 的值或敏感元数据。

更新接口不允许未知字段，不允许任意 key/value CRUD，不允许客户端修改 Field 定义。Field metadata 由注册代码控制，管理员只能修改值。

## 5. Field DTO 和管理员表单

管理员读取 group 时，DTO 至少提供：

- `group_key`、`schema_version`、`version`。
- `fields`：按注册顺序返回的 Field DTO，包括 `slug`、`title`、`desc`、`type`、`type_sub`、`default` 和已校验的 metadata。
- `values`：按 `slug` 索引的当前有效值。
- `updated_by`、`updated_at`。

`values` 是后端事实值，不能由管理员端根据 metadata 自行推断或转换。敏感值不进入公共 DTO、事件、日志或审计摘要；管理员 HTTP DTO 也不得回显敏感当前值，只能通过 `sensitive_configured` 返回逐字段是否已配置。更新时省略敏感字段表示保留现值，`clear_sensitive_fields` 只能显式清除已登记为 sensitive 的字段，且不得与同次 `values` 写入冲突。

## 6. upload 与 assets

`upload` 字段在 settings 中只保存 assets capability 的 opaque asset ID，不保存二进制、不保存带有效期的 signed URL，也不建立数据库外键。

- 写入前可通过由组合根绑定的 `AssetExists` Port 验证 asset 为可引用状态。
- settings capability 不导入 assets capability，不直接访问 assets ORM、Repository 或表。
- 原始 settings Query 返回稳定 asset ID。
- 需要 URL 的 feature/API 响应通过 Port 或消费方 Query 在请求时解析 URL；signed URL 只存在于响应期间，不进入 settings 数据库、缓存、事件或审计。
- 解析 URL 必须带明确的 expiry 和授权上下文；不能把 ID 静默替换成永久 URL。

因此管理端可以通过 Field 类型识别上传控件，下游也可以使用 resolved projection 获得 URL，而 settings 的持久化事实仍是 asset ID。

## 7. 首版 settings 组

首版由 `site_settings` feature 声明以下 group：

- `general`：站点通用设置，至少包含 `site_logo_asset_id` 站点 LOGO asset ID。
- `seo`：结构化站点默认值。
- `notification`：Email 总开关、SMTP/SMTP2GO provider 开关、复用的 sender 字段、SMTP 连接设置和 SMTP2GO region/API key。
- `object_storage`：S3-compatible 资产存储设置。
- `entitlements`：注册奖励、邀请奖励、赠送额度等整数数值。
- `operations`：`audit_retention_days`，审计和终态自动执行日志的保留天数。

`seo` 至少包含 site name、default title template、default description、default share image asset、robots policy 和 canonical host。后端不存页面路由树，不生成页面 HTML；具体页面 SEO 选择由前端实现。

`notification` 的 SMTP password、SMTP2GO API key 和 `object_storage` 的 S3 access key/secret key 必须登记为 `sensitive`。`object_storage.s3_bucket` 是系统设置资源 bucket，`object_storage.s3_avatar_bucket` 是用户头像专用 bucket；两者都由设置提供名称，不允许业务端硬编码。`entitlements` 只保存数值，业务 feature 读取后调用 points behavior；settings 不执行积分逻辑。

## 8. 事件、缓存与审计

- `settings.group_updated.v1` 包含 group key、group version 和不含敏感字段的 `changed_fields` slug 列表。
- 事件必须与 settings 行变更位于同一事务，事务提交前不得发布。
- cache adapter 可按 group key/version 缓存完整有效 group，更新事件负责最终失效；缓存故障不得改变事实值。
- 敏感字段不得进入公共 Query、事件 payload、日志或审计 diff。
- 更新要求对应 `settings.<group>.update` 权限或统一受控管理权限。

## 9. 基线重构和迁移策略

本项目尚未上线，当前 settings 表结构和实现不构成存量兼容合同。本次 Field/逐行存储重构：

- 本阶段只更新规格，不新增兼容迁移，不维护旧 group-row 数据的升级路径。
- 第二阶段直接重写 settings capability 的 model、repository/query、command、DTO、测试和管理端消费契约。
- 实现阶段可使用临时迁移验证数据库，但最终把逐行 `settings_values` 结构合并/squash 到新的 `alembic/versions/0001_initial.py`。
- `0001_initial` 发布前允许改写当前 Demo 基线；新基线发布后恢复正常迁移纪律，不再直接改写已发布 revision。
- 迁移验收必须覆盖空库 upgrade、metadata diff、重复 `(group_key, field_slug)` 拒绝、缺行默认值、组级并发更新和 reset。

## 10. 验收

- group/Field 未注册、slug 重复、字段 schema 不一致或默认值非法时启动失败。
- 读取缺失 Field 行不写库，并返回验证后的 Field default。
- 一组多个 Field 的更新在同一事务中完成，不产生半更新读取。
- 未知 Field、错误类型、错误 metadata 选项和乐观版本冲突被拒绝。
- 单字段读取使用 `(group_key, field_slug)` 定位，不绕过 group schema 和权限边界。
- public DTO 不含 private/sensitive 字段；SMTP/S3 凭据不进入事件、日志和审计。
- `upload` 只持久化 asset ID，URL 按请求解析且不持久化。
- SEO 设置不包含前端路由或单页渲染规则。
- settings 自身不声明任何业务组；所有 group/Field 声明来自下游并在组合根 freeze 前完成。
