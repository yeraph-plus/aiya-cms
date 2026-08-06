# ADR-0006: Pipeline 注册表 + 键值（显式装配、启动校验）

- 状态: accepted
- 日期: 2026-08-02
- 决策者: 项目所有者 + AI 协作
- 关联: [kernel/pipeline.md](../kernel/pipeline.md)、[architecture/01-dependency-rules.md](../architecture/01-dependency-rules.md)

## 背景

接口需要"显式注入点"：其他模块新增的数据/行为能注入到某模块接口流程中（如 interaction 模块往 content 的读取结果里注入"是否已购买/已点赞"）。所有者明确反对 WP 式按字符串名排队的 action/filters，也反对自动发现式插件机制；要求"注册表模式完成 pipeline 登记"。约束：module 禁止 import module，而注入双方天然分属不同模块。

## 决策

1. **kernel 提供 Pipeline 注册表**：`PipelineKey(name: str)` 值对象 + `PipelineDef`（`before: list[Step]` / `core` / `after: list[Step]`）+ `PipelineRegistry`（`register` / `get` / `validate_all`）。
2. **键与槽位约定**：
   - Pipeline key 常量由**属主模块**定义并登记（如 content 模块 `PIPE_CONTENT_READ = PipelineKey("content.read")`）。
   - 扩展槽位 key 与槽位 DTO 由**数据生产方模块**定义（如 interaction 模块 `SLOT_PURCHASE_BADGE` + `PurchaseBadgeDTO`）。
   - 由于模块间禁止 import，跨模块引用键值时按**字符串字面量**对齐，正确性由第 4 点的测试保证；api 层（可自由导入）一律使用常量而非字面量。
3. **装配集中在 api 层 wiring**：模块在自己的 `wiring.py` 暴露 `register(registry)` / `wire(registry)` 函数，api 启动时按显式顺序调用——登记 pipeline、注入 step、订阅事件。无自动发现。
4. **正确性双保险**：
   - 启动时 `validate_all()` fail-fast：所有注入目标 key 必须已登记，所有 step 签名必须合规，否则应用拒绝启动。
   - `tests/architecture/test_wiring_integrity.py`：全量 pipeline key / 槽位 key 的存在性与文档（context 第 7 节）一致性校验。
5. **StepContext**（kernel Pydantic 基类）：`principal`、`payload: BaseModel`、`extensions: dict[str, BaseModel]`（类型化扩展袋，值必须是 Pydantic Model，不是裸 dict）。事务边界：before/core 在 UoW 内，after 在 commit 后（可发事件）。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| Composition-Root 纯显式装配（api 直接 import 双方 pipeline 对象接线） | 无字符串、全类型检查 | 跨模块注入点列表全堆在 api 层，模块无法声明"我开放了哪些注入点"；属主模块对自身 pipeline 的治理弱化 | 所有者选择注册表方案 |
| WP 式字符串 action/filter 全局队列 | 灵活 | 无类型、无登记、隐式排队 | 所有者明确反对 |
| 包扫描自动发现 wiring | 零装配代码 | 隐式、顺序不可控、测试困难 | 所有者明确反对 |

## 后果

### 正面
- 每个模块的注入面（开放的 key 与槽位）在自身文档与注册表中显式可查；装配顺序集中在 api wiring，一眼可见。
- 启动校验 + wiring 测试把字符串键的 typo 风险压到接近类型安全。

### 负面 / 代价
- 跨模块注入的 step 拿到的 `StepContext.payload` 只能是 kernel 基类（拿不到对方模块的具体类型），需要生产方在槽位 DTO 设计中自描述；类型收窄发生在 api 层组装处。
- 注册表是全局状态，测试中需要隔离/重建（kernel 提供 `fresh_registry()` 测试工具）。

### 逃生门
- 后期若字符串键治理失控，可在 kernel 引入类型化 key（`PipelineKey[TContext]` 泛型化）逐步收紧，注册表 API 不变。
