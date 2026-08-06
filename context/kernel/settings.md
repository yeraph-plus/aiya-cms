# Kernel / settings

## 1. 设计目的

运行期可变设置（区别于 `config` 的启动期环境配置）：声明式定义 + 类型化解释 + 用户覆盖值落库 + 缓存加速。设置定义由代码登记，未登记组或字段不可读写。

设置组件负责“配置解释器”和运行期值读取，不负责启动期环境配置，也不承担 feature flag、远程配置中心或业务模块间同步调用。

## 2. 范围与依赖

- 代码位置：`inc/kernel/settings/`
- 依赖的 kernel 组件：db、cache、events、errors
- 被依赖方：api 和 modules；较低层 kernel 组件不得反向依赖 settings
- `config.Settings` 只负责进程启动期环境变量；运行期设置不从环境变量自动导入

## 3. 领域模型

### 3.1 声明式定义

```python
class SiteProfileSettings(SettingGroup):
    slug = "site.profile"
    group_title = "站点资料"
    group_description = "站点资料和展示策略"

    title = setting_field(
        slug="title",
        title="站点标题",
        description="显示在页面标题中",
        value_type=str,
        is_public=True,
        default="aiya-cms",
        validator=validate_title,
    )
```

`SettingField[T]` 的字段包括：`slug`、`title`、`description`、`value_type`、`is_public`、`default`、`validator` 和可选的声明式约束。validator 是进程内纯函数，不返回给客户端；跨字段约束由 `SettingGroup` 的组级 validator 处理。

### 3.2 解释器与读取

- `SettingInterpreter` 在启动时检查组/字段唯一性、类型、默认值和公开投影，并生成 JSON Schema 元数据。
- 解析值：代码默认值 + 数据库覆盖值 → 类型校验 → 字段/组 validator。
- 未落库时返回默认值且不创建数据库行；读路径只允许写缓存，不允许写业务库。
- 内部调用优先注入 `SettingReader`，通过字段句柄读取并保留类型信息；不得以无边界的全局 Service Locator 替代依赖注入。

## 4. 数据库

### 表：`settings`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| key | str(128) | PK | 设置组 slug，例如 `site.profile` |
| value | jsonb | not null | 仅保存用户覆盖字段 |
| updated_by | uuid | null | 最后更新者 |
| updated_at | timestamptz | not null | 最后更新时间 |

JSONB 值使用 Pydantic `SettingOverrides` 包装，并由 `SettingInterpreter` 按登记定义进行字段级验证。示例：`{\"title\": \"My Site\"}`。元数据、默认值和 validator 不落库。

当前登记组：

| slug | 定义类 | 说明 |
|---|---|---|
| site.profile | `SiteProfileSettings` | 站点资料、注册策略和公开站点值 |

`cache.home` 没有业务消费者，已从运行期 settings 删除。

## 5. 管理员 API

所有管理员接口使用 Capability：读取 `setting:read`，更新 `setting:update`。

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/v1/settings` | 无 | 所有组、字段元数据、默认值、解析值、覆盖状态 |
| PATCH | `/api/v1/settings/{group_slug}` | `{values: {...}, unset: [...]}` | 更新后的组 DTO |

GET 字段至少包含：`slug`、`title`、`description`、`type`、`is_public`、`default`、`value`、`is_overridden` 和可序列化 schema。未知字段、validator、默认值元数据和额外属性不得作为 PATCH 写入内容。

公开投影仍通过 `/api/v1/public/settings` 提供，只返回公开字段的解析值，不返回管理员元数据或私有字段。

## 6. Service / Repository / Event

- Repository 只读写 `Setting` ORM Model；更新时使用行锁合并覆盖值。
- Service 只接收/返回 Pydantic DTO，解释器负责 DTO 与覆盖值模型转换。
- 更新顺序：校验 → 写覆盖值 → commit → 清缓存 → 发布 `setting.updated` → 审计。
- 事件 payload：`{key, changed_fields, actor_id}`。

## 7. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| SETTING_001 | 404 | 设置未登记 | 未知组或字段 |
| SETTING_002 | 422 | 值校验失败 | 类型、字段 validator 或组 validator 失败 |

## 8. 测试边界

- 定义类重复组/字段 slug、默认值非法、公开投影不安全时启动 fail-fast。
- 未落库读取返回默认值且数据库无行。
- 部分覆盖不持久化默认字段；默认值改变会影响未覆盖字段。
- `unset` 删除覆盖后立即回到默认值。
- 读取缓存命中不访问数据库；更新后缓存和事件正确处理。
- 管理员 GET/PATCH Capability、metadata 返回、未知字段和公开投影边界。
