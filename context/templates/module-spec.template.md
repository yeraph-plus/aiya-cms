# Module / <模块名>

> 模板使用说明：所有章节必须保留；无内容的章节写"无"并附一句原因。本文档是代码的前置规格，实现与本文档不一致时先改文档（SDD）。

## 1. 设计目的

<模块解决什么业务问题？覆盖哪些站点形态（下载站/图库/博客/轻社区）？非目标是什么？>

## 2. 范围与依赖

- 代码位置: `inc/modules/<module>/`
- 依赖: 仅允许 `inc.kernel` 公开 API（列出实际用到的组件）
- 被谁依赖: 仅 `api` 层（模块间禁止互相导入）
- 内部结构: `models.py` / `schemas.py` / `repositories.py` / `services.py` / `registry.py`（按需）/ `listeners.py` / `wiring.py` / `api.py`

## 3. 领域模型

<聚合、实体、值对象；与 kernel 要素（User 等）的关系——只持有 id 引用，不 import 其内部。>

## 4. 状态机

<状态枚举 + 合法转换表；无状态写"无"。>

| 当前状态 | 事件/动作 | 下一状态 | 备注 |
|---|---|---|---|

## 5. 数据库

### 表: `<table_name>`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|

索引: <列表>
JSONB 字段对应的 Pydantic Model: `<ModelClass>`（定义位置）

## 6. HTTP API

| 方法 | 路径 | Capability | 请求 DTO | 响应 DTO | 说明 |
|---|---|---|---|---|---|

## 7. Pipeline

- 拥有的 Pipeline key: <列表>
- 注入点（before/after 各开放哪些槽位）: <列表>
- 向其他模块 Pipeline 注入的 step（经 wiring 装配）: <列表，注明目标 key 与槽位 key>

## 8. Event

- 发布: <事件类型清单 + payload 模型>
- 订阅: <监听的事件 + 处理器 + 用途>

## 9. Service 泛型签名

<`Service[TDTO, TData]` 等 TypeVar/Generic 约束说明。>

## 10. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|

## 11. Cron / 任务

<模块级定时任务、BaseTask 子类；无则写"无"。>

## 12. 测试边界

<必须锁定的行为清单：接口契约、流程、边界值、异常路径。每条对应至少一个 pytest。>

## 13. 未决事项

<遗留问题、后期扩展预留。>
