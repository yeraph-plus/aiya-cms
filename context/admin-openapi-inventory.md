# aiya-cms OpenAPI 端点清单（P0 施工产物）

> 一次性施工清单，由 aiya-cms (cms) 0.1.0 的 `openapi.json` 生成；非规格事实来源。
> 生成时间：2026-08-09T22:51:56.574Z。管理员页面的合同归属见 `context/admin-ts-migration-plan.md` §5.2/§7。

共 71 个端点；全部受保护端点使用 HTTPBearer（`security: bearer`），无 operation 级 security 覆盖时沿用全局。

| 方法 | 路径 | operationId | 摘要 | 响应码 | 安全 | 页面归属（adapter → 页面） |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/.well-known/openid-configuration` | `discovery__well_known_openid_configuration_get` | Discovery | 200 | public | auth.ts（oidc.ts 协议处理） → OIDC Discovery |
| GET | `/api/v1/admin/assets` | `list_assets_api_v1_admin_assets_get` | List Assets | 200, 422 | bearer | assets.ts → system/assets |
| POST | `/api/v1/admin/assets` | `register_external_api_v1_admin_assets_post` | Register External | 200, 422 | bearer | assets.ts → system/assets |
| DELETE | `/api/v1/admin/assets/{asset_id}` | `delete_asset_api_v1_admin_assets__asset_id__delete` | Delete Asset | 204, 422 | bearer | assets.ts → system/assets |
| GET | `/api/v1/admin/assets/{asset_id}` | `get_asset_api_v1_admin_assets__asset_id__get` | Get Asset | 200, 422 | bearer | assets.ts → system/assets |
| PATCH | `/api/v1/admin/assets/{asset_id}` | `update_metadata_api_v1_admin_assets__asset_id__patch` | Update Metadata | 200, 422 | bearer | assets.ts → system/assets |
| GET | `/api/v1/admin/assets/{asset_id}/url` | `resolve_url_api_v1_admin_assets__asset_id__url_get` | Resolve Url | 200, 422 | bearer | assets.ts → system/assets |
| POST | `/api/v1/admin/assets/upload-intents` | `create_upload_intent_api_v1_admin_assets_upload_intents_post` | Create Upload Intent | 200, 422 | bearer | assets.ts → system/assets |
| POST | `/api/v1/admin/assets/upload-intents/{intent_id}/finalize` | `finalize_upload_api_v1_admin_assets_upload_intents__intent_id__finalize_post` | Finalize Upload | 200, 422 | bearer | assets.ts → system/assets |
| GET | `/api/v1/admin/audit/entries` | `list_entries_api_v1_admin_audit_entries_get` | List Entries | 200, 422 | bearer | audit.ts → system/audit |
| GET | `/api/v1/admin/capabilities` | `list_capabilities_api_v1_admin_capabilities_get` | List Capabilities | 200 | bearer | identity.ts → identity/capabilities（capability 目录） |
| GET | `/api/v1/admin/content` | `list_content_api_v1_admin_content_get` | List Content | 200, 422 | bearer | content.ts → content、content editor |
| POST | `/api/v1/admin/content` | `create_content_api_v1_admin_content_post` | Create Content | 200, 422 | bearer | content.ts → content、content editor |
| GET | `/api/v1/admin/content/{content_id}` | `get_content_api_v1_admin_content__content_id__get` | Get Content | 200, 422 | bearer | content.ts → content、content editor |
| PATCH | `/api/v1/admin/content/{content_id}` | `update_content_api_v1_admin_content__content_id__patch` | Update Content | 200, 422 | bearer | content.ts → content、content editor |
| POST | `/api/v1/admin/content/{content_id}/archive` | `archive_content_api_v1_admin_content__content_id__archive_post` | Archive Content | 200, 422 | bearer | content.ts → content、content editor |
| POST | `/api/v1/admin/content/{content_id}/pin` | `set_pin_api_v1_admin_content__content_id__pin_post` | Set Pin | 200, 422 | bearer | content.ts → content、content editor |
| POST | `/api/v1/admin/content/{content_id}/publish` | `publish_content_api_v1_admin_content__content_id__publish_post` | Publish Content | 200, 422 | bearer | content.ts → content、content editor |
| POST | `/api/v1/admin/content/{content_id}/purge` | `purge_content_api_v1_admin_content__content_id__purge_post` | Purge Content | 200, 422 | bearer | content.ts → content、content editor |
| GET | `/api/v1/admin/content/{content_id}/references` | `list_references_api_v1_admin_content__content_id__references_get` | List References | 200, 422 | bearer | content.ts → content、content editor |
| PUT | `/api/v1/admin/content/{content_id}/references` | `replace_references_api_v1_admin_content__content_id__references_put` | Replace References | 204, 422 | bearer | content.ts → content、content editor |
| POST | `/api/v1/admin/content/{content_id}/reject` | `reject_content_api_v1_admin_content__content_id__reject_post` | Reject Content | 200, 422 | bearer | content.ts → content、content editor |
| POST | `/api/v1/admin/content/{content_id}/restore` | `restore_content_api_v1_admin_content__content_id__restore_post` | Restore Content | 200, 422 | bearer | content.ts → content、content editor |
| POST | `/api/v1/admin/content/{content_id}/schedule` | `schedule_content_api_v1_admin_content__content_id__schedule_post` | Schedule Content | 200, 422 | bearer | content.ts → content、content editor |
| POST | `/api/v1/admin/content/{content_id}/submit` | `submit_content_api_v1_admin_content__content_id__submit_post` | Submit Content | 200, 422 | bearer | content.ts → content、content editor |
| POST | `/api/v1/admin/content/{content_id}/unschedule` | `unschedule_content_api_v1_admin_content__content_id__unschedule_post` | Unschedule Content | 200, 422 | bearer | content.ts → content、content editor |
| POST | `/api/v1/admin/payments/orders/{order_id}/refund` | `request_refund_api_v1_admin_payments_orders__order_id__refund_post` | Request Refund | 200, 422 | bearer | operations.ts → operations/payments（阻塞：无订单读 API） |
| POST | `/api/v1/admin/points/adjust` | `adjust_points_api_v1_admin_points_adjust_post` | Adjust Points | 200, 422 | bearer | operations.ts → operations/points |
| GET | `/api/v1/admin/points/ledger` | `list_ledger_api_v1_admin_points_ledger_get` | List Ledger | 200, 422 | bearer | points.ts → operations/points/ledger |
| GET | `/api/v1/admin/roles` | `list_roles_api_v1_admin_roles_get` | List Roles | 200 | bearer | identity.ts → identity/roles |
| POST | `/api/v1/admin/roles` | `create_role_api_v1_admin_roles_post` | Create Role | 200, 422 | bearer | identity.ts → identity/roles |
| POST | `/api/v1/admin/roles/{role_id}/assign` | `assign_role_api_v1_admin_roles__role_id__assign_post` | Assign Role | 200, 422 | bearer | identity.ts → identity/roles |
| POST | `/api/v1/admin/roles/{role_id}/revoke` | `revoke_role_api_v1_admin_roles__role_id__revoke_post` | Revoke Role | 204, 422 | bearer | identity.ts → identity/roles |
| GET | `/api/v1/admin/settings/groups` | `list_groups_api_v1_admin_settings_groups_get` | List Groups | 200 | bearer | settings.ts → system/settings、system/seo |
| GET | `/api/v1/admin/settings/groups/{group_key}` | `get_group_api_v1_admin_settings_groups__group_key__get` | Get Group | 200, 422 | bearer | settings.ts → system/settings、system/seo |
| PUT | `/api/v1/admin/settings/groups/{group_key}` | `update_group_api_v1_admin_settings_groups__group_key__put` | Update Group | 200, 422 | bearer | settings.ts → system/settings、system/seo |
| POST | `/api/v1/admin/settings/groups/{group_key}/reset` | `reset_group_api_v1_admin_settings_groups__group_key__reset_post` | Reset Group | 200, 422 | bearer | settings.ts → system/settings、system/seo |
| GET | `/api/v1/admin/taxonomy/dimensions` | `list_dimensions_api_v1_admin_taxonomy_dimensions_get` | List Dimensions | 200 | bearer | taxonomy.ts → content/taxonomy |
| GET | `/api/v1/admin/taxonomy/dimensions/{dimension_key}/terms` | `list_terms_api_v1_admin_taxonomy_dimensions__dimension_key__terms_get` | List Terms | 200, 422 | bearer | taxonomy.ts → content/taxonomy |
| POST | `/api/v1/admin/taxonomy/dimensions/{dimension_key}/terms` | `create_term_api_v1_admin_taxonomy_dimensions__dimension_key__terms_post` | Create Term | 200, 422 | bearer | taxonomy.ts → content/taxonomy |
| GET | `/api/v1/admin/taxonomy/targets/{target_type}/{target_id}/terms` | `get_target_terms_api_v1_admin_taxonomy_targets__target_type___target_id__terms_get` | Get Target Terms | 200, 422 | bearer | taxonomy.ts → content editor |
| DELETE | `/api/v1/admin/taxonomy/targets/{target_type}/{target_id}/terms` | `remove_target_terms_api_v1_admin_taxonomy_targets__target_type___target_id__terms_delete` | Remove Target Terms | 204, 422 | bearer | taxonomy.ts → content/taxonomy |
| PUT | `/api/v1/admin/taxonomy/targets/{target_type}/{target_id}/terms` | `assign_terms_api_v1_admin_taxonomy_targets__target_type___target_id__terms_put` | Assign Terms | 204, 422 | bearer | taxonomy.ts → content/taxonomy |
| PATCH | `/api/v1/admin/taxonomy/terms/{term_id}` | `update_term_api_v1_admin_taxonomy_terms__term_id__patch` | Update Term | 200, 422 | bearer | taxonomy.ts → content/taxonomy |
| POST | `/api/v1/admin/taxonomy/terms/{term_id}/archive` | `archive_term_api_v1_admin_taxonomy_terms__term_id__archive_post` | Archive Term | 200, 422 | bearer | taxonomy.ts → content/taxonomy |
| GET | `/api/v1/admin/users` | `list_users_api_v1_admin_users_get` | List Users | 200, 422 | bearer | identity.ts → identity/users 列表与详情 |
| DELETE | `/api/v1/admin/users/{user_id}` | `delete_user_api_v1_admin_users__user_id__delete` | Delete User | 204, 422 | bearer | identity.ts → identity/users 列表与详情 |
| GET | `/api/v1/admin/users/{user_id}` | `get_user_api_v1_admin_users__user_id__get` | Get User | 200, 422 | bearer | identity.ts → identity/users 列表与详情 |
| POST | `/api/v1/admin/users/{user_id}/ban` | `ban_user_api_v1_admin_users__user_id__ban_post` | Ban User | 200, 422 | bearer | identity.ts → identity/users 列表与详情 |
| POST | `/api/v1/admin/users/{user_id}/unban` | `unban_user_api_v1_admin_users__user_id__unban_post` | Unban User | 200, 422 | bearer | identity.ts → identity/users 列表与详情 |
| GET | `/api/v1/me` | `me_api_v1_me_get` | Me | 200 | bearer | auth.ts → 会话初始化 |
| POST | `/api/v1/auth/password-reset/confirm` | `confirm_password_reset_api_v1_auth_password_reset_confirm_post` | Confirm Password Reset | 200, 422 | public | — → 前台账户流程，非管理员页面 |
| POST | `/api/v1/auth/password-reset/request` | `request_password_reset_api_v1_auth_password_reset_request_post` | Request Password Reset | 202, 422 | public | — → 前台账户流程，非管理员页面 |
| POST | `/api/v1/auth/register` | `register_api_v1_auth_register_post` | Register | 200, 422 | public | — → 前台账户流程，非管理员页面 |
| POST | `/api/v1/auth/verify-email` | `verify_email_api_v1_auth_verify_email_post` | Verify Email | 200, 422 | public | — → 前台账户流程，非管理员页面 |
| POST | `/api/v1/check-in` | `check_in_api_v1_check_in_post` | Check In | 200 | bearer | — → 前台/支付回调解耦，非管理员页面 |
| GET | `/api/v1/health` | `health_api_v1_health_get` | Health | 200 | public | system.ts → system/diagnostics |
| GET | `/api/v1/membership-purchase/offers` | `list_offers_api_v1_membership_purchase_offers_get` | List Offers | 200 | bearer | — → 前台/支付回调解耦，非管理员页面 |
| POST | `/api/v1/membership-purchase/orders` | `start_purchase_api_v1_membership_purchase_orders_post` | Start Purchase | 200, 422 | bearer | — → 前台/支付回调解耦，非管理员页面 |
| GET | `/api/v1/point-purchase/offers` | `list_offers_api_v1_point_purchase_offers_get` | List Offers | 200 | bearer | — → 前台/支付回调解耦，非管理员页面 |
| POST | `/api/v1/point-purchase/orders` | `start_purchase_api_v1_point_purchase_orders_post` | Start Purchase | 200, 422 | bearer | — → 前台/支付回调解耦，非管理员页面 |
| GET | `/api/v1/me/points/ledger` | `ledger_api_v1_me_points_ledger_get` | Ledger | 200, 422 | bearer | — → 前台积分流水 |
| POST | `/api/v1/webhooks/payments/{provider_key}` | `payment_webhook_api_v1_webhooks_payments__provider_key__post` | Payment Webhook | 200, 422 | public | — → 前台/支付回调解耦，非管理员页面 |
| GET | `/healthz` | `healthz_healthz_get` | Healthz | 200 | public | system.ts → system/diagnostics |
| GET | `/oidc/authorize` | `authorize_oidc_authorize_get` | Authorize | 200 | public | auth.ts（oidc.ts 协议处理） → OIDC 登录/登出 |
| GET | `/oidc/jwks` | `jwks_oidc_jwks_get` | Jwks | 200 | public | auth.ts（oidc.ts 协议处理） → OIDC 登录/登出 |
| POST | `/oidc/login` | `login_oidc_login_post` | Login | 200 | public | auth.ts（oidc.ts 协议处理） → OIDC 登录/登出 |
| GET | `/oidc/logout` | `logout_oidc_logout_get` | Logout | 200 | public | auth.ts（oidc.ts 协议处理） → OIDC 登录/登出 |
| POST | `/oidc/revoke` | `revoke_oidc_revoke_post` | Revoke | 200 | public | auth.ts（oidc.ts 协议处理） → OIDC 登录/登出 |
| POST | `/oidc/token` | `token_oidc_token_post` | Token | 200 | public | auth.ts（oidc.ts 协议处理） → OIDC 登录/登出 |
| GET | `/oidc/userinfo` | `userinfo_oidc_userinfo_get` | Userinfo | 200 | public | auth.ts（oidc.ts 协议处理） → OIDC 登录/登出 |

## 管理员缺口（无 endpoint，页面阻塞）

| 页面 | 缺口 | 对应计划章节 |
| --- | --- | --- |
| dashboard 概览 | 无 AdminSummaryProvider readmodel DTO | §7.3 / P7 |
| content 受控 data 表单 | 无 content type schema metadata 合同 | §7.3 / P7 |
| OIDC clients | 无 admin OIDC client/grant/session/key 管理 API | §7.3 / P7 |
| notifications | 无 delivery/failure/retry 管理 API | §7.3 / P7 |
| payments 列表 | 仅有按 order_id 退款 command，无订单/回执读 API | §7.3 / P7 |
| points 流水 | 仅有 balance 与 adjust，无管理员账本查询 | §7.3 / P7 |
| assets 引用检查 | 无跨能力引用检查 API；system/assets 仅管理稳定引用 | §7.3 / P7 |
