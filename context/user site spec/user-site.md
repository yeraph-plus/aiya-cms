# 用户站规格

`site/` 是 Astro SSR 客户端，只消费 user OpenAPI 和同目录设计合同。release 仅交付公开 content/community/comments 浏览，以及登录、OIDC callback、登出和受限公开浏览会话。

Astro 作为 server-side confidential OIDC client 使用 Authorization Code + PKCE；client secret、access/refresh token、verifier 和 server session 均不进入浏览器 bundle、HTML、Vue props 或本地存储。浏览器仅持有 host-only HttpOnly session cookie。

本 release 不实现 `/api/v1/me`、个人资料、头像上传、签到、积分、会员、购买、支付或退款 UI/API。缺失路由应为 404 且不得进入 user OpenAPI。公开内容保持 Markdown 原文与共享渲染合同；客户端不直连 provider SDK 或对象存储私有 credential。

Astro SSR 与管理员预览复用 `packages/markdown` 及安全 fixture。公开图床成品可使用 assets 返回的稳定 WebP URL；signed URL、token 和 provider payload 不进入缓存或 SEO 内容。客户端同时部署在 release Compose 中，生产不使用 Vite development server。
