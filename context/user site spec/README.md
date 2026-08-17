# 用户站规格与设计案

本目录是用户站独立规格入口，与 `context/spec/` 后端规格、`context/admin dash spec (SPA)/` 管理员端规格并列，三者共同归属于 `context/` 唯一事实源。

## 文档职责

1. [`user-site.md`](user-site.md)：Astro SSR 基础框架、BFF/OIDC 会话、SEO 所有权、Markdown 渲染合同、FastAPI 用户侧端点、OpenAPI 投影和发布门。
2. [`LAYOUT.md`](LAYOUT.md)：页面模板、应用外壳、信息优先级、内容密度、响应式重排与区块组合。
3. [`DESIGN.md`](DESIGN.md)：颜色、字体、间距、圆角、阴影、组件元素、视觉状态和 Design Tokens。

## 约束优先级

- 后端 capability、feature、HTTP、数据与安全合同仍由 [`../spec/`](../spec/) 持有；用户站文档只定义其消费方式，不复制后端所有权。
- `user-site.md` 的认证、安全、SEO、SSR、可访问性和 OpenAPI 合同优先于布局与视觉表达。
- `LAYOUT.md` 决定内容放置、优先级和响应式重排；`DESIGN.md` 决定元素外观。两者不得各自维护路由、DTO 或业务状态机。
- 三份文档都是长期规格，不在此目录维护实施进度、临时任务或第二套 roadmap。

## 推荐阅读顺序

先读 `user-site.md` 确定系统边界，再读 `LAYOUT.md` 确定页面结构，最后用 `DESIGN.md` 落实视觉元素与 tokens。实现变更仍按“规格 -> 失败测试 -> 实现 -> 集成验证”推进。
