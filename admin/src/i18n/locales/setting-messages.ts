const zhCN = {
    settings: {
        fields: {
            general: {
                site_tagline: { label: '站点标语' },
                site_logo_asset_id: { label: '站点 Logo' },
                default_locale: { label: '默认语言', options: { 'zh-CN': '简体中文', 'en-US': 'English' } },
                default_timezone: { label: '默认时区' },
                maintenance_mode: { label: '维护模式' }
            },
            seo: {
                site_name: { label: '站点名称' },
                default_title_template: { label: '默认标题模板' },
                default_description: { label: '默认描述' },
                default_share_image_asset_id: { label: '默认分享图' },
                robots_policy: { label: '搜索引擎策略', options: { 'index,follow': '允许收录并跟踪链接', 'noindex,nofollow': '禁止收录及跟踪', 'index,nofollow': '允许收录，禁止跟踪', 'noindex,follow': '禁止收录，允许跟踪' } },
                canonical_host: { label: '规范主机名' }
            },
            notification: {
                default_from_name: { label: '发件人名称' },
                email_enabled: { label: '启用邮件通知' },
                default_channel: { label: '默认渠道', options: { email: '邮件' } },
                email_provider: { label: '邮件 Provider', options: { 'email.smtp': 'SMTP', 'email.smtp2go': 'SMTP2GO' } },
                smtp_enabled: { label: '启用 SMTP' },
                smtp_host: { label: 'SMTP 主机' },
                smtp_port: { label: 'SMTP 端口' },
                smtp_username: { label: 'SMTP 用户名' },
                smtp_password: { label: 'SMTP 密码' },
                smtp_from_address: { label: '发件邮箱' },
                smtp_use_tls: { label: 'SMTP TLS' },
                smtp_starttls: { label: 'SMTP STARTTLS' },
                smtp2go_enabled: { label: '启用 SMTP2GO' },
                smtp2go_api_key: { label: 'SMTP2GO API 密钥' },
                smtp2go_region: { label: 'SMTP2GO 区域', options: { global: '全球', us: '美国', eu: '欧洲' } }
            },
            entitlements: { registration_reward: { label: '注册奖励' }, invite_reward: { label: '邀请奖励' }, gift_quota: { label: '赠送额度' } },
            object_storage: {
                storage_provider: { label: '存储 Provider', options: { s3: 'S3 兼容存储' } },
                s3_endpoint_url: { label: 'S3 Endpoint' },
                s3_virtual_host_url: { label: 'S3 虚拟主机 URL' },
                s3_public_base_url: { label: '内容公开 URL 基址' },
                s3_bucket: { label: '系统资源桶' },
                s3_avatar_bucket: { label: '头像桶' },
                s3_content_bucket: { label: '图床桶' },
                s3_region: { label: '区域' },
                s3_addressing_style: { label: '寻址方式', options: { path: '路径式', virtual: '虚拟主机式' } },
                s3_access_key_id: { label: 'Access Key ID' },
                s3_secret_access_key: { label: 'Secret Access Key' },
                content_image_max_edge: { label: '图床最大边长' },
                content_image_webp_quality: { label: 'WebP 质量' }
            },
            operations: { audit_retention_days: { label: '审计保留天数' } },
            payments: {
                provider: { label: '支付 Provider', options: { paypal: 'PayPal', epay: 'Epay' } },
                paypal_environment: { label: 'PayPal 环境', options: { sandbox: 'Sandbox', production: '生产' } },
                paypal_client_id: { label: 'PayPal Client ID' },
                paypal_client_secret: { label: 'PayPal Client Secret' },
                paypal_webhook_id: { label: 'PayPal Webhook ID' },
                epay_gateway_url: { label: 'Epay 网关地址' },
                epay_merchant_id: { label: 'Epay 商户 ID' },
                epay_merchant_key: { label: 'Epay 商户密钥' },
                epay_payment_type: { label: 'Epay 支付类型' }
            }
        }
    }
} as const;

const enUS = {
    settings: {
        fields: {
            general: {
                site_tagline: { label: 'Site tagline' },
                site_logo_asset_id: { label: 'Site logo' },
                default_locale: { label: 'Default locale', options: { 'zh-CN': 'Simplified Chinese', 'en-US': 'English' } },
                default_timezone: { label: 'Default time zone' },
                maintenance_mode: { label: 'Maintenance mode' }
            },
            seo: {
                site_name: { label: 'Site name' },
                default_title_template: { label: 'Default title template' },
                default_description: { label: 'Default description' },
                default_share_image_asset_id: { label: 'Default share image' },
                robots_policy: { label: 'Robots policy', options: { 'index,follow': 'Index, follow', 'noindex,nofollow': 'No index, no follow', 'index,nofollow': 'Index, no follow', 'noindex,follow': 'No index, follow' } },
                canonical_host: { label: 'Canonical host' }
            },
            notification: {
                default_from_name: { label: 'From name' },
                email_enabled: { label: 'Enable email' },
                default_channel: { label: 'Default channel', options: { email: 'Email' } },
                email_provider: { label: 'Email provider', options: { 'email.smtp': 'SMTP', 'email.smtp2go': 'SMTP2GO' } },
                smtp_enabled: { label: 'Enable SMTP' },
                smtp_host: { label: 'SMTP host' },
                smtp_port: { label: 'SMTP port' },
                smtp_username: { label: 'SMTP username' },
                smtp_password: { label: 'SMTP password' },
                smtp_from_address: { label: 'From address' },
                smtp_use_tls: { label: 'SMTP TLS' },
                smtp_starttls: { label: 'SMTP STARTTLS' },
                smtp2go_enabled: { label: 'Enable SMTP2GO' },
                smtp2go_api_key: { label: 'SMTP2GO API key' },
                smtp2go_region: { label: 'SMTP2GO region', options: { global: 'Global', us: 'US', eu: 'EU' } }
            },
            entitlements: { registration_reward: { label: 'Registration reward' }, invite_reward: { label: 'Invitation reward' }, gift_quota: { label: 'Gift quota' } },
            object_storage: {
                storage_provider: { label: 'Storage provider', options: { s3: 'S3-compatible storage' } },
                s3_endpoint_url: { label: 'S3 endpoint' },
                s3_virtual_host_url: { label: 'S3 virtual host URL' },
                s3_public_base_url: { label: 'Content public URL base' },
                s3_bucket: { label: 'System asset bucket' },
                s3_avatar_bucket: { label: 'Avatar bucket' },
                s3_content_bucket: { label: 'Content image bucket' },
                s3_region: { label: 'Region' },
                s3_addressing_style: { label: 'Addressing style', options: { path: 'Path', virtual: 'Virtual host' } },
                s3_access_key_id: { label: 'Access key ID' },
                s3_secret_access_key: { label: 'Secret access key' },
                content_image_max_edge: { label: 'Maximum image edge' },
                content_image_webp_quality: { label: 'WebP quality' }
            },
            operations: { audit_retention_days: { label: 'Audit retention days' } },
            payments: {
                provider: { label: 'Payment provider', options: { paypal: 'PayPal', epay: 'Epay' } },
                paypal_environment: { label: 'PayPal environment', options: { sandbox: 'Sandbox', production: 'Production' } },
                paypal_client_id: { label: 'PayPal client ID' },
                paypal_client_secret: { label: 'PayPal client secret' },
                paypal_webhook_id: { label: 'PayPal webhook ID' },
                epay_gateway_url: { label: 'Epay gateway URL' },
                epay_merchant_id: { label: 'Epay merchant ID' },
                epay_merchant_key: { label: 'Epay merchant key' },
                epay_payment_type: { label: 'Epay payment type' }
            }
        }
    }
} as const;

export { enUS, zhCN };
