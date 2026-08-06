# Kernel / config

## 1. 设计目的

集中、类型化、可测试地管理全部环境配置。唯一配置入口，禁止散落 `os.environ` 读取。

非目标：不做配置热更新（运行期可变配置走 settings 组件）。

## 2. 范围与依赖

- 代码位置: `inc/kernel/config.py`
- 依赖的 kernel 组件: 无（位于依赖链最底端）
- 被谁依赖: 全部组件
- 外部依赖: pydantic-settings

## 3. 领域模型

`Settings(BaseSettings)` 单例，来源优先级：环境变量 > `.env`。字段（前缀 `AIYA_`）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `database_url` | str | `postgresql+asyncpg://aiya:aiya@localhost:5432/aiya` | 主库 DSN |
| `redis_url` | str | `redis://localhost:6379/0` | 缓存 |
| `smtp_host` / `smtp_port` / `smtp_user` / `smtp_password` / `smtp_from` | str/int | mailpit 默认值 | 邮件 |
| `jwt_secret` | str | dev 默认值（生产必须使用至少 32 字符的非空密钥） | 令牌签名 |
| `jwt_access_ttl_seconds` | int | 900 | access token |
| `jwt_refresh_ttl_seconds` | int | 1209600 (14d) | refresh token |
| `cache_backend` | `redis` \| `memory` | `redis` | 缓存后端选择 |
| `cors_origins` | list[str] | `["http://localhost:7000"]` | CORS 白名单（dev 默认 Vite） |
| `cookie_name` | str | `aiya_refresh` | refresh httpOnly Cookie 名（见 ADR-0013） |
| `cookie_secure` | bool | `False` | Cookie `Secure` 位；prod 必须为 True |
| `env` | `dev` \| `test` \| `prod` | `dev` | 运行环境 |
| `log_level` | str | `INFO` | 日志级别 |

`get_settings()` 返回缓存单例；测试用 `Settings(_env_file=None, **override)` 直接构造。

## 4. 状态机

无（纯值对象）。

## 5. 数据库

无（不落库；运行期可变配置见 [settings.md](settings.md)）。

## 6. 公开 API

```python
class Settings(BaseSettings): ...
def get_settings() -> Settings  # 缓存单例
```

### HTTP API

无。

## 7. Pipeline

无。

## 8. Event

无。

## 9. 错误码

| 错误码 | HTTP | 含义 | 触发条件 |
|---|---|---|---|
| CONFIG_001 | 500 | 必需配置缺失/非法 | Settings 构造校验失败 |

## 10. Cron / 任务

无。

## 11. 测试边界

- 默认值在无任何环境变量时可构造（dev 可跑）。
- 环境变量覆盖生效（`AIYA_DATABASE_URL`）。
- 非法值（如 `jwt_access_ttl_seconds=-1`）抛出校验错误。
- `jwt_secret` 为 dev 默认值且 `env=prod` 时拒绝启动（CONFIG_001）。
- `cookie_secure=False` 且 `env=prod` 时拒绝启动（CONFIG_001）。
- `env=prod` 且 JWT secret 为空、过短或仅空白时拒绝启动（CONFIG_001）。

## 12. 未决事项

无。
