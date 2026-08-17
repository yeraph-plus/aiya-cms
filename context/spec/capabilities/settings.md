# Settings Capability 规格

## 职责

settings 保存由代码注册的结构化运行时配置及其审计/并发版本。它不管理前端文案、不读取环境 secret、不实例化 provider，也不允许数据库动态定义字段。feature/组合根在 freeze 前显式注册 group 与 Pydantic 值 schema。

## Field 合同

管理员 Field DTO 只包含稳定机器可读信息：`slug`、`type`、`type_sub`、`default`、`sensitive`、`public`、值选项和结构约束（范围、长度、pattern、枚举等）。DTO、OpenAPI 和注册定义中不得出现 `title`、`desc`、`label`、`placeholder` 或其他展示文本。

敏感字段不回显当前值，只返回 `sensitive_configured`；省略表示保留，`clear_sensitive_fields` 只能显式清除已登记敏感字段。公共投影排除 private/sensitive 值，事件、日志和审计摘要也不得包含它们。

管理端以 `group_key + slug + option value` 在本地 i18n 映射标签、帮助和选项文本，仍只依赖 OpenAPI 生成类型。未知字段/选项使用安全的本地 fallback，不由后端返回展示文字。

## 发布 settings 组

- `general`、`seo`、`entitlements`、`operations`：结构化站点和运维值。
- `notification`：邮件 provider 选择、开关、sender、SMTP/SMTP2GO 凭据；密码/API key 为 sensitive。
- `object_storage`：`storage_provider`、S3 endpoint/region/credentials、系统 bucket、头像 bucket、`s3_content_bucket`、`s3_public_base_url`、`content_image_max_edge`（默认 2560，1–8192）与 `content_image_webp_quality`（默认 85，40–100）。access/secret key 为 sensitive。
- `payments`：`provider` 为 `paypal` 或 `epay`，以及相应 PayPal/Epay 配置；client secret、webhook ID、merchant key 为 sensitive。不存在法币选择或换算设置。

settings 只保存已注册 catalog 的当前 provider key。adapter 在调用时取只读 snapshot 验证配置；更新 settings 不建立连接或探测外部服务。

## 验收

- 未注册 group/field、非法默认值、字段/值 schema 不一致和重复 slug 在启动失败。
- 更新整组原子且版本冲突明确；读取默认值不写库。
- OpenAPI/生成前端类型不含展示性元数据，管理端的中英文文案仅在本地映射。
- provider 选择不能实例化或选择未注册 adapter；敏感值不进入响应、事件、日志或审计。
