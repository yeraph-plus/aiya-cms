# Settings Capability 规格

## 1. 职责

settings 保存由代码注册的结构化配置组及其运行值，提供公开/私有读取、校验、缓存失效和审计。它不读取环境 secret，不执行数据库内脚本，也不负责前端展示逻辑。

基础设施 secret 继续由 kernel config/secret provider 管理；例外是 `site_settings` 显式登记的 SMTP 通道凭据（§5），作为 sensitive 字段承载并受公共面排除约束。

## 2. SettingGroupSpec

feature/组合根可以注册：

- group key、版本和 Pydantic value schema。
- 字段默认值、公开性、是否敏感、编辑权限。
- cache policy 和变更事件策略。
- 可选跨字段 validator。

settings 是纯被动宿主：不自行声明组；组声明由下游（feature、组合根）提供并集中在声明处维护。未知 group/field、重复 key 或无法序列化默认值必须启动失败。注册只声明 schema，不在启动时自动写库。

## 3. 表所有权

- `settings_values`：group key、schema version、value JSONB、version、updated by/at。
- 可选 `settings_history`：只保存必要审计 diff，不保存 secret；首版可依赖业务审计而不建完整版本库。

JSONB 必须按 group spec 验证。数据库缺少 row 时 Query 返回代码默认值，不因读取而插入。

## 4. Commands 与 Queries

- `UpdateSettingGroup`：完整校验后以乐观 version 更新并发布事件。
- `ResetSettingGroup`：显式恢复默认值并审计。
- `GetSettingGroup`、`ListSettingGroups`。
- `GetPublicSettings`：只返回逐字段登记为 public 的值。

不提供任意 key/value CRUD，也不允许管理员写未知字段。

## 5. SEO 组

首版由 `site_settings` feature 声明 `seo` group（组合根装配注册）：

- site name。
- default title template。
- default description。
- default share image asset reference。
- robots policy。
- canonical host。

后端只提供结构化站点默认值和内容基础数据。具体页面的 title、description、canonical、Open Graph、Twitter Card、JSON-LD 选择与前端路由由前端实现；后端不存页面路由树或生成 HTML。

`site_settings` feature 同时声明 `general`（站点通用）与 `notification` 组。`notification` 组承载 SMTP 连接参数与凭据：host/port/username/password/from_address、use_tls/starttls 全部由 settings 填写；`smtp_password` 登记为 sensitive 字段，不进入公共 DTO、事件 payload、日志和审计摘要。adapter 装配时从该组构造连接配置（见 `adapters.md` §3.1），host 未配置时启动失败。

## 6. 事件、缓存与审计

- `settings.group_updated.v1` 包含 group key、version 和安全字段变更摘要。
- adapter 可据事件失效缓存；事务提交前不得发布。
- 敏感字段不进入公共 Query、日志、事件 payload 或 diff。
- 更新要求对应 `settings.<group>.update` 权限或统一受控管理权限。

## 7. 验收

- 读取缺失设置不写库并返回验证后的默认值。
- 未知字段、错误 schema 和乐观版本冲突被拒绝。
- public DTO 不含 private/sensitive 字段；`notification` 组的 SMTP 凭据只存在于私有读取。
- SEO 设置不包含前端路由或单页渲染规则。
- cache 故障不改变事实值，更新后旧缓存最终失效。
- settings 自身不声明任何组；组声明全部来自下游并集中在声明处维护。
