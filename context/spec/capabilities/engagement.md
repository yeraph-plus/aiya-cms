# Engagement Capability 规格

## 1. 职责与边界

engagement 维护 content 的浏览、点赞/收藏和评分事实及聚合快照。它只保存 opaque `content_id`，不建立 content 外键、不修改 `contents`，并通过 `EngageableContentReader` Port 校验目标。

只有 `published` 内容可接受新互动。归档或物理删除只隐藏目标，不级联删除历史互动事实。

## 2. 表所有权

- `engagement_content_stats`：`content_id`、content type/status/published projection、`view_count`、`like_count`、`rating_sum`、`rating_count`、`rating_average`、projection version/time。
- `engagement_content_views`：每次浏览事实；可选 `idempotency_key_digest`，同一 content/key 唯一，无 key 时每次调用均计数。
- `engagement_content_likes`：subject/content 唯一一行，使用 `removed_at` 表示撤销；保留 `liked_at`。
- `engagement_content_ratings`：subject/content 唯一一行，保存当前 1–5 整数评分、撤销时间和更新时间。

事实表是来源，聚合列是同事务维护的快照；计数不得由调用方传入。

## 3. Commands 与 Query

- `RecordContentView`：无业务请求体，服务端只执行 `+1`；可选 `Idempotency-Key` 重放去重。
- `LikeContent` / `UnlikeContent`：幂等激活/撤销/再次激活。
- `RateContent` / `WithdrawRating`：重复同值幂等，改分按差值更新，撤销后减少 sum/count。
- `GetContentEngagement`、`ListFavorites`、`ListEngagedContent`。

评分每次变化都使用 Decimal `ROUND_HALF_UP` 固化一位小数；无评分时平均值为 null。

## 4. 投影、排序与统计

`post` feature 消费带 content version 的 post 事实事件，幂等更新 engagement 投影并支持显式重建。互动排序使用 projection，因此允许短暂最终一致；diagnostics 必须报告 lag、乱序和孤儿投影。engagement capability 已启用但 post 未启用时，不自动订阅 content 事件。

互动 sort allowlist 为 `view_count`、`like_count`、`rating_sum`、`rating_count`、`rating_average`。未传 sort 时沿用 content 置顶默认序。

## 5. HTTP 与权限

engagement capability 不导出按任意 `type_name` 放开的用户 router。完整产品由 `post` feature 导出：

- `POST /api/v1/posts/{post_id}/views`；
- `PUT|DELETE /api/v1/posts/{post_id}/like`；
- `PUT|DELETE /api/v1/posts/{post_id}/rating`；
- `GET /api/v1/me/favorites/posts`。

post 列表/详情可以通过公开 Query 组合 engagement 摘要；GET 本身不记录 view。page 不装配 engagement。管理员只读摘要随 admin content 返回；投影重建是独立、审计的运维 Command。

互动写入不要求管理员 capability；管理员读和重建分别使用 `engagement.read`、`engagement.rebuild`。

## 6. 验收

覆盖唯一约束、并发计数、幂等重放、改分/撤销/恢复、published 门禁、投影重放与重建、排序分页和 GET 无业务副作用。
