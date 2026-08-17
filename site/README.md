# Aiya CMS 用户站

`site/` 是独立部署的 Astro SSR 用户站。长期合同以
[`context/user site spec/user-site.md`](../context/user%20site%20spec/user-site.md)
为准；本文件只保留本地运行入口。

```powershell
Copy-Item .env.example .env
npm install
npm run generate:api
npm run test
npm run lint
npm run build
npm run dev
```

FastAPI 初始化前，在仓库根 `.env` 设置与 `SITE_OIDC_CLIENT_SECRET` 相同的
`AIYA_SITE_OIDC_CLIENT_SECRET`，再运行 `python -m inc.cli install`。生产环境必须使用
HTTPS 的站点/API/OIDC origin、独立的高熵 client secret 和可持久化 Redis；不得使用示例值。
`SITE_ENVIRONMENT` 与 `SITE_ORIGIN` 同时也是镜像构建参数，修改后必须重新构建镜像，确保
`__Host-` Secure session cookie 与 canonical origin 在构建时生效。
