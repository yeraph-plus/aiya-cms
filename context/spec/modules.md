# 模块规格

## 1. 模块结构

模块按需包含 `definition.py`、`models.py`、`schemas.py`、`repositories.py`、`services.py`、`listeners.py`、`wiring.py`、`api.py`。声明型模块可只包含 definition/wiring。

模块只能依赖 kernel 公开 API，不得 import 兄弟模块；模块间写入只通过 EventBus。

## 2. 显式装配

API 组合根按固定顺序调用：登记内容类型 → pipeline → steps/slots → events → cron/tasks → routers → fail-fast validate → freeze。新增模块修改仓内组合根与 Alembic，然后重新构建镜像；不引入 entry-point 自动发现或独立微服务装配。

## 3. 模块测试

每个模块必须先写规格和失败测试，覆盖 DTO、权限、事务、登记物、跨 type 隔离、事件副作用和 HTTP/OpenAPI。模块不得绕过 kernel Service 直接访问 kernel 表。

## 4. 当前模块

- post/forum/issue：声明式内容类型。
- interaction：独立事实表与事件驱动计数，暂不扩展为外部服务。

未来 notification、points、commerce、download、webhook、search 仍按本规格加入仓库模块，并通过 Compose 镜像发布。
