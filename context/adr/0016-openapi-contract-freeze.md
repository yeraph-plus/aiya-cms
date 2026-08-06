# ADR-0016: OpenAPI 契约冻结与生成

- 状态: accepted
- 日期: 2026-08-04
- 决策者: 项目所有者 + AI 协作
- 关联: [m1-a1-plan.md](../m1-a1-plan.md)（执行原则 5、G0/G3、M1.12、A1.2）、[admin/01-a0-a1-plan.md](../admin/01-a0-a1-plan.md) §3.2、[kernel/errors.md](../kernel/errors.md)、[ADR-0013](0013-browser-token-storage-cors-csrf.md)、[ADR-0014](0014-request-id-propagation.md)、[ADR-0015](0015-health-check-contract.md)

## 背景

双轨执行原则 5 约定"契约单一事实来源"：后端 FastAPI OpenAPI 冻结后生成管理员端类型/客户端，生成物禁止手工编辑。G0 已登记生成器（openapi-typescript + 原生 fetch，目录 `admin/src/common/api/generated/`），但"冻结"的操作语义尚未锁定：冻结产物放哪、如何产生、如何检测漂移、契约如何版本化演进。不冻结则 A1.2 无法安全开工（依赖 `M1L -. "冻结 OpenAPI" .-> A1B`），且两端各自手写 DTO 会回归 G3 "不得手写 DTO" 明令禁止的路线。

约束：Python 3.14 / FastAPI 0.141；前端 Vue3 + TypeScript 6；前端构建必须不依赖后端在线（CI 隔离）；契约必须可评审（PR diff）。

## 决策

1. **单一事实来源 = 运行中的 FastAPI app factory 生成的 OpenAPI schema**。app factory 显式注册全部 router；OpenAPI 元数据（`title`/`version`/`description`）固定为代码常量，不读环境变量。固定 `generate_unique_id_function`（基于 router 名 + method + path 生成稳定 operationId），使 schema 哈希不受 handler 函数重命名影响。
2. **冻结产物 = 仓库根 `openapi.json`（提交、可评审）+ `openapi.sha256`（规范序列化哈希）**。
   - 规范字节：`json.dumps(schema, sort_keys=True, ensure_ascii=False, separators=(",", ":"))` 后 UTF-8 编码。
   - `openapi.json` 以 `indent=2` 格式化落盘供评审；哈希对规范字节计算，不受格式化影响。
3. **后端命令 `python -m inc.api.openapi dump [--check]`**（随 M1.12 实现）：
   - `dump`：从 app factory 生成 schema，写 `openapi.json` + `openapi.sha256`。
   - `--check`：内存重生成，规范字节 SHA-256 与提交的 `openapi.sha256` 比对，不一致即退出非零。
4. **生成器（确认 G0 登记）**：`openapi-typescript` 从冻结的 `openapi.json` 生成纯类型到 `admin/src/common/api/generated/`（只读、禁手工编辑）；`npm run generate:api` 执行；统一 HTTP 层为手写薄适配层（base URL / 超时 / request_id / 204 / ErrorResponse 解析），不再维护手写后端 DTO。
5. **过期检查双向兜底**：
   - 后端：pytest 质量门（或 CI step）跑 `dump --check`。
   - 前端：`npm run check`（或 CI step）跑 `dump --check`，与 typecheck 串联——schema 变更但未重新生成即失败。
6. **版本化与变更工作流**：
   - `/api/v1` URL 前缀是版本边界；v1 内只允许向后兼容的增量变更，破坏性变更必须新开 `/api/v2`（另产一份冻结产物），不得静默改写 v1。
   - 契约变更流程：改规格 → 改实现 → `dump` → `generate:api` → 更新消费方 → 提交时把 `openapi.json` 的 PR diff 作为契约评审单元。
7. **错误模型冻结**：错误响应组件 `ErrorResponse{code, message, detail, request_id}`（[kernel/errors.md](../kernel/errors.md) §3）是契约的一部分；错误码以代码登记处 + errors 规格为权威，A1 只依赖稳定错误码分支，不解析自由文本 message。
8. **冻结时机**：本 ADR 冻结机制；首份冻结产物随 M1.12 落地（health 先行，见 ADR-0015）；auth 契约在 G3（认证契约门）冻结。A1.2 可在产物缺位前对 fixture schema 搭建并单测工具链与适配层，产物落地后切换真实契约。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| A 提交快照 + 哈希门（采用） | 契约可评审、前端构建不依赖后端在线、漂移双向可检 | 每次契约变更需按流程重新生成并提交产物 | — |
| B 仅 live `/openapi.json`，前端构建时抓取 | 无重复产物 | 后端必须在线才能构建；漂移不可检测；无法 PR 评审 | 破坏 CI 隔离与"契约可评审"约束 |
| C 手写 DTO + axios（模板现状） | 零新工具 | 双重事实来源、漂移、无契约类型安全 | 与 G3 "不得手写 DTO" 直接冲突 |

## 后果

### 正面
- 契约即评审单元：后端 schema 的每次变更有 PR diff 可查。
- 前端构建不依赖后端在线；schema 漂移两端双兜底。
- 生成类型从契约派生，杜绝手写 DTO 漂移。

### 负面 / 代价
- 每次契约变更需按流程重新生成并提交 `openapi.json` 变更（仪式成本，与 ADR-0008 同理）。
- operationId 稳定性依赖 `generate_unique_id_function` 固定；改 app factory 装配需重跑 `dump`。

### 逃生门（如适用）
- 生成器若替换（如改用后端 SDK 生成），只影响 generate 命令与 `generated/` 目录，冻结产物与哈希门不变。
- 若未来多 API 版本并行，按版本各持一份 `<version>.openapi.json` + 对应哈希，机制不变。
