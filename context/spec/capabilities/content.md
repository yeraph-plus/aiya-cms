# Content Capability 规格

## 1. 职责

content 提供通用内容实体、类型声明、状态转换、发布调度、置顶排序和内容间单向引用。它不知道 post/page/work 的具体业务含义；实际 content type 由 feature 注册。

不包含 taxonomy、comments、修订、媒体库、父子页面、前端路由、SEO 文档/标签渲染、点赞/浏览统计、下载授权或隐式插件钩子。post/page/work feature 可以在各自 Pydantic `data` schema 中声明类型化输入，但 content 不解释或渲染这些字段。work 的可下载文件列表只保存 archive opaque item 与公开清单快照；provider locator、交付 URL 和授权事实归 archive。community discussion/post 明确不注册为 content type；其表、模板、状态机和搜索归 [`community.md`](community.md)。

## 2. ContentTypeSpec

feature 注册不可变类型声明，至少包含：

- `type_name`、版本、显示名称。
- 对应 `data` 的 Pydantic schema 和 schema version。
- 允许状态、默认状态和 transition map。
- 是否允许 schedule、pin、owner 和 references。
- slug 策略、标题/正文/摘要约束。
- 正文格式、版本化 profile、UTF-8 byte 上限和发布校验策略。
- 所需 access capability keys。
- 可公开查询字段和排序选项。

ContentTypeSpec 是代码规格，不保存可执行脚本。重复 type、未知状态、无起点/终点的 transition、未登记权限或 schema 冲突必须启动失败。

### 2.1 Slug 公开路由基线

`post`、`page` 与 `work` 固定声明 `slug_policy = "generated_title_suffix_v1"`。slug 是创建后不可变的公开定位键，不是 UUID 的可逆编码，也不是授权或保密边界。

- `CreateContent` 的产品/API 输入不接收 slug；服务端从创建时的 title 自动生成。管理端只在创建成功后显示只读、可复制的 slug；`UpdateContent` 不得修改 slug，标题修改也不重算 slug。
- 生成器是版本化纯函数：对 title 采用锁定版本的 Unicode 到 ASCII 转写与 slugify 规则，输出小写 `a-z0-9-` stem；连续连字符折叠、首尾连字符移除，stem 截断至 64 个 ASCII 字符。CJK 标题必须有确定的 ASCII 转写 fixture；若结果为空，按类型使用 `post`、`page` 或 `work` 作为 stem。
- 最终值为 `<stem>-<suffix>`，其中 suffix 是由 CSPRNG 生成的 8 位小写 base32 字符 `[a-z2-7]`。因此公开 URL 保持可读，同时不暴露 UUID 或递增数据库编号；整个 slug 不超过 73 个 ASCII 字符。
- `(type_name, slug)` 唯一约束仍是并发下唯一事实来源。生成器不得以预查询代替约束；发生冲突时重新生成 suffix 并重试有限次数，耗尽后返回稳定 `content.slug_generation_failed`，不以随机覆盖或修改既有内容处理。
- 通过 slug 定位内容时只按 `(type_name, slug)` 查询。不得从 suffix 解码 content ID、建立数值主键，或把可逆/混淆编码当作访问控制。发布状态和权限仍由正常公开 Query 决定。

已发布 slug 首版没有改名、别名或重定向机制。若发布后业务确实需要迁移 URL，必须先新增版本化 route-history/redirect capability 合同；不得在更新标题时静默更换 canonical URL。

### 2.2 Markdown 正文基线

下一用户站 manifest 中的 `post`、`page` 与 `work` 固定声明：

- `body_format = "markdown"`；
- `body_profile = "gfm-v1"`；
- `body_max_bytes = 524288`，按规范化后的 UTF-8 byte 数计算，而不是按 Unicode code point 或前端字符数计算；
- format/profile 来自已注册的 ContentTypeSpec，是服务端派生的只读事实。客户端只提交 `body`，不得选择或覆盖 format/profile。

`gfm-v1` 允许标题、段落、强调/加粗/删除线、有序/无序/任务列表、引用、分隔线、行内/围栏代码、表格、链接、图片、自动链接和软/硬换行。首版明确禁止：

- raw HTML；
- MDX/JSX、`import`/`export`、表达式和可执行代码；
- YAML/TOML frontmatter；
- 任意 directive、iframe、script、style 和未经登记的扩展插件；
- `data:` URI 或把 HTML 字符串作为正文的兼容输入。

profile 是持久化合同。未来允许新语法、改变 heading ID、链接或清洗语义时必须新增 profile（如 `gfm-v2`），不得静默改变已发布正文的含义。`schema_version` 标识该 content type 的数据合同；每种类型固定 profile 时不要求给 `contents` 增加逐行 format/profile 列。

### 2.3 规范化、链接与资源引用

正文写入前由 content 的纯校验策略执行以下确定性处理：

- CRLF/CR 统一为 LF；拒绝 NUL 和除 tab/newline 外不允许的 C0 控制字符；
- 不自动 Unicode normalization、不 trim 全文，也不改写围栏代码内容；
- 解析并验证 Markdown，拒绝 profile 外语法；保存和返回的仍是规范化 Markdown 原文；
- 链接目标只允许 `https:`、`mailto:`、`tel:`、站内 root-relative `/...` 和 fragment `#...`；拒绝 `javascript:`、`vbscript:`、`data:`、`file:`、scheme-relative `//...` 以及带 username/password 的 URL；
- 不在保存、发布或 SSR 渲染期间抓取外部 URL，不以网络可达性作为链接合法条件。

首版 Markdown 图片只允许 `asset:<uuid>` 目标，不允许远程图片 URL、provider URL 或 signed URL。`asset:<uuid>` 是正文内的稳定 opaque reference，不建立 content 到 assets 的 ORM relationship/外键，也不由 content capability 导入 assets。

### 2.4 校验阶段与错误合同

`CreateContent`/`UpdateContent` 必须执行规范化、byte 上限、Markdown profile、链接 scheme 和 asset reference 形状校验，使 draft 也不能保存不可解析或可执行输入。`SubmitContent`、`ScheduleContent`、`PublishContent` 还必须调用由消费 feature 绑定的 `ContentPublicationPolicy` Port；该 Port 可通过 assets 的公开 Query/`AssetExists` Port 验证正文中的 asset 均存在且为 `ready`，但不得让 content 反向依赖 feature 或 assets。

post/page/work 进入 pending、scheduled 或 published 前必须具有非空 `body` 和非空基础列 `excerpt`。`excerpt` 是列表摘要和 SEO description fallback 的唯一正文摘要事实；类型 data 不再复制第二份 summary，不建立双写或兼容优先级。

稳定错误 code 至少包括：

- `content.body_too_large`；
- `content.markdown_invalid`；
- `content.markdown_feature_not_allowed`；
- `content.markdown_link_not_allowed`；
- `content.markdown_asset_invalid`；
- `content.excerpt_required`。

错误可携带安全的字段位置/规则标识和 request ID，但不得回显正文片段、credential、provider URL 或 parser stack。

## 3. 表所有权

### 3.1 `contents`

固定列：

- `id`、`type_name`、`schema_version`。
- `title`、`slug`、`body`、`excerpt`。
- `status`。
- 可选 `owner_type`、`owner_id` opaque reference。
- `data` JSONB，绑定注册类型的 Pydantic schema。
- `is_pinned`、`pin_rank`。
- `publish_at`、`published_at`、`schedule_version`。
- `version` 乐观并发号。
- `created_at`、`updated_at`、`archived_at`。

约束至少包括 `(type_name, slug)` 唯一、schedule 字段与状态一致、pin rank 范围、published 状态必须有 `published_at`。

### 3.2 `content_references`

- `source_content_id`、`target_content_id` 均为 content 自有外键。
- `kind`、`position`、有 schema 的 metadata。
- `(source, target, kind)` 唯一或按 kind 规格允许重复位置。

引用是单向关系，只从 source 独立查询；不递归展开、不表达父子层级。

## 4. 基础状态

能力提供以下标准状态词汇，ContentTypeSpec 选择子集和合法转换：

- `draft`
- `pending`
- `rejected`
- `scheduled`
- `published`
- `archived`

默认建议转换：

```text
draft -> pending | scheduled | published
pending -> draft | rejected | scheduled | published
rejected -> draft
scheduled -> draft | published
published -> archived
archived -> draft
```

所有状态变化使用命名 Command 和 transition 校验；不开放通用 status PATCH。发布后编辑是否回到 draft 由类型声明明确，首版默认允许更新已发布内容但保留 published 状态和乐观版本。

## 5. Commands

- `CreateContent`
- `UpdateContent`
- `SubmitContent`
- `RejectContent`
- `ScheduleContent`
- `UnscheduleContent`
- `PublishContent`
- `ArchiveContent`
- `RestoreContentToDraft`
- `SetContentPin`
- `ReplaceContentReferences`
- 运维 `PurgeArchivedContent`

Command 必须校验类型、Pydantic data、slug 生成/不可变合同、正文合同、transition、权限、owner、乐观版本和幂等键。Content capability 不因发布自动发通知、过滤关键词或奖励积分。

## 6. 定时发布

- `ScheduleContent` 设置 `status=scheduled`、UTC `publish_at` 并增加 `schedule_version`。
- Cron 只扫描到期 ID，使用 lease 或 `FOR UPDATE SKIP LOCKED` 启动 `content.publish_scheduled.v1` workflow/activity。
- 执行幂等键为 `content_id:schedule_version`。
- 发布状态和 `content.published.v1` outbox 在同一 UoW 提交。
- worker 重启后重新扫描数据库；不创建每内容一个内存 timer。
- 取消/重排会增加 schedule version，使旧任务安全失效。

## 7. 置顶与分页

默认列表排序：

```text
is_pinned DESC,
pin_rank DESC,
published_at DESC NULLS LAST,
id DESC
```

- 置顶在查询阶段排序，置顶项占用当前页容量。
- `total` 使用同一过滤条件，包含置顶项，不受 ORDER BY 影响。
- `pin_rank` 相同以 published_at/id 保证稳定顺序。
- 只返回 published 的公开列表；后台列表可按权限选择状态。
- 若未来需要独立置顶区，必须新增 `pinned_items + items + total` 契约，不能静默改变当前分页。

### 7.1 显式排序（后台列表可选）

- `sort` 为逗号分隔字段列表，`-` 前缀表示 DESC；未传时保持上方默认全结果排序（置顶优先）不变。
- 字段必须落在该类型 `ContentTypeSpec.sort_options` allowlist 内；跨类型列表取所有已注册类型 sort_options 的交集。未知或未授权字段返回 `content.invalid_sort` validation error，不静默忽略。
- 可排序列映射到固定列白名单（`id`/`title`/`slug`/`published_at`/`created_at`/`updated_at`/`pin_rank`），禁止表达式、data JSONB 内部字段或关系字段。
- 显式排序覆盖默认序（含置顶位）；排序键末尾始终追加 `id DESC` 作为唯一稳定键；`total` 语义不变。

## 8. 引用和删除

- reference 目标必须存在且允许被引用。
- 删除 source 时可删除其 outgoing references；存在 incoming references 时拒绝物理 purge。
- 业务 API 默认只 archive，不物理删除。
- purge 是有权限、审计、可 dry-run 的运维 Command，要求先解除 incoming references。
- 不级联删除被引用内容。

## 9. Events

- `content.created.v1`
- `content.updated.v1`
- `content.submitted.v1`
- `content.scheduled.v1`
- `content.schedule_cancelled.v1`
- `content.published.v1`
- `content.archived.v1`
- `content.pin_changed.v1`

事件只包含稳定基础字段和必要变更摘要；完整 body/data、渲染 HTML 和外链清单均不得进入事件，由有权限 Query 获取正文事实。GET 不产生 `content.viewed` 或任何写副作用。

## 10. 初始类型

- post feature 注册 `post`：category + tag、comments、engagement counters。
- page feature 注册 `page`：仅 category，不装配 tag、comments 或 engagement，不支持父子关系。
- work feature 注册 `work`：多 namespace taxonomy、comments、engagement counters，以及只含 archive opaque ref 的下载文件清单。
- 三者都复用 content 表、Command 和查询，不复制 ORM/Service；差异由 [`../features/content-types.md`](../features/content-types.md) 的 FeatureSpec、Pydantic data schema 与目标策略声明。
- content 只保存 Markdown 原文，不保存或返回预渲染 HTML。纯文本、目录、搜索文本和渲染缓存均为可重建投影，不是写入事实源。

## 11. Diagnostics 与验收

diagnostics 检查未知 type/schema/profile version、非法状态组合、过期 scheduled 积压、published 缺时间、孤儿 reference、已发布正文不再满足 profile/asset 发布策略和 data schema 不匹配，且不得修复。

验收必须覆盖：

- 未注册 type、非法 transition/data/权限被拒绝。
- 并发更新通过 version 防止丢失更新。
- 重复/并发定时扫描只发布一次。
- 取消后旧 schedule task 不发布。
- 置顶分页 total、页容量和稳定顺序符合本规格。
- incoming reference 阻止 purge，archive 不受影响。
- CRLF 规范化、UTF-8 byte 边界、禁止语法、危险链接和非法 asset reference 返回稳定错误。
- draft 允许保存通过基础 Markdown 校验的未完成内容，但 submit/schedule/publish 会拒绝空正文、空 excerpt 或未 ready asset。
- API、事件和数据库均不出现派生 HTML；renderer/profile 升级不会覆盖 Markdown 原文。
- slug generator 对 CJK/空标题 stem、长度边界和并发重名有 fixture；title 更新不会改变已创建 slug，公开 slug 查询不依赖 UUID 或可逆解码。
