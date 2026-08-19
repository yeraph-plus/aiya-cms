# 用户站内容类型 Feature 规格

> 状态：下一用户站目标，尚未实施。本文件定义 `post`、`page`、`work` 三种产品内容类型。三者复用 content capability 的基础事实，但由各自 feature 注册类型、taxonomy、comments、engagement、archive 与用户路由组合。

## 1. 统一原则

- content 只拥有内容基础列、JSONB data、状态机、发布与引用；不认识三种产品语义。
- taxonomy、comments、engagement、archive 保持独立 capability；feature 只使用公开面。
- 三种类型使用独立稳定 type key 和 Pydantic data schema，不用 nullable 万能字段模拟差异。
- GET 不写 view；计数必须通过显式 Command 端点。
- 公共 canonical 定位使用不可变 slug；内部写入使用 opaque UUID。

## 2. 普通文章 `post`

`post.v2` 注册：

- Markdown `gfm-v1`、excerpt、SEO data；
- taxonomy `post.category`：single，发布时恰好 1；
- taxonomy `post.tag`：multiple，0–8；
- comments target policy `post`；
- engagement：view、like/favorite、rating 和聚合计数；
- 列表支持发布时间与 engagement allowlist 排序；
- 不支持 archive 下载文件。

用户路由：`GET /api/v1/posts`、`GET /api/v1/posts/by-slug/{slug}`、评论端点、显式 view/like/rating 和 `/api/v1/me/favorites/posts`。

## 3. 文档/页面文章 `page`

`page.v2` 注册：

- Markdown `gfm-v1`、excerpt、SEO data；
- taxonomy `page.category`：single，发布时恰好 1；
- 不注册 tag、comments、engagement、archive、favorite、rating 或计数器；
- 不支持父子页面、目录树或自动文档导航；如未来需要层级，先定义独立合同。

用户路由仅为 `GET /api/v1/pages` 与 `GET /api/v1/pages/by-slug/{slug}`。未装配的评论/互动路由必须 404，而不是返回空实现。

## 4. 作品文章 `work`

`work.v1` 注册 Markdown、excerpt、SEO、作品元数据、命名空间 taxonomy、comments、engagement 和 archive manifest。

### 4.1 命名空间 taxonomy

借鉴 E-Hentai 使用 namespace 区分同名 tag 语义的做法，但不复制其投票、mod power、weak/solid、成人标签规则或运行时。首版显式注册：

| Dimension key | 语义 | selection |
| --- | --- | --- |
| `work.category` | 作品主分类 | single，发布时恰好 1 |
| `work.source` | 原作、系列或改编来源 | multiple，0–8 |
| `work.creator` | 作者、画师、制作人 | multiple，1–16 |
| `work.group` | 社团、工作室、制作组 | multiple，0–8 |
| `work.character` | 角色 | multiple，0–32 |
| `work.language` | 语言 | multiple，1–4 |
| `work.genre` | 主题/类型标签 | multiple，0–32 |
| `work.format` | 漫画、插画集、游戏素材等格式 | multiple，0–4 |

同一 slug 可在不同 dimension 中存在；查询必须显式带 dimension key。各维度内 OR、维度间 AND。term 由管理员受控创建/归档，普通用户不能通过内容提交临时创建 term。

### 4.2 `WorkDataV1`

JSONB 至少包含：

- `alternate_titles`、可选发布日期与安全展示元数据；
- `cover_asset_id` opaque ref；
- `archive_manifest_version`；
- `download_files[]`：`archive_item_id`、公开 `display_name`、`part_number`、`size_bytes`、可选 checksum 摘要。

文件列表必须按 `part_number, archive_item_id` 稳定排序。它是 published catalog/报价快照，不包含 provider key、OpenList path、Gofile content ID、token、raw/direct URL 或 secret header。archive capability 仍是交付事实和 external locator 的 owner。

发布策略批量验证所有 archive item 为 active、可交付，且 JSONB 的 name/size/checksum 与 archive 公开 DTO 一致。已发布 manifest 变化必须增加 `archive_manifest_version`，使旧 quote 失效。

### 4.3 互动与下载

- comments target policy 固定为 `work`，端点位于 `/api/v1/works/{work_id}/comments`。
- engagement 支持显式 view、like/favorite、rating 与聚合摘要；favorites 使用 `/api/v1/me/favorites/works`。
- 下载报价和消费由 business_center 提供；work detail 只展示文件清单与 quote 入口，不自行扣积分或生成 provider URL。

用户路由：`GET /api/v1/works`、`GET /api/v1/works/by-slug/{slug}`、comments/engagement，以及 business_center 的 quote/consume 路由。

## 5. SEO 与渲染

- post/page/work 均由 Astro SSR 输出 canonical、title、description、Open Graph 和结构化数据；正文保存 Markdown，不保存派生 HTML。
- work 的下载清单可以被 SSR 展示，但所有下载 link、grant token、余额和购买状态必须为 authenticated/private response，禁止进入静态缓存或搜索索引。
- page 无互动区；post/work 的评论和互动作为正文后的独立区块，不影响正文 canonical。

## 6. 验收

- 三种 type 的 registry、data schema、dimension 和 RouterSpec 在启动时显式校验。
- post 恰有 category+tag+comments+engagement；page 只有 category；work 有 namespaced dimensions+comments+engagement+archive manifest。
- page 的 comments/engagement/download 路由为 404。
- work JSONB 不含 provider locator、credential 或 URL；发布时 archive refs 与 manifest version 闭合。
- E-Hentai 只作为 namespace 语义参考；本系统不复制其 tag 投票或权限模型。

## 7. 外部语义参考

- EHWiki Namespace：`https://ehwiki.org/wiki/Namespace`。实现前只复核 namespace 分类含义；本系统的 dimension key、权限、term 生命周期和内容规则仍以本规格为准。
