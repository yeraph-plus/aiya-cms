# ADR-0026: 首个管理员引导

- 状态: accepted
- 日期: 2026-08-05
- 范围: 本地开发、测试环境和显式部署初始化
- 关联: [kernel/auth.md](../kernel/auth.md)、[ADR-0017](0017-identity-user-system-design.md)、[ADR-0022](0022-auth-service-implementation.md)

## 背景

Alembic 迁移负责建立 users、roles、permissions 和关联表，并写入 canonical role/permission seed，
但不应写入固定管理员凭据。公开注册只授予 reader；HTTP 授予角色又要求 `role:assign`，
因此全新数据库需要一个受控的首个管理员引导入口。

## 决策

1. 提供 `python -m inc.cli create-admin` 和安装后的 `aiya-cms create-admin` 命令。
2. 命令只在显式执行时运行，不在 Web 进程启动时自动迁移或自动创建账号。
3. `AuthService.bootstrap_admin` 在一个 UoW 事务中创建 User、password Identity 和 `admin` 角色关联；
   密码仍经 RegisterRequest 校验并使用现有 Argon2 原语哈希。
4. 已存在同用户名或邮箱时命令失败，不静默提权或覆盖凭据；数据库必须先执行 `alembic upgrade head`。
5. 管理员引导不增加公开 HTTP 路由，生产环境由部署系统安全注入一次性参数或交互式输入。

## 验证

- 空库迁移后执行命令，登录 `/api/v1/auth/me` 返回 `admin` 角色及全量 capabilities。
- 重复用户名/邮箱返回稳定冲突错误，事务不会创建半成品用户。
- Web 启动不执行迁移、不自动创建管理员。
