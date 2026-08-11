# Assets Capability 规格

## 1. 职责

assets 只管理外部图床、S3 或兼容对象存储上的稳定对象引用和 SDK 交互。系统不保存二进制文件，不提供文件夹、图库、在线编辑、图片处理、修订或 WordPress 媒体库兼容。

## 2. AssetRef

稳定 DTO 至少包含：

- asset ID。
- provider key。
- bucket/container 和 object key。
- mime type、byte size、checksum。
- alt text 和受 Pydantic 约束的 metadata。
- state、created/updated/deleted time。

数据库和业务 DTO 禁止保存带有效期的 signed URL。URL 由 Query 通过 provider adapter 按请求生成并携带明确 expiry。

## 3. 表所有权

- `assets_objects`：稳定引用、完整性元数据、状态。
- `assets_upload_intents`：可选，记录短期上传意图 owner、bucket、目标 object key、digest、expires/consumed state。

状态至少为 `pending`、`ready`、`failed`、`deleted`。外部对象是否存在由 provider/diagnostics 确认，不能仅靠本地 row 推断。

## 4. Provider Port

assets 自己声明 `ObjectStorageProvider`：

- 创建受限 upload intent 或执行 server-side upload。
- head/stat 对象。
- 生成短期 read URL。
- 删除对象。

`ObjectStat` may return the provider bucket/container so Finalize can persist the complete stable reference.

adapter 负责 SDK client、endpoint、credential、timeout、重试和 provider error 映射。S3-compatible adapter 的连接配置与凭据由 `site_settings.object_storage` 组保存；凭据字段必须登记为 sensitive，不进入公共 DTO、事件、日志或审计摘要。

## 5. Commands 与 Queries

- `CreateUploadIntent`：分配不可预测 object key 和受限上传条件。
- `FinalizeAsset`：通过 provider stat 校验 size/mime/checksum 后转 ready。
- `RegisterExternalAsset`：仅受信服务端流程可登记已存在对象。
- `UpdateAssetMetadata`。
- `DeleteAsset`：先标记，再由幂等 activity 删除外部对象。
- `GetAsset`、`ResolveAssetUrl`。
- 管理端 `ListAssets`：按 state、provider、bucket 或 object key 查询稳定引用并分页；它不返回 signed URL，也不构成媒体库。

provider 调用不得与长数据库事务绑定。Finalize/Delete 使用 workflow/activity 处理跨系统部分失败。

## 6. 跨能力使用

- content/settings/identity 只保存 asset opaque ID 或 AssetRef JSON，不建 assets 外键。
- 系统站点资源使用 `object_storage.s3_bucket`；用户头像使用 `object_storage.s3_avatar_bucket`。bucket 由组合根选择并通过 assets Command 传入，assets 不理解业务类型。
- 写入引用前可通过消费方 `AssetExists` Port 验证 ready 状态。
- assets 不维护“被哪些业务对象使用”的跨能力反向索引；物理删除前由 feature/运维流程检查引用。

## 7. 安全

- upload intent 限制 object key/prefix、content length、mime、checksum、expiry 和一次性使用。
- object key 不使用原始文件名作为唯一安全边界。
- provider credential、signed URL 和原始 SDK 错误不得记录。
- 对公开/私有资源生成 URL 的授权由调用 feature/access 决定，assets adapter 只执行明确策略。

## 8. Diagnostics 与验收

- diagnostics 报告长期 pending、删除失败、本地 ready 但远端缺失、checksum/size 异常；深度远端扫描需显式运行。
- signed URL 不持久化且过期时间正确。
- 重复 finalize/delete 幂等。
- provider 超时/失败可恢复，不产生错误 ready 状态。
- capability 不演变为媒体库 UI 或二进制代理服务。
