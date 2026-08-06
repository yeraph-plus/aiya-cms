# Modules / 总览（00-modules-overview）

## 1. 模块是什么

模块层承载具体业务类型与可替换扩展：`post`、`forum`、`issue` 的声明，以及后期的积分、通知、支付、搜索等。Content、Taxonomy、Comment 的通用对象表和基 Service 按 ADR-0032 属于 kernel；具体类型通过声明使用内核能力。拥有独立聚合的模块仍独立设计表结构和 Service，但声明型模块可以不建表。

## 2. 模块标准结构

```
inc/modules/<name>/
  __init__.py        # 显式导出公开符号（DTO / Service Protocol / wiring 函数）
  definition.py      # 声明型模块的 ContentType 子类，按需
  models.py          # ORM（只允许本模块与 api 层测试接触）
  schemas.py         # Pydantic DTO + JSONB Model 登记
  repositories.py    # Repository[ModelT] 子类
  services.py        # Service（禁 Session；进出 DTO）
  registry.py        # 模块自有的登记处（如内容类型注册表），按需
  listeners.py       # 事件监听器定义（函数），按需
  wiring.py          # register(registry/bus/scheduler/...)：登记 pipeline、事件、Cron
  api.py             # FastAPI router（薄：参数→Service→DTO）
```

目录按需存在。`post/forum/issue` 首期是声明型模块，只需要 `definition.py`、`wiring.py` 和自身规格；禁止复制 kernel Content/Taxonomy/Comment 的 ORM、Repository 或 Service。

## 3. 接线规则（wiring）

api 启动时按显式顺序调用各模块的 `wiring.register(...)`：

1. `register_definitions(content_types)`——登记自有 ContentType 声明，按需。
2. `register_pipelines(registry)`——登记自有 PipelineDef（含 core step）。
3. `attach_steps(registry)`——向已登记 Pipeline 注入 step（按 key 字符串对齐；生产方定义槽位常量+DTO）。
4. `subscribe_events(bus)`——登记监听器。
5. `register_tasks(scheduler)`——登记 BaseTask 子类与 Cron。

顺序由 api 层 wiring.py 硬编码（无自动发现）。启动末尾 `registry.validate_all()` fail-fast。

## 4. 跨模块协作纪律（复述红线）

- 模块之间**禁止 import**（含类型）。
- 读取协作：api 层注入点聚合（ADR-0007）；step 从 `ctx.payload`/`ctx.principal` 取要素，写 `ctx.extensions[SLOT_X] = XxxDTO(...)`。
- 写入协作：仅 EventBus；监听器内自开 UoW 写自己的表。
- 共享要素：用户只经 `UserRead`/`IdentityService`；权限经 `require_capability`；不直接读 kernel 表。

## 5. 本期模块清单

| 模块 | 规格 | 一句话 |
|---|---|---|
| post | 待由 G0 新建 `post.md` | 声明 post 状态、字段、category/tag 和评论策略 |
| forum | 待由 G0 新建 `forum.md` | 声明 forum 内容类型及自身扩展业务 |
| issue | 待由 G0 新建 `issue.md` | 声明 issue 内容类型及自身扩展业务 |
| interaction | [interaction.md](interaction.md) | 点赞/评分等用户事实，经事件维护内核计数 |

旧 [content.md](content.md)、[taxonomy.md](taxonomy.md)、[comment.md](comment.md) 仅记录 M2 当前实现，是 M2.1 迁移输入；不得继续扩展，迁移完成后由 kernel 规格取代。

## 6. 后期模块预留（路线，非本期）

interaction（点赞/收藏/关注/举报）、notification、message、points/签到、order/payment/refund、download 鉴权、webhook、search（Meilisearch 适配）。预留机制均已就位：pipeline 槽位、事件、Capability 登记、BaseTask、LISTEN/NOTIFY 唤醒（支付）。每个新模块启动 = 先写本目录下规格文档 → pytest → 实现（SDD）。
