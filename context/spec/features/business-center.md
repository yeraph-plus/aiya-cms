# Business Center Feature 规格

> 本文件定义下一用户站发布目标。本轮只建立规格，不实现积分消费、下载交付或第三方 OIDC 消费端点。

## 1. 定位

`business_center` 是系统内所有“消费积分取得业务结果”的统一 feature。业务能力保持独立、交付资产保持统一；业务中心只回答三件事：本次是什么受信业务、需要多少积分、扣费成功后调用哪个公开 Command/Port 完成交付。

首个业务是付费下载。未来 AI 写小说、生成图片或 OIDC 绑定的其他客户端必须注册新的产品/报价 provider，复用相同积分扣费流程，不能自行读写 points 表或复制余额判断。

法币不进入 business_center。购买积分或会员属于 [`user-center.md`](user-center.md)，所有 CNY order/refund 事实归 payments。

## 2. `BusinessProductSpec`

组合根显式注册不可变产品声明：

- `product_key`、version、owner；
- 固定 `program_key=credit`；首版拒绝其他 points program；
- `pricing_policy_key` 与 `fulfillment_port_key`；
- 可使用的 OIDC client IDs、audience/scopes；
- 单次最小/最大积分、quote TTL、consume cooldown；
- request、cost basis、fulfillment 和 result 的 Pydantic schema；
- refund/compensation policy version。

重复 key、未知 pricing/fulfillment、非 `credit` program、未注册 scope 或 schema 冲突必须启动失败。客户端永远不能直接提交 debit amount 或 behavior key。

## 3. 报价合同

`QuoteBusinessProduct` 接收 `product_key + target_ref + 产品声明允许的参数`，经对应业务 Query/Port 取得可信 cost basis，再应用纯函数 pricing policy。返回：

- `quote_id`、product/pricing version；
- `program_key=credit`、整数 `amount`；
- 安全的单位数和价格解释；
- target snapshot digest；
- `expires_at`；
- 可验证的 opaque quote token。

consume 时重新验证 token、expiry、subject、client_id 和 target digest；目标/价格版本变化返回 `business_center.quote_stale`，不得静默用新价格扣费。

## 4. 首个定价策略：下载分卷

稳定 key 为 `archive.files.fixed.v1`：

- 可计费单位是 published work manifest 中一个 active file entry；
- `unit_points=100`，固定使用 `credit`；
- `total_points = file_count * 100`；
- 首版一次购买整个 manifest，不支持客户端选择子集或提交 file count；
- 文件按 4 GiB 分卷：除最后一卷外应等于 4 GiB，最后一卷 `0 < size <= 4 GiB`；每一卷仍固定 100 积分，不按字节做浮点或阶梯换算；
- manifest version、file IDs、count 和 size snapshot 参与 quote digest。

未来改变单位价格、按实际流量、选择部分文件或优惠必须注册新 policy version，不修改 `archive.files.fixed.v1` 的历史语义。

## 5. 消费与交付 workflow

workflow key：`business_center.consume.v1`。

1. 验证 quote 和 authenticated subject/client。
2. 调用 points `DebitPoints`，behavior `business_center.consume.debit.v1`，幂等键绑定 `subject + quote_id + request idempotency key`。
3. 调用目标 fulfillment Port。下载场景调用 archive `IssueDownloadGrant`。
4. 交付能力保存自己的结果事实；business_center 返回 points entry ref 与 fulfillment ref。

余额不足时不得创建部分 grant。扣费成功、provider 暂时失败时 workflow 保持 `fulfillment_pending` 并重试，不再次 debit。达到版本化终止条件且确认没有可用交付时，调用 `ReverseLedgerEntry` 补偿并关闭 workflow；不能只删 workflow 状态。

业务历史由 points ledger 与目标 capability 事实组成。首版不建立万能 `business_orders` 表；未来若出现独立、跨产品复用的订单状态机，应提升为 capability，而不是向 feature workflow state 塞任意 JSON。

## 6. 下载交付语义

- archive grant 绑定 subject、manifest version、files、points entry ref 和 expires_at。
- 一次消费获得一个短时下载窗口内的全部文件链接；窗口内幂等刷新链接不再次扣费。
- grant 到期后重新下载需要新 quote 和新消费；首版不定义永久“已购买”权益。
- provider URL、required headers 和 token 不进入 content JSONB、points metadata、事件或 SEO 页面。
- 浏览器只收到 archive 输出的 browser-safe redirect/proxy ticket；需要 provider secret header 的 URL不得直接暴露。

## 7. OIDC 客户端消费

除 Astro BFF 外，其他 OIDC client 可以在产品声明 allowlist 中获得：

- `business.quote`：为当前 token subject 请求报价；
- `business.consume`：消费当前 subject 的积分；
- 可选的产品专属 scope，例如 `archive.download`。

token 必须包含用户 subject、正确 audience、client_id 和 scope。client credentials 或无用户 subject 的 token 首版不得消费个人积分。请求不得指定其他 subject、任意 amount、points program、provider 或 fulfillment key。

points ledger source ref 必须记录 `product_key`、quote ID、client_id 和 fulfillment opaque ref，以便审计与对账，但不保存 access token 或业务敏感输入。

## 8. HTTP 合同

| 方法与路径 | 语义 |
| --- | --- |
| `POST /api/v1/business/quotes` | 为受信产品/目标生成短时报价 |
| `POST /api/v1/business/consumptions` | 按 quote 幂等扣费并启动交付 |
| `GET /api/v1/business/consumptions/{workflow_id}` | 当前 subject/client 查询状态 |
| `GET /api/v1/me/downloads` | 本人的 archive grant 列表 |
| `POST /api/v1/me/downloads/{grant_id}/links` | 窗口内刷新 browser-safe links |

这些路径进入 user OpenAPI；admin 管理只通过所属 capability 的 `/api/v1/admin/**` Command/Query，不为业务中心建立通用后台 CRUD。

## 9. 验收

- 所有消费固定使用 `credit`；客户端篡改 amount/program/file count 无效。
- 同一幂等键并发消费只产生一条 debit 和一个 fulfillment。
- quote 过期、manifest 漂移、余额不足均不产生 grant。
- provider 临时失败可恢复且不重复扣费；终止失败有明确 reversal。
- Astro 与第三方 OIDC client 遵循相同 subject/scope/audience 合同。
- 新 AI 产品只需注册产品、pricing 和 fulfillment Port，不导入 points ORM 或复制扣费逻辑。
