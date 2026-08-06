# Module / issue

> 状态：G6 声明已实现并由 API wiring 显式注册（2026-08-06）。issue 是声明型模块，不复制 Content/Taxonomy/Comment 表和 Service。

## 1. 设计目的

提供问题/工单式帖子区 `issue`。issue 与 post/forum 共用 kernel Content 基实现，后续可通过声明增加专属状态、字段和 taxonomy 分组。

非目标：不实现独立 issue 表、工作流系统、通知、全文搜索或跨模块同步调用。

## 2. 范围与依赖

- 代码位置: `inc/modules/issue/`
- 依赖: `inc.kernel.content` 的 ContentType/ContentField/TaxonomyGroupDef/CommentPolicy/Status 定义
- 被谁依赖: 仅 api wiring 显式注册；不得被 post/forum 导入
- 内部结构: `definition.py`、`wiring.py`、`__init__.py`；不创建 models/repositories/services

## 3. 领域模型

- `IssueContentType.type_name = "issue"`。
- 固定列使用 kernel Content；G0 data fields 显式为空 tuple。
- G0 taxonomy groups 显式为空 tuple；project/label 等复杂分组必须先在本规格冻结。
- 评论策略：允许评论，最大深度 3，默认待审核，默认限频 10 条/10 分钟。

## 4. 状态机

| 当前状态 | 事件/动作 | 下一状态 | 备注 |
|---|---|---|---|
| draft | publish | published | `content:publish` |
| pending | publish | published | `content:publish` |
| published | unpublish | draft | `content:publish` |
| draft/pending/published | trash | trash | 父类通用动作 |
| trash | restore | draft | 父类恢复到 default_status |

`default_status = "draft"`；公开状态只有 `published`。Issue-specific open/closed workflow 不在 G0 固定。

## 5. 数据库

无。issue 使用 kernel `contents`、`terms`、`term_relationships`、`comments` 表，不创建模块表。

## 6. HTTP API

无独立路由。所有 HTTP 路由由 api 组合根提供，固定使用 `/api/v1/contents/issue/...` 和 `/api/v1/terms/issue/...`；具体契约见 [kernel/content.md](../kernel/content.md) 与 [kernel/taxonomy.md](../kernel/taxonomy.md)。

## 7. Pipeline

- 拥有的 Pipeline key: 无；通过 wiring 登记 ContentType。
- 注入点: 无。
- 向其他模块 Pipeline 注入的 step: 无。

## 8. Event

- 发布: 无自有领域事件；kernel Content 发布 content.*。
- 订阅: 无；后续工作流经 EventBus/独立模块登记。

## 9. Service 泛型签名

无模块 Service。`IssueContentType` 是 `ContentType` 子类；data 类型为 kernel `ContentDataValues`，G0 不声明自定义字段。

## 10. 错误码

无。使用 kernel `CONTENT_*`、`TERM_*`、`COMMENT_*` 错误码。

## 11. Cron / 任务

无。使用 kernel content/comment Cron。

## 12. 测试边界

- `type_name=issue`、default_status、statuses、transitions 和空 taxonomy/data 声明注册成功。
- issue 与 post/forum 的相同 slug、id、term 和 comment 查询不互相命中。
- 未登记 group 在 issue 创建 term 时返回 TERM_002；不会自动接受任意 group。
- `/content-types` 返回 issue 的完整元数据，不暴露未声明的字段或动作。

## 13. 未决事项

- issue 是否增加 open/closed 状态、project/label group 和专属 data fields，必须在 G6 前补齐并先改规格、再写红测。
