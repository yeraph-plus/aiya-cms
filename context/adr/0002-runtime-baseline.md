# ADR-0002: 运行时与工具链基线（pip + venv + Python 3.14）

- 状态: accepted
- 日期: 2026-08-02
- 决策者: 项目所有者 + AI 协作
- 关联: [architecture/00-overview.md](../architecture/00-overview.md) 第 7 节

## 背景

项目从零开始。本机环境：Python 3.14.3、Git、Docker/Docker Compose、Node 24、codegraph CLI；无 uv/poetry/psql/redis 本地安装。需要确定依赖管理、Python 版本与本地基础设施供给方式。

## 决策

- **Python 3.14**，`venv` 创建虚拟环境。
- **pip + `pyproject.toml`（PEP 621）**，所有依赖**精确钉版**（`==`），`pip install -e ".[dev]"` 安装。
- 本地基础设施用 **docker-compose** 供给：PostgreSQL 16、Redis 7、mailpit（SMTP 捕获）。
- 质量门：ruff（lint+format）、mypy（kernel 目录 strict）、pytest + pytest-asyncio + httpx（ASGITransport）。
- 代码查询以 **codegraph** 为首选接口（M0 执行 `codegraph init`，变更后 `codegraph sync`）。

## 备选方案

| 方案 | 优点 | 缺点 | 未采纳原因 |
|---|---|---|---|
| uv | 速度快、自带锁文件与 Python 版本管理 | 需额外安装 | 所有者选择 pip 零额外工具 |
| poetry | 锁文件成熟 | 需额外安装；构建后端多一层 | 同上 |
| Python 3.13 | 三方库二进制轮子最保险 | 落后一个版本 | 2026 年主流库已支持 3.14；遇阻再退 |
| 本地裸装 PG/Redis | 无 Docker 依赖 | Windows 环境脏、版本不可复现 | compose 一条命令可复现 |

## 后果

### 正面
- 零额外工具链即可起步；compose 保证 PG/Redis 版本与任何机器一致。

### 负面 / 代价
- pip 无锁文件：依赖解析漂移风险靠精确钉版缓解；传递依赖不锁定（接受，单人项目）。
- Python 3.14 存在个别三方库轮子缺失风险。

### 逃生门
- 依赖锁定需求增强时平滑迁移 uv（pyproject 不变）。
- 任一二进制依赖不支持 3.14 时退回 3.13（仅改 venv 与 pyproject 的 requires-python）。
