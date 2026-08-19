# Adapters 规格

## 边界与注册

adapter 位于 `inc/adapters/<consumer capability>/`，实现由消费 capability 声明的 Port。capability 不得反向导入 adapter；feature 只消费已注入的公开 Port/Resolver。`inc/api` 以稳定 key 显式注册全部允许 provider，启动时一次性建立完整 catalog 并 validate/freeze；禁止 import side effect、自动发现和启动期网络连接。

下一用户站 release 的允许 catalog 固定为：`email.smtp`、`email.smtp2go`、`payments.paypal`、`payments.epay`、`storage.s3`、`archive.openlist`、`archive.gofile`。settings capability 保存每一类 Port 的当前选择，ProviderCatalog/Resolver 在调用时读取其只读快照并解析单一当前 provider；不得按顺序静默尝试多个 provider。每个 adapter 自己验证配置、初始化短生命周期 SDK client、设置 timeout、归一化错误和关闭资源；注册本身不连接外部系统。

所有外部 adapter 提供 `check_availability()`。缺少设置、凭据无效或连通性失败只能返回安全原因码；业务调用由 capability 转换为 typed `*_provider_unavailable`，不得返回密钥、完整 endpoint 凭据或 SDK 原文。

## 邮件与对象存储

SMTP 和 SMTP2GO 从 `notification` settings 组取得 sender、开关和敏感凭据。禁用或配置不完整返回 `notification.provider_unavailable`。SMTP2GO 只允许代码定义的 global/US/EU endpoint。

S3 从 `object_storage` settings 组取得 endpoint、region、credentials 和 bucket。系统、头像和内容图床 bucket 均由 settings 提供；`s3_content_bucket` 的公开成品由 `s3_public_base_url` 拼出无签名参数、可长期缓存的 URL。私有上传/读取仍使用受限 intent 或短期 URL。缺配置或 probe/call 失败返回 `assets.provider_unavailable`。

## 支付

PayPal 和 Epay 都从 `payments` settings 组读取当前配置，且只接受 `CNY` 订单和退款。PayPal 请求固定发送 `CNY`；转换由 PayPal 处理。两者返回统一 `ProviderSession`：`redirect_url`、`qr_code_payload`、`app_url` 至少存在一项。

`WebhookRequest` 统一传递 `method`、原始 body、headers 和 query parameters；adapter 验签后返回标准 webhook event。下一用户站 release 只挂 provider callback/webhook 与 `user_center` 购买入口，不把 payments 内部管理 Command 暴露为用户 CRUD。回调进入 payments capability 后产生受信 payment result，再由 `user_center` 持久 workflow 消费。

Epay 遵循 LemPay 兼容协议：下单向 `mapi.php` 提交 form 并解析 JSON；签名按参数名排序，排除 `sign`、`sign_type`、空值和 `0`，追加商户密钥后计算小写 MD5。GET 回调校验签名和 `TRADE_SUCCESS`，成功响应字面量 `success`；查询与退款使用其 `api.php` 端点。配置为网关 URL、商户 ID、商户密钥和支付类型。

OIDC 是普通 SigningKeyStore Port，仅允许 filesystem 实现；它不是 provider catalog，也不存在内存实现。

## 外部归档下载

OpenList 和 Gofile adapter 实现 archive capability 声明的 `ArchiveDeliveryProvider`，目录分别为 `inc/adapters/archive/openlist/` 与 `inc/adapters/archive/gofile/`。它们只把 capability DTO 转换为外部 API 调用，不拥有价格、积分、购买授权或内容规则。

- `archive.openlist`
  - settings 保存 base URL、认证 token、timeout，以及是否允许 proxy/download URL；
  - adapter 使用文件 list/get/link API，把 provider path/ref 归一化为 archive locator 和短时交付结果；
  - provider 返回的 URL、headers 与过期信息只进入短生命周期 DTO，不写入 content JSONB、日志或 OpenAPI 快照。
- `archive.gofile`
  - settings 保存 API token、timeout 和允许使用 direct link 的策略；
  - adapter 使用 contents/direct-links API，显式处理 provider 的权限、到期和限流错误；
  - API token 必须使用 Bearer 认证，不能下发浏览器或持久化到业务表。

两者都必须实现：

- `resolve_manifest(locator)`：取得受控文件列表和大小/checksum 等可公开元数据；
- `issue_delivery(locator, policy)`：返回 browser-safe redirect/proxy 描述或短时 URL；
- `check_availability()`：不泄漏 endpoint/token 的诊断；
- timeout、重试边界、限流归一化、脱敏日志和 client close。

adapter 不允许把一个 provider 的失败静默回退到另一个 provider。迁移 provider 必须是 archive capability 的显式 Command，保留审计并更新 locator 版本。

## 验收

- 单独 import adapter 无连接、线程或注册副作用。
- catalog 同时含所有允许 key；settings 改变只影响后续调用。
- SMTP、SMTP2GO、S3、PayPal、Epay、OpenList、Gofile 的缺配置和失败路径均脱敏且有合同测试。
- Epay 下单、签名、GET webhook、查询、退款、幂等及金额/CNY 不匹配均使用 HTTP mock 闭合，不发起真实支付。
- OpenList/Gofile 的列表、交付、过期、限流、权限拒绝及恶意 provider payload 均使用 HTTP mock 闭合；测试不得请求真实托管服务。
