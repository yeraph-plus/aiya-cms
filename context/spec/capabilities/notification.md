# Notification Capability 规格

## 1. 职责

notification 管理通知意图、模板变量、渠道选择、收件目标快照和可靠投递状态。Email、SMS 等是 adapter，不通过继承扩展一个全知 MailService。

notification 不决定“何时因发帖/审核/积分而通知”；该业务触发由 feature workflow 明确调用。

## 2. NotificationSpec 与模板

capability/feature 注册 NotificationSpec：

- 稳定 notification key 和版本。
- 允许 channel 及优先/回退策略。
- 模板 key、locale 和变量 Pydantic schema。
- recipient kind 和敏感级别。
- delivery/retry/retention policy。

模板可以由受控资源文件或 capability 表保存，但模板变量 schema 和可用 channel 必须由代码声明。禁止在数据库模板中执行任意 Python/SQL/网络逻辑。

### 2.1 Template 定义的导出边界

`notification template` 是后端预留定义面：模板 key/version、变量 schema、channel 与 locale 合同由 capability/feature 注册并在启动时校验。当前未导出 `/api/v1/admin/notifications/templates` 的读取、创建、更新、删除或发布接口，管理员 SPA 不提供模板目录或模板编辑器。

未来的管理员通知页面只管理 delivery/attempt 的只读查询以及 `RetryDelivery`、`CancelPendingNotification` 等已命名运行态 Command。SMTP/SMS provider 配置继续通过受控 settings group 管理，不构成模板管理接口。若以后要开放模板维护，必须先定义版本发布、变量 schema 兼容、预览安全、权限和审计合同，再显式加入 RouterSpec/OpenAPI。

当前管理侧 HTTP 面固定为：

- `GET /api/v1/admin/notifications/deliveries`：按 status、channel、provider、spec、recipient 过滤并稳定分页；
- `GET /api/v1/admin/notifications/deliveries/{delivery_id}`：返回 intent、delivery 与 attempt 列表；
- `POST /api/v1/admin/notifications/deliveries/{delivery_id}/retry`：调用 `RetryDelivery`；
- `POST /api/v1/admin/notifications/deliveries/{delivery_id}/cancel`：调用 `CancelPendingNotification`。

不得以 generic PATCH 或状态字段覆盖替代命名 Command。

## 3. 表所有权

- `notification_templates`：key/version/channel/locale、subject/body、状态和变量 schema version。
- `notification_intents`：notification key、business idempotency key、recipient ref、variables、requested time/state。
- `notification_deliveries`：intent、channel/当前或最终 provider、加密或 tokenized 收件地址快照、workflow attempt、provider message ref、状态、next retry/error category。
- `notification_delivery_attempts`：delivery、workflow attempt、provider 顺序/key、归一化结果、provider message ref、错误分类与开始/完成时间；不保存完整地址或渲染正文。

variables 为有模型 JSONB，不得包含不必要 secret。收件地址为可靠重试所需的受限个人数据，必须加密/脱敏日志并按 retention policy 清理。

## 4. Port 与 adapters

- `RecipientResolver`：按 opaque recipient ref 解析当前允许的 channel/address。
- `NotificationProvider`：发送一个已渲染 delivery，返回 `delivered/failed/unknown/unavailable` 之一以及是否确认允许切换 provider。
- Email/SMS adapter 负责 SDK client、credential、timeout、provider idempotency、限流和错误分类。
- Email adapter 的连接配置由 `site_settings` 的 `notification` settings 组填写，adapter 每次投递时读取该组。SMTP 与 SMTP2GO 复用现有 sender 字段，各自拥有 provider 开关；禁用或缺少必需配置返回 `unavailable`。凭据字段登记为 sensitive。

Port 由 notification 定义，identity 或外部通讯录 adapter 由组合根绑定；notification 不导入 identity。

## 5. Commands 与 activity

- `RequestNotification`：校验 spec/variables，幂等创建 intent 和 delivery 计划。
- `CancelPendingNotification`：只能取消尚未交给 provider 的 delivery。
- `RetryDelivery`：管理员有权限的显式恢复 Command。
- `notification.deliver.v1` activity：领取、渲染、按组合根顺序调用 provider、逐 provider 记录尝试并归并最终结果。

feature 可以直接调用 RequestNotification activity/Command；不得自行实例化 provider SDK。

## 6. 投递语义

- intent 以业务 idempotency key 去重，重复请求返回同一结果。
- delivery 使用 lease，支持多 worker。
- provider 支持 idempotency key 时必须传递稳定 key。
- provider timeout 后结果不明时标记 `unknown`，先查询 provider 或人工恢复；不得盲目重发造成重复通知。
- provider `unavailable` 不计为网络发送失败，继续调用同 channel 的下一个 provider；全部 unavailable 时以 `notification.no_available_provider` 永久失败并等待显式恢复。
- 只有 adapter 明确证明请求未被 provider 接受时才能返回允许切换；连接建立失败、明确 429 等可以切换，read timeout、提交后断线、成功响应无法解析等必须归 `unknown` 并停止切换。
- provider 顺序由组合根静态声明，不由运行时 settings 改写；同一 provider 的稳定幂等键不随 workflow retry 次数变化。
- 永久错误进入 failed，暂时错误按 policy 重试，超限进入 dead。
- channel 未绑定或模板缺失在启动校验或请求阶段明确失败，不静默丢弃。

外部通知无法提供严格 exactly-once；系统保证 intent/delivery 不重复创建，并在 provider 能力范围内最大化幂等。

## 7. 状态和事件

delivery 状态至少为 `pending`、`sending`、`delivered`、`unknown`、`failed`、`dead`、`cancelled`。

事件：

- `notification.requested.v1`
- `notification.delivered.v1`
- `notification.delivery_failed.v1`
- `notification.delivery_dead.v1`

事件和日志不携带完整收件地址或渲染后的敏感正文。

## 8. Diagnostics 与验收

- diagnostics 检查 pending age、expired lease、unknown/dead 积压、模板/spec 漂移和未绑定 channel。
- Email 与 SMS fake adapters 通过相同合同测试。
- 重复 RequestNotification 不新增 delivery。
- worker 崩溃可恢复；provider timeout unknown 不自动造成双发。
- 模板变量缺失/多余、locale fallback 和敏感字段 redaction 有测试。
- 未装配 notification 的 manifest 不连接任何邮件/SMS provider。
