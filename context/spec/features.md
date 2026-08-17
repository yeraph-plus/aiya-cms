# 垂直 Feature 规格

feature 是跨 capability 多步业务流的唯一编排层，只调用公开 Command、Query、Activity、Port 和 DTO，绝不读取 capability 的 ORM、Repository 或表。普通单 capability 的管理员 CRUD 不应为形式而再包 feature。

## release features

- `auth`：编排注册、邮箱验证、密码找回与重置；identity/access 完成原子事实，提交后经 notification 的 trigger API 请求 `identity.email_verification` 或 `identity.password_reset`。发送失败不回滚身份事实。
- `site_settings`、`site_cleanup`：声明 settings groups 和站点运维任务。
- `post`、`page`、`content_engagement`：公开内容的发布与浏览组合；不引入用户中心或购买流程。
- `content_bucket`：管理员私有图片上传、finalize、处理状态轮询、删除。它只经 assets 的公开表面和 settings 读取图床参数，assets 拥有 S3/Pillow/清理。

release 不装配 `user_center`、签到、积分购买、会员购买或支付 callback feature。feature 未装配时不得产生 router、worker、workflow 或外部副作用。

## 工作流规则

跨事务步骤使用稳定 key 的 activity/workflow 与 Pydantic 输入/状态。每步有幂等键、明确超时/重试；外部调用和等待不放在数据库事务中。不可逆事实完成后不得伪造回滚。需要独立、可复用业务模型/表时提升为 capability。

## 验收

- 架构测试证明 feature 只使用 capability 公共 surface。
- 注册/找回和图床等多步流程有集成测试；管理员 CRUD 直接使用所属 capability public API。
- 未装配 feature 没有路由、任务、订阅或 provider 调用。
