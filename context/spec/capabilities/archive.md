# Archive Capability 规格

> 本文件定义下一用户站发布目标。本轮只建立规格，不创建模型、迁移、adapter、router 或下载服务。

## 1. 职责与选择

`archive` 管理可下载文件的稳定逻辑引用、外部托管 locator、发布可用性、下载授权和交付尝试。它消费 `ArchiveDeliveryProvider` Port，对接 OpenList、Gofile 或未来其他下载托管系统。

该职责不扩展现有 assets：assets 继续负责站内对象存储、图片/头像、upload intent 和图床成品；archive 负责大文件分卷、外部下载目录、付费交付和短时链接。二者可以都引用同一物理存储，但不得共享 ORM、表、provider DTO 或生命周期状态。

archive 不计算积分价格、不扣积分、不读取 content/points/identity 表。计费由 business_center 编排；content JSONB 只保存 archive item 的公开 opaque ref 与展示快照。

## 2. 表所有权

### 2.1 `archive_items`

- `id`、immutable `item_key`；
- `provider_key` 与 provider contract version；
- 加密/受保护的 `external_locator` Pydantic JSONB；
- `display_name`、`size_bytes`、可选 checksum algorithm/value；
- `part_number`、`state=pending|active|unavailable|retired`；
- provider fact version、last verified time；
- optimistic `version` 与时间字段。

external locator 可以是 OpenList mount path 或 Gofile content ID，但不进入公开 DTO、事件、日志或 content JSONB。provider 切换不重新解释既有 locator；迁移 item 必须通过命名 Command 建立新 provider snapshot 并审计。

### 2.2 `archive_download_grants`

- `id`、subject opaque ref；
- business product、quote、points entry opaque refs；
- target type/id、manifest version/digest；
- granted file item IDs 的版本化 snapshot；
- `status=pending|active|expired|revoked|failed`；
- `valid_from`、`expires_at`、idempotency key digest；
- version 与时间字段。

grant 不保存 provider URL、access token、secret headers 或浏览器 cookie。一个 business consumption 最多产生一个 grant。

### 2.3 `archive_delivery_attempts`

- grant、item、provider key；
- attempt number、状态、安全 reason code；
- provider delivery opaque ref（若存在）；
- link expiry、started/completed 时间；
- 不保存 raw URL、credential 或完整 provider response。

## 3. 文件与 manifest 规则

- `size_bytes > 0`，part number 为正整数，同一发布 manifest 内唯一。
- 4 GiB 分卷 profile key 为 `archive.part.4g.v1`；除最后一卷外必须为 `4 * 1024^3` bytes，最后一卷不超过该值。
- archive item active 表示 provider locator 经显式校验可解析，不保证 provider 此刻在线。
- content 的 work JSONB 保存 `archive_item_id/display_name/part_number/size/checksum` 快照；archive Query 是发布校验和交付时的事实来源。
- retired item 不再进入新 manifest/grant，但既有审计事实保留。

## 4. `ArchiveDeliveryProvider` Port

Port 输入输出使用 archive 自有 Pydantic DTO：

- `check_availability(settings_snapshot) -> Availability`；
- `stat(external_locator, settings_snapshot) -> ProviderFileFact`；
- `create_delivery(request, settings_snapshot) -> ProviderDelivery`；
- `refresh_delivery(provider_delivery_ref, request, settings_snapshot)`；
- `revoke_delivery(provider_delivery_ref, settings_snapshot)`（provider 支持时）；
- 可选 `list_children` 只用于管理员显式导入，不参与用户 GET。

`ProviderDelivery` 只能返回：

- browser-safe、短时 `redirect_url`；或
- 不暴露 provider secret 的站内/proxy ticket；或
- `proxy_required` typed result。

若 provider 下载必须携带账号 token、Cookie、Authorization 或其他 secret header，adapter 不得把 header 返回浏览器。部署必须提供受信 proxy/signed delivery 方案，否则该 item 不可发布为付费下载。

## 5. Provider catalog

组合根启动时注册全部允许实现：

```text
archive.openlist
archive.gofile
```

settings 保存当前导入 provider 和各 provider 配置；每个 archive item 永久绑定创建/迁移时的 provider key，交付按 item key 解析，不因“当前默认 provider”变化而重解释历史项。

OpenList adapter 计划使用官方 REST 文件查询/链接合同，至少覆盖文件详情和 link 解析。OpenList 可能返回直链、代理链接及必须携带的 headers；adapter 只输出 browser-safe 结果，且 token 由服务端 settings 提供。

Gofile adapter 计划使用官方 API 的 folder/content 查询和 direct link 合同。Gofile API 当前标记为 beta、部分能力要求 Premium 且有不公开阈值的 rate limit，因此 adapter 必须锁定已测试 contract version、处理 429、设置有限 timeout，并始终生成有期限的 direct link；不得依赖永久公开 folder URL作为付费授权。

两者均为薄 adapter/SDK 边界。是否采用第三方 Python SDK必须在实现前完成维护状态、许可证、类型质量与 credential 处理审查；无合适 SDK 时使用受控 HTTP client 实现，不把远程 JSON 泄漏到 capability。

## 6. Commands、Queries 与 Activity

Commands：

- `RegisterArchiveItem`、`VerifyArchiveItem`、`ActivateArchiveItem`；
- `MarkArchiveItemUnavailable`、`RetireArchiveItem`；
- `MigrateArchiveItemProvider`；
- `IssueDownloadGrant`、`ActivateDownloadGrant`、`ExpireDownloadGrant`、`RevokeDownloadGrant`；
- `RecordDeliveryAttempt`。

Queries：

- `GetArchiveItemPublic`、`BatchGetArchiveItemsPublic`；
- `GetArchiveItemAdmin`、`ListArchiveItemsAdmin`；
- `GetDownloadGrantForSubject`、`ListDownloadGrantsForSubject`；
- `GetGrantCostBasis`：只返回 file count、size、manifest digest，不返回积分价格。

Activity：

- `ResolveDownloadLinks`：按 grant snapshot 为每个 item 调用绑定 provider，记录安全 attempt，返回短时交付 DTO。

Query 不 probe provider、不刷新链接、不修改状态。provider stat/link 只能由显式 Command/Activity 调用。

## 7. HTTP 与权限

管理员普通管理面：

- `GET/POST /api/v1/admin/archive/items`；
- `GET/PATCH /api/v1/admin/archive/items/{item_id}`；
- `POST .../verify|activate|retire|migrate-provider`；
- `GET /api/v1/admin/archive/grants` 和 grant detail。

用户 grant/link 端点由 business_center 组合，不由 archive 导出任意 subject 的通用 router。

权限至少包括 `archive.items.read`、`archive.items.manage`、`archive.items.verify`、`archive.grants.read`、`archive.grants.revoke`。provider locator 与 availability detail 只在管理员授权 DTO 中返回脱敏摘要。

## 8. 事件与错误

事件：`archive.item_registered.v1`、`archive.item_activated.v1`、`archive.item_unavailable.v1`、`archive.item_retired.v1`、`archive.grant_issued.v1`、`archive.grant_activated.v1`、`archive.grant_expired.v1`、`archive.grant_revoked.v1`。

稳定错误至少包括 `archive.item_not_deliverable`、`archive.manifest_mismatch`、`archive.provider_unavailable`、`archive.delivery_not_browser_safe`、`archive.grant_expired`、`archive.grant_forbidden`、`archive.version_conflict`。

事件不包含 locator、URL、provider payload、subject 隐私信息或 points 余额。

## 9. 验收

- archive 不导入 assets/content/points/identity；所有跨能力引用 opaque。
- OpenList/Gofile adapter import 和注册无网络副作用；调用时才读取 settings snapshot。
- content/work JSONB 和 public OpenAPI 无 locator、token、secret header 或 direct URL。
- quote 后 manifest 漂移会拒绝消费；grant 只能由匹配 subject/client 获取。
- 链接有期限，刷新幂等且 grant 窗口内不重复扣积分。
- provider 429、timeout、contract drift、仅 header 鉴权链接均转为安全 typed result。
- migration、provider HTTP mock、grant 并发、过期/撤销和日志脱敏有合同测试。

## 10. 外部合同参考

- OpenList 官方 API/文件链接文档：`https://doc.oplist.org/api`、`https://doc.oplist.org/guide/advanced/mcp`。
- Gofile 官方 API：`https://gofile.io/api`。其 beta/Premium/rate-limit 状态必须在实现时重新核验。
