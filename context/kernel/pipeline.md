# Kernel / pipeline（注册表 + 执行器）

## 1. 设计目的

显式注入点机制（ADR-0006）：替代 WP 式字符串 action/filter 与自动发现插件；为"其他模块注入数据/行为到本模块接口流程"提供登记、装配、校验、执行的一体化设施；**一个 Pipeline 运行 = 一个事务**（写路径）。

非目标：不做运行期动态装卸；不做优先级数字排序（顺序 = 装配顺序，显式可控）。

## 2. 范围与依赖

- 代码位置: `inc/kernel/pipeline/`
- 依赖的 kernel 组件: db（UoW）, events, errors, logging
- 被谁依赖: api wiring, 全部 modules
- 外部依赖: 无新增

## 3. 领域模型

- `PipelineKey(str)`：值对象，如 `PipelineKey("content.read")`。属主模块定义常量；跨模块引用按字符串对齐，api 层用常量。
- `Step`：`async def step(ctx: StepContext) -> None`。
- `StepContext(BaseModel)`：
  - `principal: Principal`
  - `payload: BaseModel`——读路径为主查询结果（`ContentRead`/`Page[...]`），写路径为 Command DTO / 结果 DTO。跨模块 step 只依赖 kernel 基类与槽位约定。
  - `extensions: dict[str, BaseModel]`——类型化扩展袋；槽位 key 由数据生产方模块定义常量，值必须是其登记的 DTO。
  - `request: RequestMeta`（ip/user_agent/request_id，审计用）。
- `PipelineDef`：`key`、`owner: str`（属主模块名）、`kind: read | write`、`before: list[Step]`、`core: Step`、`after: list[Step]`。
- `PipelineRegistry`：`register(def)`（重复 key → PIPELINE_002）、`get(key)`（未登记 → PIPELINE_001）、`attach(key, step, *, phase: before|after)`（注入）、`validate_all()`（启动 fail-fast：注入目标存在、step 签名合规、kind 合规——read 管道禁止注入写 step 的声明式检查靠 wiring 测试）。
- `PipelineExecutor`：
  - 写管道：`async with uow:` → before → core → `uow.commit()` → after（提交后，可 publish 事件）。
  - 读管道：不开写事务；before → core → after；全程只读约束（step 违例写库属架构缺陷，由同步只读规则约束）。
  - step 异常：before/core 异常 → 回滚并抛出；after 异常 → 记 error 日志不抛（主事务已提交），缺失槽位为 None。

## 4. 状态机

无。

## 5. 数据库

无。

## 6. 公开 API

```python
class PipelineKey(str): ...
class StepContext(BaseModel): ...
class PipelineDef: ...
class PipelineRegistry: ...
class PipelineExecutor:
    async def run(self, key: PipelineKey, ctx: StepContext) -> StepContext
def fresh_registry() -> PipelineRegistry  # 测试工具
```

### HTTP API

无。

## 7. Pipeline

本组件即 Pipeline 基础设施。全量 key 清单：Content/Taxonomy/Comment kernel key 见各自 kernel 文档第 7 节；post/forum/issue 为声明型模块，不拥有 Pipeline key。

## 8. Event

无（执行器提交后**调用方**发事件；执行器本身不发）。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| PIPELINE_001 | 500 | 注入/执行了未登记的 key | registry.get / validate_all |
| PIPELINE_002 | 500 | 重复登记同一 key | register |
| PIPELINE_003 | 500 | core step 执行失败 | 业务异常包装（具体业务码优先） |

## 10. Cron / 任务

无。

## 11. 测试边界

- 写管道：core 抛错 → before 的写入全部回滚；after 不执行。
- 写管道：after 抛错 → 主数据已提交（查询可见），错误日志记录，响应不失败。
- 读管道：after step 填充 extensions，api 可按槽位常量取出并类型收窄。
- 装配顺序 = 执行顺序（before/after 各自按 attach 顺序）。
- validate_all：注入不存在的 key → 启动失败；重复 register → PIPELINE_002。
- 未登记的槽位 key 写入 extensions → wiring 完整性测试失败（文档一致性）。

## 12. 未决事项

- 类型化 key（`PipelineKey[TContext]` 泛型收紧）：ADR-0006 逃生门。
- 列表聚合防 N+1 约定：step 接收列表 payload 时必须批量查询（规范已写入 ADR-0007，执行靠评审 + 测试）。

## 13. M1.9 实现状态

M1.9 已实现（2026-08-04）：`PipelineKey`、`PipelineDef`、`StepContext`、
`ExtensionBag`、`PipelineRegistry` 与 `PipelineExecutor` 已落库，错误码
`PIPELINE_001/002/003` 已登记。执行器支持读管道与写管道的明确事务边界，按
before/core/after 顺序执行；写管道提交后才运行 after，after 失败只记录结构化
错误日志。启动校验覆盖重复/未登记 key、异步 step 签名、read 管道写 step 与
类型化扩展值。模块 pipeline key 的实际登记仍由后续模块 wiring 完成。
