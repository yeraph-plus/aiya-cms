# CMS 对象规格

## 1. Content

固定列为 id/type/title/slug/status/owner_id/content/view_count/like_count/rating_sum/rating_count/data/published_at/created_at/updated_at/excerpt/comment_count/trashed_at。

内容类型声明必须提供 type_name、statuses、default_status、transitions、fields、taxonomy_groups、comment_policy；解释器负责字段校验和字符串规范化。

状态动作由 transition 声明；trash/restore 是通用动作，purge 由 Cron 按 `trashed_at` 清理。

## 2. Taxonomy

- Term 与 Relationship 是 kernel 通用对象，URL 必须携带 `type_name`。
- 同 group 条件为 OR，跨 group 为 AND；未知 type/group fail-fast 或返回稳定错误码。
- post 声明 `category`、`tag`；不接受未登记 group 或 `tags` 别名。

## 3. Comment

- 采用 `target_type + target_id` 多态目标；kernel 只依赖组合根注入的 TargetExists。
- parent/root/depth 组成评论树；查询保持 roots + descendants 两阶段读取。
- 审核、垃圾、占位删除、防刷、最大深度和 orphan 清理均由 kernel 实现。
- approved 且非占位评论计入 comment_count，所有变化通过事件和 recount 覆盖。

## 4. 内容类型

- post/forum/issue 是仓内声明模块，只提供 ContentType 与 wiring，不复制 kernel ORM/Service。
- API wiring 固定按 post → forum → issue 登记并冻结。
- `/api/v1/content-types` 是管理员动态表单、动作和 taxonomy 控件的唯一元数据来源。
