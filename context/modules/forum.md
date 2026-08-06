# Module / forum

> 状态：G6 声明已实现并由 API wiring 显式注册（2026-08-06）。forum 是声明型模块，不复制 Content/Taxonomy/Comment 表和 Service。

## 1. 设计目的

提供轻社区论坛帖子区 `forum`。forum 与 post/issue 共用 kernel 对象实现，但通过 URL `type_name=forum`、注册字段和独立 taxonomy 声明实现数据外观隔离。

非目标：不实现独立论坛表、板块树、消息通知、全文搜索或模块间同步调用。

## 2. 范围与依赖

- 代码位置: `inc/modules/forum/`
- 依赖: `inc.kernel.content` 的 ContentType/ContentField/TaxonomyGroupDef/CommentPolicy/Status 定义
- 被谁依赖: 仅 api wiring 显式注册；不得被 post/issue 导入
- 内部结构: `definition.py`、`wiring.py`、`__init__.py`；不创建 models/repositories/services

## 3. 领域模型

- `ForumContentType.type_name = "forum"`。
- 固定列使用 kernel Content；G0 data fields 显式为空 tuple。
- G0 taxonomy groups 显式为空 tuple，表示尚未启用论坛分组；增加 board/tag 等 group 必须先改本规格。
- 评论策略：允许评论，最大深度 5，自动审核，默认限频 10 条/10 分钟。

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

无。forum 使用 kernel `contents`、`terms`、`term_relationships`、`comments` 表，不创建模块表。

## 6. HTTP API

无独立路由。所有 HTTP 路由由 api 组合根提供，固定使用 `/api/v1/contents/forum/...` 和 `/api/v1/terms/forum/...`；具体契约见 [kernel/content.md](../kernel/content.md) 与 [kernel/taxonomy.md](../kernel/taxonomy.md)。

## 7. Pipeline

- 拥有的 Pipeline key: 无；通过 wiring 登记 ContentType。
- 注入点: 无。
- 向其他模块 Pipeline 注入的 step: 无。

## 8. Event

- 发布: 无自有领域事件；kernel Content 发布 content.*。
- 订阅: 无；后续通知等能力经 EventBus 登记。

## 9. Service 泛型签名

无模块 Service。`ForumContentType` 是 `ContentType` 子类；data 类型为 kernel `ContentDataValues`，G0 不声明自定义字段。

## 10. 错误码

无。使用 kernel `CONTENT_*`、`TERM_*`、`COMMENT_*` 错误码。

## 11. Cron / 任务

无。使用 kernel content/comment Cron。

## 12. 测试边界

- `type_name=forum`、default_status、statuses、transitions 和空 taxonomy/data 声明注册成功。
- forum 与 post/issue 的相同 slug、id、term 和 comment 查询不互相命中。
- 未登记 group 在 forum 创建 term 时返回 TERM_002，而不是隐式创建。
- `/content-types` 返回 forum 的完整元数据和空 group/field 列表。

## 13. 未决事项

- forum 是否启用 board/tag 等 taxonomy group，以及专属 data fields，必须在 G6 前补齐并写入本文件；不得由代码隐式推断。
