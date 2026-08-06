# Module / post

> 状态：G6 声明已实现并由 API wiring 显式注册（2026-08-06）。post 是声明型模块，不复制 Content/Taxonomy/Comment 表和 Service。

## 1. 设计目的

提供博客、下载站和图库共用的基础帖子类型 `post`。类型通过 kernel ContentType 获得统一 CRUD、查询、taxonomy 和评论能力；本模块只声明业务元数据。

非目标：不拥有独立表；不实现自有 CRUD Service；不实现全文搜索、版本历史或 interaction 事实表。

## 2. 范围与依赖

- 代码位置: `inc/modules/post/`
- 依赖: `inc.kernel.content` 的 ContentType/ContentField/TaxonomyGroupDef/CommentPolicy/Status 定义
- 被谁依赖: 仅 api wiring 显式注册；其他 modules 不得直接导入
- 内部结构: `definition.py`、`wiring.py`、`__init__.py`；不创建 models/repositories/services

## 3. 领域模型

- `PostContentType.type_name = "post"`。
- 固定列使用 kernel Content：title、slug、content、excerpt、status、计数和 data。
- G0 data 字段显式为空 tuple；增加业务字段必须先改本规格和测试，不使用隐式万能键。
- taxonomy 显式声明 `category`、`tag` 两个扁平 group。
- 评论策略：允许评论，最大深度 3，自动审核，默认限频 10 条/10 分钟。

## 4. 状态机

| 当前状态 | 事件/动作 | 下一状态 | 备注 |
|---|---|---|---|
| draft | publish | published | `content:publish` |
| pending | publish | published | `content:publish` |
| published | unpublish | draft | `content:publish` |
| draft/pending/published | trash | trash | 父类通用动作 |
| trash | restore | draft | 父类恢复到 default_status |

`default_status = "draft"`；公开状态只有 `published`。

## 5. 数据库

无。post 使用 kernel `contents`、`terms`、`term_relationships`、`comments` 表，不创建模块表。

## 6. HTTP API

无独立路由。所有 HTTP 路由由 api 组合根提供，固定使用 `/api/v1/contents/post/...` 和 `/api/v1/terms/post/...`；具体契约见 [kernel/content.md](../kernel/content.md) 与 [kernel/taxonomy.md](../kernel/taxonomy.md)。

## 7. Pipeline

- 拥有的 Pipeline key: 无；通过 wiring 登记 ContentType。
- 注入点: 无。
- 向其他模块 Pipeline 注入的 step: 无。taxonomy/comment 的通用扩展由 kernel wiring 装配。

## 8. Event

- 发布: 无自有领域事件；kernel Content 发布 content.*。
- 订阅: 无；interaction、taxonomy、comment 通过 kernel/API wiring 协作。

## 9. Service 泛型签名

无模块 Service。`PostContentType` 是 `ContentType` 子类；data 类型为 kernel `ContentDataValues`，G0 不声明自定义字段。

## 10. 错误码

无。使用 kernel `CONTENT_*`、`TERM_*`、`COMMENT_*` 错误码。

## 11. Cron / 任务

无。使用 kernel `content.purge_trash`、`content.recount_comments` 和 `comment.purge_orphans`。

## 12. 测试边界

- `type_name`、default_status、statuses、transitions、公开状态和 taxonomy group 注册成功。
- 重复注册 post、未知 group、非法 action 在启动校验失败。
- post 与 forum/issue 使用相同 slug 时互不冲突，所有查询包含 type=post。
- post 的 content CRUD、taxonomy assign、评论目标校验均通过 kernel 契约。
- `/content-types` 返回 post 的完整状态、动作、category/tag 和空 data fields 元数据。

## 13. 未决事项

- post 专属 data 字段（例如封面、来源 URL）需在业务确定后追加声明；不在 G0 猜测字段。
