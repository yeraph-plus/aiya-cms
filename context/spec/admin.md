# 管理员核心闭环规格

## 1. 目标

管理员 SPA 同仓库维护，首版覆盖认证、概览、用户、内容、taxonomy、评论、审计、设置、任务和只读账户概览。公开站点前台、媒体库、修订历史和未来业务模块 UI 不在本版。

## 2. 交互约束

- 列表筛选、分页、排序与状态写入 URL，并在进入页面时恢复。
- 页面统一提供 loading、empty、error、403 和移动端状态；错误展示稳定 code 与 request_id。
- 操作按钮按具体 Capability 隐藏，敏感/永久删除操作必须确认。
- Content 表单依据 `/content-types` metadata 渲染字段、动作、taxonomy group；不提供未知 JSON fallback。
- Markdown 预览必须安全清洗；设置只提交声明字段的 sparse patch。
- 所有用户可见文案进入 zh-CN/en i18n，不在页面内散落硬编码文本。

## 3. 验收

Vitest 覆盖 API 适配、URL query、能力可见性、动态字段、错误状态和动作矩阵；Playwright mock/real 覆盖桌面与移动端主要读写流程。管理员构建不得产生 chunk warning，npm ci 必须可复现。

## 4. 独立实施批次

管理员端不作为 kernel 冻结的前置条件，按独立应用版本推进：

1. 收口路由可达面，移除 YummyAdmin 演示组件、store、service、model、素材和未使用依赖，同时保留 `LICENSE` 与 `UPSTREAM.md`。
2. 用生成的 `paths`/`operations` 请求体与响应类型替换手写 DTO；统一 query、加载/空/错误/403、`ApiError` 展示和 Capability 守卫。
3. 逐页完成概览、用户、内容、taxonomy、评论、审计/任务、设置和账户闭环，并补齐中文 i18n、动态字段和安全 Markdown 预览。
4. 每批先补 Vitest，再跑 mock/real Playwright 的桌面与移动矩阵；应用完成后另建应用版本标签，不改变 `kernel-v0.1.0` 公共契约。
