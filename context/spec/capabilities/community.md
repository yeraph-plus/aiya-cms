# Community Capability 规格

## 1. 职责与边界

`community` 提供单一站点社区中的讨论（discussion）、帖子（post）、社区标签（tag）、审核状态、锁定、领域内搜索和讨论列表排序。其交互模型借鉴 Flarum 的 discussion stream 与 tags 页面，但不复制 Flarum 的运行时扩展系统、JSON:API 或数据库结构。

该能力是独立 capability，而不是 `content` 的新 type：

- `community_discussions`、`community_posts`、`community_tags`、关联表和搜索投影全部由 community 拥有；
- 不导入或写入 content、taxonomy、comments、engagement 的 ORM、Repository、表或 registry；
- discussion 不是 content，reply 不是 comments，community tag 也不是 taxonomy term；
- 可以采用与 content 相同的外部 Markdown 行为和相似的类型声明模式，但模板 key、状态机、Command、事件、DTO、迁移和错误码均为 community 自有合同；
- identity subject 只以 `(author_type, author_id)` opaque reference 保存，由 community 定义并消费的 `CommunityAuthorPort` 校验和投影公开作者信息，不建立跨 capability 外键；
- notification、points、assets、mentions、spam/report 等后续行为只能由显式 feature 消费 community 的公开事件/Command 组装，community 不自动反向调用兄弟 capability。

首版只支持一个社区实例，不增加 `community_id`、租户或版块空间模型。未来需要多个独立社区时必须先新增明确的 scope、唯一键、授权和迁移合同，不能把 nullable `community_id` 临时塞入现有查询。

## 2. DiscussionTemplateSpec

组合根显式注册不可变 `DiscussionTemplateSpec`。它类似 `ContentTypeSpec` 的声明方式，但只服务 community，至少包含：

- 稳定 `template_key`、版本、显示名称；
- discussion `data` 与首帖/回复 `data` 的 Pydantic schema 和 schema version；
- 标题、首帖、回复的长度与正文 profile；
- discussion 合法状态、默认状态和 transition map；
- 新 discussion 与 reply 的审核策略；
- primary/secondary tag 数量约束；
- 创建、回复、编辑、审核、锁定和管理标签所需的 access capability keys；
- 允许公开返回的 data 字段。

首个产品 manifest 注册 `general` 模板，固定首帖/回复 `body_max_bytes=262144`、`min_primary_tags=1`、`max_primary_tags=1`、`min_secondary_tags=0`、`max_secondary_tags=5`，并在调用者具有 create/reply 权限时直接 published；pending 状态保留给后续显式审核策略和 moderator Command，不由数据库设置临时切换。所有 tag 上下限和审核默认值必须在声明中显式给出，不从数据库设置或客户端输入推断。重复 template、未知状态、非法 transition、未登记权限、无 Pydantic schema 或 profile 冲突必须启动失败。

模板只声明校验和已有状态机参数，不保存或执行脚本。若 Q&A、投票、悬赏等新类型需要新的事实表、Command 或生命周期，应先扩展 community 规格或由新 capability/feature 承担；不得把任意 JSONB 表单当作万能业务插件。

### 2.1 正文合同

首帖与回复保存规范化 Markdown 原文，首版 profile 为 `gfm-v1`。其可观察语法、安全链接、raw HTML/MDX/directive 禁止项和渲染边界与 [`content.md`](content.md) 的 `gfm-v1` 一致，但 community 不导入 content 实现，也不调用 content Command/Query。

- request 只提交 `body`；`body_format="markdown"`、`body_profile="gfm-v1"` 由 template 派生并在 DTO 中只读返回；
- 每种 template 必须分别声明首帖与回复的 UTF-8 byte 上限；
- CRLF/CR 统一为 LF，拒绝 NUL、危险 scheme、raw HTML、MDX 和未登记扩展；
- 首版不支持图片、附件、`asset:<uuid>`、远程图片或 embed；需要 assets 时先新增由消费方 Port 校验的版本化 profile；
- 数据库、事件和 OpenAPI 不保存或返回派生 HTML。搜索文本是可从 Markdown 原文重建的投影，不得反向覆盖原文。

共享 parser/fixture 是代码复用，不改变能力所有权。profile 语义变化必须新增版本，不能因 content renderer 升级而静默改变已存 community post。

## 3. 表所有权

所有表使用 `community_` 前缀，并只由 community migration 修改。

### 3.1 `community_discussions`

- `id`、`template_key`、`schema_version`；
- `title`、创建后不可变的 `slug`；
- `status`：`draft | pending | published | hidden | archived`；
- `author_type`、`author_id` opaque reference；
- `data` JSONB，绑定 template 的 Pydantic schema；
- `is_locked`、`locked_at`、`locked_by_type`、`locked_by_id`；
- `first_post_id`、`last_post_id`，均为本 capability 内的 post reference；
- `reply_count`：当前 published 且非首帖的 reply 数；
- `last_posted_at`：当前最后一个 published post 的时间；
- `version`、`created_at`、`updated_at`、`published_at`、`hidden_at`、`archived_at`。

`(template_key, slug)` 唯一。published discussion 必须存在 published 首帖、`published_at`、`last_post_id` 和 `last_posted_at`。`reply_count`、last post 和 last time 是 community 同一事务维护的可校验摘要，不由 GET 临时回写。

slug 使用 community 自有、版本化的 `community_title_suffix_v1`：从创建时 title 生成可读 ASCII stem，加 8 位 CSPRNG base32 suffix；CJK 转写必须有固定 fixture，转写结果为空时使用 `discussion` stem。创建后不随 title 编辑改变。并发唯一性以数据库约束为准，冲突有限重试，耗尽返回 `community.slug_generation_failed`。公开 URL 不暴露或解码 UUID/递增 ID。

### 3.2 `community_posts`

- `id`、`discussion_id` community 内部外键；
- `number`：discussion 内从 1 递增的不可变序号，`1` 固定为首帖；
- `post_type`：首版只允许 `comment`，系统时间线事件不伪装成 post；
- `status`：`pending | published | hidden | deleted`；
- `author_type`、`author_id` opaque reference；
- `body` Markdown 原文、`body_profile`、`schema_version`、Pydantic `data` JSONB；
- `version`、`created_at`、`edited_at`、`published_at`、`hidden_at`、`deleted_at`。

`(discussion_id, number)` 唯一。`CreateDiscussion` 必须在一个 UoW 中创建 discussion 与 number=1 的首帖；事务提交后不得出现无首帖 discussion。reply 分配序号必须并发安全，删除/隐藏后不重排或复用 number。

公开 post stream 只计数和返回 published post，按 `number ASC, id ASC` 稳定分页。hidden/deleted post 对普通用户不返回正文；审核 Query 可以按权限查看安全摘要。删除需要清除正文时仍保留最小 tombstone、序号和审计事实。

### 3.3 `community_tags`

- `id`、`kind=primary|secondary`；
- 可选 `parent_id`，只指向同表 active primary tag；
- `name`、`slug`、`description`、受控 `color`、受控 `icon_key`；
- `position`、`status=active|archived`；
- 有 schema 的 `metadata` JSONB、`version`、时间字段。

tag slug 全局唯一。primary tag 最多一层父子关系：root primary 可以拥有 child primary，child 不得再有子项；secondary tag 必须无 parent。禁止环、自引用和跨 kind parent。`color`/`icon_key` 是结构化展示值，不允许 HTML、CSS 或可执行模板。

### 3.4 `community_discussion_tags`

- `discussion_id`、`tag_id` 均为 community 内部强外键；
- `position`、`assigned_at`；
- `(discussion_id, tag_id)` 唯一。

同一 discussion 的 primary/secondary 数量必须满足其 template 声明。archived tag 保留既有 assignment 以保持历史事实，但不能新分配；discussion archive 不级联删除 tag。

### 3.5 `community_search_documents`

搜索投影按 discussion title 和每个 post 分行保存：

- `id`、`discussion_id`、可选 `post_id`；
- `document_kind=title|post`；
- `search_profile`、`normalized_text`、`source_version`、`updated_at`；
- title document 每 discussion 唯一，post document 每 post 唯一。

它是 community 自有、可重建的读模型，不是第二正文事实源。source 写入、编辑、发布、隐藏或删除时必须在同一 UoW 更新/移除对应可搜索文档，确保未发布或已隐藏正文不会因最终一致性窗口泄露。

首版 `community_trigram_v1` 使用 PostgreSQL `pg_trgm` 的 GIN trigram 索引，同时覆盖中文等无空格文本和 ASCII 文本。migration 必须显式建立 extension/索引并在缺失时失败，不得静默退化为无索引全表 `%LIKE%`。未来外置搜索必须通过新版 Port、outbox/inbox、权限后过滤和重建合同引入。

## 4. 状态与业务流

discussion 基础转换：

```text
draft -> pending | published
pending -> draft | published | hidden
published -> hidden | archived
hidden -> published | archived
archived -> published
```

- `CreateDiscussion` 原子创建 discussion 与首帖；初始状态由 template + Principal 权限决定，客户端不能自报 published。
- draft/pending discussion 及其首帖不进入公开列表、tag count、search 或 `latest/top/newest`。
- `CreateReply` 在 unlocked published discussion 上执行；初始 post 状态由 template + Principal 权限决定。
- 只有 reply 变为 published 时才增加 `reply_count` 并更新 `last_post_id/last_posted_at`；隐藏/删除当前最后 reply 时必须在同一事务重算摘要。
- lock 只阻止普通用户新增 reply，不改变已有可见性、搜索和排序；有明确权限的 moderator Command 可绕过。
- 隐藏首帖必须同时隐藏 discussion；恢复 discussion 时必须先保证首帖 published。
- archive 是 discussion 的业务终态入口，默认不可回复且不出现在公开查询；物理 purge 不进入普通 API。

所有转换通过命名 Command 和乐观 `version` 校验，不开放通用 status/locked 字段 PATCH。

## 5. Tags 规则

- `CreateTag`、`UpdateTag`、`ArchiveTag`、`ReorderTags` 管理 Tags 分区；普通读取不写入 definition row。
- `ReplaceDiscussionTags` 一次性替换 discussion 的完整 tag 集合，校验 active 状态、层级、template 数量和权限。
- 公开 Tags 分区按 `kind, parent.position, position, name, id` 稳定排序，并返回每个 tag 的 published discussion count；count 是只读聚合/投影，不由 GET 回写。
- 列表 `tag=<slug>` 首版只接受一个 active tag，匹配直接 assignment；选择 parent 不隐式包含 child。未来需要 descendant 聚合时新增显式参数和索引合同。
- tag 默认 archive，不级联隐藏或删除 discussion；有 assignment 时禁止物理删除。

community tag 与通用 taxonomy 的 `category/tag` 没有同步、镜像或共享 ID。需要跨域导航时由用户站分别查询并组合链接，不建立双写。

## 6. 搜索、过滤、排序与分页

公开 `ListDiscussions` 支持：

- `q`：搜索 published discussion 的 title 与 published post Markdown 派生纯文本；
- `tag`：按一个 active community tag slug 过滤；
- `sort=latest|top|newest`；搜索时额外允许 `relevance`；
- `page`、`size`，沿用统一 Page DTO。

`q` 是纯文本，不支持 Flarum gambit、字段表达式、SQL 片段或任意过滤 DSL；tag 等结构化条件使用独立参数。规范化后允许 1–128 个 Unicode scalar，按 Unicode 空白最多拆为 8 个非空 token，拒绝 NUL/控制字符和全空白输入。查询归一化和索引归一化必须使用同一 `community_trigram_v1` 纯函数；中文、ASCII、大小写和组合字符 fixture 必须锁定结果。

排序语义固定为：

```text
latest:  last_posted_at DESC, id DESC
top:     reply_count DESC, last_posted_at DESC, id DESC
newest:  created_at DESC, id DESC
relevance: search_rank DESC, last_posted_at DESC, id DESC
```

- 无 `q` 时默认 `latest`；有 `q` 且未传 sort 时默认 `relevance`。
- `relevance` 没有 `q` 时返回 `community.invalid_sort`，不退化为 latest。
- `q` 与 `latest/top/newest` 可以组合：先按搜索命中过滤，再按显式 sort 排序。
- `top` 明确等价于 Flarum 风格的回复数排序，不读取 view/like/rating，也不是时间衰减的“热度”；未来 hot/trending 必须新增独立 sort key 和版本化评分投影。
- `total` 与 items 使用相同公开可见性、search 和 tag 条件；每种排序最后都有唯一 ID，禁止不稳定分页。
- search rank 只决定顺序，不进入持久业务事实；允许 DTO 返回安全的命中 post ID/摘要，但不得返回隐藏正文或 parser 内部信息。

## 7. Commands 与 Queries

### 7.1 Commands

- discussion：`CreateDiscussion`、`UpdateDiscussion`、`SubmitDiscussion`、`PublishDiscussion`、`HideDiscussion`、`RestoreDiscussion`、`ArchiveDiscussion`、`LockDiscussion`、`UnlockDiscussion`、`ReplaceDiscussionTags`；
- post：`CreateReply`、`UpdatePost`、`ApprovePost`、`HidePost`、`DeletePost`；
- tag：`CreateTag`、`UpdateTag`、`ArchiveTag`、`ReorderTags`；
- ops：`RebuildCommunitySearch`、有权限且可 dry-run 的 `PurgeArchivedDiscussions`。

创建 discussion/reply 和所有可重试写端点必须支持业务幂等键。Command 只写 community 表与 kernel outbox；作者校验经 Port，不能写 identity。审核、锁定、归档、删除和 search rebuild 必须进入 audit envelope，且不复制完整正文。

### 7.2 Queries

- `ListDiscussions`、`GetDiscussionById`、`GetPublishedDiscussionBySlug`；
- `ListDiscussionPosts`；
- `ListTags`、`GetTagBySlug`；
- `GetCommunityDiagnostics` 与管理员审核列表。

Query 无写副作用。批量作者公开投影经 `CommunityAuthorPort`，Port 超时应返回明确失败或受控缺省作者 DTO，不把 provider/identity 异常伪装成“讨论不存在”。

## 8. HTTP 与 OpenAPI

用户侧 RouterSpec 使用两个稳定 OpenAPI tags：`discussions` 与 `community-tags`。首版路径：

| 方法与路径 | 认证/幂等 | 语义 |
| --- | --- | --- |
| `GET /api/v1/community/discussions` | 匿名；可选 Bearer | search/tag/sort/page 的 published discussion 列表 |
| `POST /api/v1/community/discussions` | 登录 + `Idempotency-Key` | 创建 discussion 与首帖 |
| `GET /api/v1/community/discussions/by-slug/{slug}` | 匿名；可选 Bearer | published discussion 详情 |
| `PATCH /api/v1/community/discussions/{discussion_id}` | 登录 + version | 编辑允许字段，不通用修改状态 |
| `GET /api/v1/community/discussions/{discussion_id}/posts` | 匿名；可选 Bearer | published post stream |
| `POST /api/v1/community/discussions/{discussion_id}/replies` | 登录 + `Idempotency-Key` | 创建 reply，遵守 lock/审核策略 |
| `PATCH /api/v1/community/posts/{post_id}` | 登录 + version | 编辑本人或有权限的 post |
| `GET /api/v1/community/tags` | 匿名 | Tags 分区与 published counts |
| `GET /api/v1/community/tags/by-slug/{slug}` | 匿名 | tag 详情与公开元数据 |

moderation、lock/unlock、archive、tag 管理和 search rebuild 使用 `/api/v1/admin/community/**` 的命名 Command 路由及 `admin-community` tag。用户侧不得通过 `include_hidden=true` 或任意 status filter 提权。

Astro 公开 URL 建议固定为 `/community`、`/community/tags`、`/community/tags/{slug}` 与 `/community/discussions/{slug}`。浏览器/canonical 使用 slug；写操作使用详情 DTO 返回的 opaque UUID。未知 slug、非 published discussion 和无权查看的对象对公开请求统一为 404。

## 9. 权限、错误与事件

首版 access capability keys 至少包括：

- `community.discussions.create`、`community.discussions.reply`、`community.discussions.edit_own`；
- `community.discussions.moderate`、`community.discussions.lock`、`community.discussions.archive`；
- `community.posts.moderate`、`community.tags.manage`；
- `community.read_admin`、`community.search.rebuild`、`community.purge`。

稳定错误 code 至少包括：

- `community.unknown_template`、`community.invalid_transition`、`community.version_conflict`；
- `community.slug_generation_failed`、`community.discussion_locked`；
- `community.tag_required`、`community.tag_limit_exceeded`、`community.tag_archived`、`community.tag_hierarchy_invalid`；
- `community.markdown_invalid`、`community.body_too_large`；
- `community.search_query_invalid`、`community.invalid_sort`、`community.search_profile_unavailable`。

事件至少包括：

- `community.discussion_created.v1`、`community.discussion_updated.v1`、`community.discussion_published.v1`、`community.discussion_hidden.v1`、`community.discussion_archived.v1`、`community.discussion_lock_changed.v1`；
- `community.post_created.v1`、`community.post_published.v1`、`community.post_hidden.v1`、`community.post_deleted.v1`；
- `community.tags_replaced.v1`、`community.tag_created.v1`、`community.tag_updated.v1`、`community.tag_archived.v1`。

事件只包含 ID、版本、状态、必要 tag/计数摘要和 trace 信息，不包含 title/body 全文、派生 HTML、搜索文档或作者敏感信息。GET/HEAD 不产生 view、read、search 或任何写事件。

## 10. 索引、迁移与诊断

migration 至少建立：

- discussion slug 唯一索引；
- published + `last_posted_at/id`、`reply_count/last_posted_at/id`、`created_at/id` 排序索引；
- post `(discussion_id, number)` 唯一索引和公开状态索引；
- tag slug、parent/position 与 assignment 双向索引；
- `community_search_documents.normalized_text` 的 trigram 索引及 source 唯一约束。

diagnostics 只读检查：未知 template/schema/profile、discussion/首帖状态不一致、reply_count/last post 摘要漂移、tag 层级/数量违规、archived tag 新 assignment、search source version 落后、隐藏正文仍可搜索、孤儿作者 reference 和过期 pending 积压。修复通过独立、有权限、有审计的 Command，不由 diagnostics 或 GET 自动执行。

## 11. 不在首版范围

- 多社区/多租户、子论坛/space；
- unread/read position、follow/subscription、实时推送；
- likes/reactions、views、评分、投票、最佳答案、悬赏；
- mentions、通知、积分奖励、附件/图片；
- 举报、spam classifier、敏感词自动审核；
- sticky/pin、hot/trending、个性化推荐；
- Flarum gambit 查询语言或运行时 extension 注入。

这些项目需要新增明确事实、权限、Port、事件、排序或 workflow 合同，不能复用 JSONB/metadata 绕过规格。

## 12. 验收

- community package 单独 import 无注册、router、线程、连接或后台副作用；未进入 manifest 时用户/admin 路由均不存在且 OpenAPI 不包含。
- community 不导入 content/taxonomy/comments/engagement，所有论坛表均为 `community_` owner；identity 只经 opaque reference + Port。
- 创建 discussion 与首帖原子提交；并发 reply number 不重复；幂等重放不产生重复 discussion/post/event。
- discussion/post transition、lock、审核、隐藏/恢复、archive 和乐观并发有正负测试。
- tag primary/secondary、单层 parent、数量上下限、archive 和稳定排序有正负测试；与 taxonomy 无双写。
- `latest/top/newest/relevance` 完全按本规格排序并以 ID 收尾；tag/search/page total 使用同一可见性条件。
- 搜索覆盖 title 与 published post，中文/ASCII fixture 顺序稳定；pending/hidden/deleted 正文在同一事务后不可搜索；rebuild 可从源事实恢复。
- `top` 只使用 reply_count，GET 不计 view、不写 read marker、不刷新搜索投影。
- Markdown/profile/byte/危险输入测试通过，API/事件/数据库无派生 HTML。
- author Port 失败、搜索 profile/extension 缺失、slug 并发冲突和最后 reply 被隐藏等失败路径有可重现测试。
- migration replay、diagnostics、完整/用户 OpenAPI snapshot 与生成客户端无漂移。
