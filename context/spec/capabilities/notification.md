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

## 3. 表所有权

- `notification_templates`：key/version/channel/locale、subject/body、状态和变量 schema version。
- `notification_intents`：notification key、business idempotency key、recipient ref、variables、requested time/state。
- `notification_deliveries`：intent、channel/provider、加密或 tokenized 收件地址快照、attempt、provider message ref、状态、next retry/error category。

variables 为有模型 JSONB，不得包含不必要 secret。收件地址为可靠重试所需的受限个人数据，必须加密/脱敏日志并按 retention policy 清理。

## 4. Port 与 adapters

- `RecipientResolver`：按 opaque recipient ref 解析当前允许的 channel/address。
- `NotificationProvider`：发送一个已渲染 delivery，返回归一化 provider result。
- Email/SMS adapter 负责 SDK client、credential、timeout、provider idempotency、限流和错误分类。
- Email adapter 的连接配置（host/port/username/password/from_address 等）由 `site_settings` 的 `notification` settings 组填写，凭据字段登记为 sensitive；host 未配置时拒绝绑定。

Port 由 notification 定义，identity 或外部通讯录 adapter 由组合根绑定；notification 不导入 identity。

## 5. Commands 与 activity

- `RequestNotification`：校验 spec/variables，幂等创建 intent 和 delivery 计划。
- `CancelPendingNotification`：只能取消尚未交给 provider 的 delivery。
- `RetryDelivery`：管理员有权限的显式恢复 Command。
- `notification.deliver.v1` activity：领取、渲染、调用 provider、记录结果。

feature 可以直接调用 RequestNotification activity/Command；不得自行实例化 provider SDK。

## 6. 投递语义

- intent 以业务 idempotency key 去重，重复请求返回同一结果。
- delivery 使用 lease，支持多 worker。
- provider 支持 idempotency key 时必须传递稳定 key。
- provider timeout 后结果不明时标记 `unknown`，先查询 provider 或人工恢复；不得盲目重发造成重复通知。
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
