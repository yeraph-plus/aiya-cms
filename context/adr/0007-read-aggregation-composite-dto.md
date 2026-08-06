# ADR-0007: 读聚合形态——api 层复合响应 DTO

- 状态: accepted
- 日期: 2026-08-02
- 决策者: 项目所有者 + AI 协作
- 关联: [architecture/00-overview.md](../architecture/00-overview.md) 第 5.2 节、[architecture/02-data-boundaries.md](../architecture/02-data-boundaries.md)

## 背景

实际业务中模块必定关联：内容详情页往往同时要展示"是否已点赞/已收藏/已购买"（interaction/commerce）、"评论数"（comment）等。api 作为最外层数据出口不应被限制为"只能调用一个模块的 Service"。需要确定读聚合的类型形态。

## 决策

1. **api 层定义复合响应 DTO**：api 可自由 import 各模块的 DTO，把主 DTO 与扩展槽 DTO 组合成强类型响应，例如：
   `ContentDetailResponse = ContentRead（主）+ viewer: ViewerContextDTO | None + stats: ContentStatsDTO | None`。
2. **填充走读 Pipeline 注入点**（ADR-0006）：主 QueryService 产出主 DTO 后，读 Pipeline 的 after steps 依次执行，把各自模块的数据写入 `StepContext.extensions[slot_key]`；api handler 最后按槽位常量取出并组装复合响应。
3. 全程只读：注入 step 只允许调用本模块 QueryService / Cache，禁止任何写与事件发布（同步只读规则，[00-overview](../architecture/00-overview.md) 第 5 节）。
4. 槽位缺失语义：某模块未装配（如 interaction 未启用）→ 槽位为 `None`，前端按可空字段处理。聚合永远不因单一扩展缺失而失败。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| 内核 Envelope + 类型化槽位 | 约束统一，api 只透传 | 多一层间接；响应结构对所有端点一刀切；前端拿到的类型信息变弱 | 复合 DTO 更直接、OpenAPI 文档更精确 |
| endpoint 手工拼装（无注入点） | 最简单 | 注入点设计在读侧消失；新增扩展要改每个 endpoint | 所有者要求保留注入点机制 |
| GraphQL 式字段解析 | 前端按需取 | 引入整套 GraphQL 栈，过度设计 | 超出本期范围 |

## 后果

### 正面
- 每个端点的响应 Schema 精确、可进 OpenAPI 文档，前端类型可生成。
- 扩展能力以"装配"方式增减：加一个新扩展 = 生产方模块加 step + api 复合 DTO 加可空字段，主模块零改动。

### 负面 / 代价
- api 层随业务增长出现较多复合 DTO 定义（接受，这本身就是 api 层的职责）。
- N+1 风险：列表聚合时 step 必须批量取数（约束写入 pipeline 规格：step 接收的是列表 payload 时必须批量查询）。

### 逃生门
- 某端点聚合逻辑失控时，允许在 api 层为该端点手写编排（注入点不用是权利不是义务），无需架构变更。
