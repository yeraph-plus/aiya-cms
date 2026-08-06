# Kernel / cache

## 1. 设计目的

统一缓存抽象：为"首页数据等大块查询"提供缓存能力；Redis 为主实现，内存实现用于 dev/test 降级；**命中/未命中/异常日志在封装内部完成**，调用方零日志负担。

非目标：不做缓存失效广播（多实例一致性问题本期不存在）；不做本地+远程二级缓存。

## 2. 范围与依赖

- 代码位置: `inc/kernel/cache/`
- 依赖的 kernel 组件: config, errors, logging
- 被谁依赖: settings, 各模块 QueryService, tasks（防刷限频复用）
- 外部依赖: redis-py（async）

## 3. 领域模型

- `Cache` Protocol：
  - `get(key) -> str | None`
  - `set(key, value: str, ttl: int | None) -> None`
  - `delete(key) -> None`
  - `get_or_set(key, factory: Callable[[], Awaitable[str]], ttl: int) -> str`
- 值统一为 **str**（调用方负责 JSON 序列化——经 Pydantic `model_dump_json` / `model_validate_json`，禁止裸 dict）。
- key 约定：`aiya:<domain>:<...>`，由调用方用 kernel 提供的 `cache_key(*parts)` 构造函数生成，自动加 `aiya:` 前缀。
- `RedisCache`：连接池由工厂管理；Redis 不可用时抛 CACHE_001，由工厂按配置降级为 MemoryCache（记 warn 日志）。
- `MemoryCache`：进程内 dict + TTL 惰性过期；dev/test 与降级用。
- 命中/未命中/异常均记 debug/warn 日志（含 key，不含 value）。

## 4. 状态机

无。

## 5. 数据库

无。

## 6. 公开 API

```python
class Cache(Protocol): ...
def cache_key(*parts: str) -> str
def build_cache(settings: Settings) -> Cache  # 工厂：redis 不可达时降级 memory 并记日志
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
| CACHE_001 | —（内部） | 缓存后端不可用 | Redis 连接失败（工厂降级，不传染业务） |

## 10. Cron / 任务

无（MemoryCache 惰性过期，无需清理任务）。

## 11. 测试边界

- get_or_set 未命中时恰好调用 factory 一次并回填（并发下用单飞锁防击穿，单实例内 asyncio.Lock 按 key）。
- TTL 到期后 get 返回 None（MemoryCache 用时间注入测试，不等真实秒数）。
- Redis 不可达时 build_cache 降级 memory 且记录 warn。
- key 构造函数统一前缀 `aiya:`，防手工拼接绕过。

## 12. 未决事项

- 大块缓存（首页聚合）的具体键设计与失效策略：由使用方模块文档登记（读路径缓存写属合法，见 architecture/00-overview 5.2）。
- 多实例后的一致性：预留 `invalidate` 事件方案，本期不实现。

## 13. 实现边界（M1.3）

- `MemoryCache` 使用每 key `asyncio.Lock` 实现 `get_or_set` 单飞，并按 monotonic 时间执行 TTL；`RedisCache` 使用同样的进程内单飞锁避免本进程击穿。
- `build_cache(settings)` 为同步工厂：`cache_backend=memory` 直接返回 Memory，Redis 客户端构造失败返回 Memory；Redis 首次异步操作失败后固定降级到同实例 Memory，并只记录一次 warn。
- 缓存故障不向业务抛出 `CACHE_001`；该错误码用于内部登记和后续可观测性接入。所有 key 均经 `cache_key()` 生成 `aiya:<domain>:...` 命名空间。
