# Assets Capability 规格

## 职责

assets 管理对象存储的稳定引用、私有 upload intent、finalize、删除和图片规范化；不做媒体库 UI、文件夹、在线编辑、大文件分卷、付费下载授权或外部下载目录。后四项属于规划中的 [`archive`](archive.md) capability，不能通过扩展一个万能 ObjectStorageProvider 混入 assets。业务跨能力只保存 opaque asset ID，不建立外键或持久化 signed URL。

ObjectStorageProvider 提供 upload intent、stat/read、写入、删除、短期私有 URL 和稳定公开 URL。provider 从 settings 当前 storage key 解析；调用时缺配置或错误映射为 `assets.provider_unavailable`，不泄露 credentials/SDK 内容。

## 图床成品

`content_bucket` feature 仅对管理员开放，按如下流程调用 assets 的公开命令/query/activity：创建私有上传 intent → finalize 源 asset → 轮询处理状态 → 删除成品。feature 不读 assets ORM/Repository。

assets 读取已 finalize 的暂存对象并用 Pillow 解码、缩放、编码为 WebP，之后写入 `s3_content_bucket`，记录 ready 成品，删除源暂存对象。失败时清理生成对象/源文件并记录失败状态；删除成品幂等删除 S3 对象和本地引用。

仅接受 JPEG、PNG、WebP。拒绝 SVG、GIF、动画、损坏图像、解压炸弹和超过 20 MiB 的源数据。最大边长来自 `content_image_max_edge`（默认 2560，范围 1–8192），WebP quality 来自 `content_image_webp_quality`（默认 85，范围 40–100）。成品只保留规范化 WebP，并经 `s3_public_base_url` 生成不带签名参数的稳定 URL。

## 验收

- intent/finalize/get/delete 各有管理员权限；未授权、非内容 bucket 或未 ready 源被拒绝。
- 尺寸、质量、格式、动画/炸弹、20 MiB 限制、S3 暂存/失败清理、stable URL 和删除都由测试覆盖。
- 私有 signed URL 不持久化；公开图床 URL 无 query signature。
