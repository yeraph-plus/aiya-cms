# ADR-0031: 声明式运行期设置模型与稀疏覆盖值

- 状态: accepted
- 日期: 2026-08-06
- 决策者: 项目维护者
- 关联: `context/kernel/settings.md`、ADR-0003、ADR-0009、ADR-0025、ADR-0027

## 背景

运行期设置需要同时服务于代码读取、管理员配置页面和公开投影。现有实现将 Pydantic 值模型、注册元数据和 HTTP 特例分散维护，数据库还会保存补齐默认值后的完整对象，导致默认值演进和动态管理页面都不够清晰。

## 决策

1. 设置以 `SettingGroup` 抽象父类和 `SettingField[T]` 声明式字段定义登记。每个字段包含 `slug`、标题、描述、类型、默认值、公开标记和后端 validator；组级 validator 负责跨字段约束。
2. `SettingInterpreter` 是唯一解释边界，负责启动期 fail-fast、类型校验、默认值解析、稀疏覆盖合并、公开投影和 JSON Schema 元数据生成。validator 只能是进程内纯函数，不序列化到 HTTP。
3. `settings.value` 仅保存用户覆盖字段，例如 `{\"title\": \"My Site\"}`。读取结果为代码默认值与数据库覆盖值合并后的解析值；未设置的字段不写库，`unset` 后恢复默认值。
4. 管理端设置 API 统一为：`GET /api/v1/settings` 返回所有组和字段元数据、默认值、解析值及覆盖状态；`PATCH /api/v1/settings/{group_slug}` 只接受用户值和 `unset`，并要求 `setting:read` / `setting:update` Capability。
5. `/api/v1/public/settings` 保留为独立公开投影，仅返回 `is_public` 字段的解析值，不返回默认值、私有值、validator 或内部 schema。它不属于管理员设置接口。
6. 内部读取优先通过注入的 `SettingReader` 完成，字段句柄提供静态类型；不引入无边界的进程级全局 Service Locator。较低层 kernel 组件不得反向依赖 settings。
7. `cache.home` 没有业务消费者，删除其登记、模型和 API 暴露；缓存基础设施配置继续属于启动期 `config.Settings` 或具体消费者配置。

## 备选方案

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 抽象组/字段 + 解释器 + 稀疏 JSONB 覆盖 | 声明集中、默认值可演进、管理端可动态生成 | 需要新增解释器和 unset 语义 | 采用 |
| B. 继续每个 key 一个完整 Pydantic Model | 改动小 | 元数据重复，默认值和覆盖值混杂 | 不采用 |
| C. 每个字段一行数据库记录 | 字段更新简单 | 行数和事务复杂度增加，失去组级原子更新 | 不采用 |

## 后果

### 正面

- 不需要新增数据表，现有 `settings` 表可继续使用。
- 新字段和默认值只需改声明类；未覆盖字段会自动获得新默认值。
- 管理员读取可以直接驱动动态表单，公开投影由字段标记生成。

### 代价

- 更新必须明确区分覆盖值和恢复默认值。
- callback 不是可序列化 API 元数据；需要用类型/schema/约束提供前端提示。
- 旧的 `cache.home` 和重复 settings 路由不再保留；开发期数据需要按新语义重建。

## 测试边界

- 声明类重复组/字段 slug、非法默认值、缺少公开约束时启动失败。
- 未落库读取不写数据库并返回默认值；部分覆盖只返回覆盖字段的新值。
- 默认值变更影响未覆盖字段；`unset` 后恢复默认值。
- 字段类型、字段 validator、组级 validator 失败返回 `SETTING_002`。
- 管理员 GET 返回完整元数据；PATCH 拒绝 metadata、未知字段和未授权请求。
- 公开接口只返回公开字段，不泄露默认值、私有字段和 validator。
