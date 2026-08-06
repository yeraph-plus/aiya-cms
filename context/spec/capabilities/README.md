# Capabilities 规格索引

capability 是拥有业务模型、表、命令、查询、事件、诊断和迁移的边界。它可以被不同 feature 复用，但不会因 import 自动运行。

## 初始能力

- [`identity.md`](identity.md)：用户主体、登录标识和凭据生命周期。
- [`access.md`](access.md)：权限 key、角色、主体授权与审计边界。
- [`oidc-provider.md`](oidc-provider.md)：作为 OpenID Provider 对外提供单点登录。
- [`audit.md`](audit.md)：跨能力安全审计事实的不可变持久化和查询。
- [`content.md`](content.md)：通用内容、类型声明、状态、定时发布、置顶和引用。
- [`taxonomy.md`](taxonomy.md)：平面多维标签。
- [`settings.md`](settings.md)：声明式配置组和 SEO 默认值。
- [`assets.md`](assets.md)：外部对象存储/图床的稳定资源引用。
- [`notification.md`](notification.md)：通知意图、模板、渠道和可靠投递。
- [`points.md`](points.md)：积分计划、账户、不可变账本和行为规格。
- [`payments.md`](payments.md)：外部支付订单、webhook 和退款事实。

comments 不属于首个重建闭环；未来若加入，必须成为独立 capability，不回到 kernel/content 内核。

## 统一包合同

一个 capability 按需要包含：

```text
inc/capabilities/<name>/
  definition.py       # 纯数据 CapabilitySpec
  models.py           # 自有表
  schemas.py          # DTO/JSONB schema
  commands.py         # 业务写入口
  queries.py          # 无副作用读入口
  ports.py            # 本能力消费的接口
  events.py           # 版本化业务事实
  activities.py       # 幂等 workflow 步骤
  diagnostics.py      # 只读一致性检查
  metrics.py
  readmodels.py
  api.py              # 可选 RouterSpec
  migrations/
  tests/
```

文件可以在简单能力中合并，但职责和公开/内部边界不得消失。

## 统一行为规则

- capability 只能导入 kernel 和自身，不能导入兄弟 capability。
- 跨能力关系保存 opaque ID，不建兄弟表外键；有效性通过消费方 Port 校验。
- Command 只能写自身表和 kernel outbox；Query 无写副作用。
- 公开边界使用 Pydantic DTO，不暴露 ORM/Repository/UoW。
- 外部 SDK 位于 adapter/activity，错误归一化后才进入业务层。
- events 是已提交事实；需要立即答复时调用 Command/Port。
- `diagnostics.py` 只读，修复另设有权限且审计的 Command。
- 每项注册使用 owner 明确的稳定 key，组合根 validate/freeze 后才启动运行时。
- 每个 capability 维护自己的后续 revision；不能修改兄弟表。

## 能力启用和迁移

所有随发行版交付的 capability 表统一进入 migration manifest。运行时只有 manifest 启用的能力才注册 router、订阅、Cron、worker 和 provider 连接。

因此“未启用不工作”不等于“未启用不建表”。首版不支持运行中安装/卸载 capability 或按租户切换代码能力。

## 统一验收

- 单独导入无副作用。
- 最小 manifest 可独立装配并 fail-fast 校验必需 Port。
- 表 owner、事件、权限、错误码和公开 DTO 有合同测试。
- 并发、幂等、事务 rollback 和 provider failure 有负向测试。
- API/feature 无法访问 capability 内部 ORM/Repository。
