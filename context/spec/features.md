# 垂直 Feature 规格

feature 是跨 capability 多步骤业务流的唯一编排层，只调用公开 Command、Query、Activity、Port 和 DTO，绝不读取 capability 的 ORM、Repository 或表。普通单 capability 管理 CRUD 仍由 `/api/v1/admin/**` 直接适配 capability，不为形式统一套 feature。

## 目标 Feature 集合

下一用户站 release 的稳定 feature key 为：

- `auth`：注册、邮箱验证、密码找回/重置；
- [`user_center`](features/user-center.md)：资料、签到、积分/会员购买、卡密兑换、会员周期限时积分；
- [`business_center`](features/business-center.md)：可信报价、统一积分扣费和业务交付；
- [`post`、`page`、`work`](features/content-types.md)：三种内容产品组合；
- `site_settings`、`site_cleanup`：站点 settings 与运维任务；
- `content_bucket`：管理员图片上传和规范化。

community 是独立 capability 及其 RouterSpec，不伪装为 content feature。archive 是独立 capability；OpenList/Gofile 是其 Port adapter。

## 组合收敛

目标 manifest 不再注册 `check_in`、`membership_grants`、`point_purchase`、`membership_purchase` 或 `content_engagement` 独立 feature。其行为分别收敛为：

| 旧组件 | 目标 owner |
| --- | --- |
| `check_in`、旧 `MeService` | `user_center` |
| `point_purchase`、`membership_purchase` | `user_center` |
| membership 直接授予 points | `user_center` 持久 workflow |
| gift card 兑换 points/membership | `user_center` |
| `content_engagement` | `post` 和 `work` 的 feature 组合 |
| 下载付费逻辑 | `business_center` + archive |

points、membership、gift_cards、payments、engagement 等 capability 保留自身规则、表和原子操作；收敛 feature 不意味着合并 capability 或建立跨能力 ORM 关系。

## 内部货币与法币边界

- 系统业务消费一律使用 points 的固定 `credit` program；下载、未来 AI 等业务不得直接接受 CNY 或 provider payment token。
- CNY order、attempt、webhook、refund，以及未来可能出现的法币余额，只能归 payments capability。
- user_center 从受信商品声明创建 payments order；payments 返回受信 captured/refunded 事实，user_center 再完成 points/membership fulfillment。
- business_center 不导入 payments，只扣 points。

## 工作流规则

跨事务步骤使用稳定 workflow/activity key、Pydantic 输入/状态、幂等键、超时、重试和明确补偿。外部调用不放在长期数据库事务中。已提交的 payment、points、membership、gift-card 或 archive 事实不能通过删除 workflow 假装回滚。

需要独立、可复用业务表和状态机时提升为 capability；feature 只拥有声明、编排 gateway 和必要的持久 workflow state，不建立万能业务订单表。

## 实施状态

本规格先于实现生效。当前代码中的 `check_in`、旧 `/me` 组合和未装配购买链属于待替换实现；完整迁移顺序与删除清单见 [`../user site spec/IMPLEMENTATION.md`](<../user site spec/IMPLEMENTATION.md>)。在完成失败测试、迁移、OpenAPI 和端到端验证前，不得宣称目标用户站已交付。

## 验收

- 架构测试证明 feature 只使用 capability public surface。
- 目标 manifest 只注册本文件列出的 feature key，旧 key/router/workflow 无兼容别名。
- 未装配 feature 没有路由、任务、订阅、provider 调用或后台副作用。
- user_center 和 business_center 的幂等、补偿、provider failure 与并发路径有集成测试。
