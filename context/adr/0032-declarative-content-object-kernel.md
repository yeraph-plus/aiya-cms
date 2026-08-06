# ADR-0032: 声明式内容对象内核与业务类型登记

- 状态: accepted
- 日期: 2026-08-06
- 决策者: 项目维护者
- 关联: ADR-0001、ADR-0003、ADR-0007、ADR-0009、ADR-0010、ADR-0030、ADR-0031、`context/0.1.0-declarative-content-kernel-plan.md`

## 背景

现有 `content`、`taxonomy`、`comment` 以三个业务模块实现，但其表结构、CRUD、状态校验、类型隔离、term 组合筛选和评论树算法都属于所有站点形态共用的 CMS 对象能力。具体站点真正变化的是内容类型、状态、扩展字段、taxonomy 分组和评论策略。继续把共用实现留在 modules，会让每个 `post`、`forum`、`issue` 业务区重复装配相同基础能力，也使声明元数据不足以直接驱动 OpenAPI 管理界面。

项目仍处于 0.1.0 初步设计阶段。本次允许破坏性替换现有字段、DTO、方法和导入路径，不提供旧接口、旧类型或旧注册函数的兼容层。

## 决策

### 1. 归属与依赖方向

1. `Content`、`Term`、`TermRelationship`、`Comment` 的通用 ORM、Repository、UoW、Service、DTO、事件、错误码和查询实现提升到 `inc/kernel/content`、`inc/kernel/taxonomy`、`inc/kernel/comment`。
2. kernel 不提供任何具体内容类型。`post`、`forum`、`issue` 分别由 `inc/modules/<type_name>/` 中的声明类定义。
3. modules 只依赖 kernel 公开的声明接口，不互相导入；kernel 绝不导入 modules。`inc/api/wiring.py` 显式导入声明类、登记、校验并冻结注册表，禁止自动发现。
4. ADR-0001 的三层依赖红线继续有效；本 ADR 仅重新界定 CMS 通用对象能力与具体业务类型的归属。

### 2. 声明类与解释器

1. kernel 提供 `ContentType` 抽象父类、不可变定义对象和 `ContentTypeInterpreter`。注册表只保存解释器校验、规范化后的定义。
2. 子类必须显式声明：
   - `type_name`；
   - `statuses`；
   - `default_status`；
   - `transitions`；
   - `fields`；
   - `taxonomies`；
   - `comments`；
   - 可选 `trash` 策略。
3. 注册阶段 fail-fast 校验 type/group/field/status slug、重复项、默认状态、转换起止状态、公开状态、字段约束和评论策略。注册完成后冻结，运行期不可修改。
4. validator 只能是无数据库、无网络、无事件副作用的纯函数；callback 不进入 HTTP 响应。

### 3. 状态与 trash

1. 状态值和动作分离：例如 `published` 是状态，`publish` 是动作。不同内容类型可声明不同状态集合和转换表。
2. `trash` 是父类保留的通用状态，不要求子类重复登记；任何非 trash 状态都可执行 `trash`。
3. 恢复统一回到该类型的 `default_status`，并清空 `trashed_at`。
4. 进入 trash 时写入独立的 `trashed_at`。硬删除由 `content.purge_trash` Cron 按 `TrashPolicy.retention_days` 批量执行，不为每一行创建长期倒计时任务。
5. 硬删除后发布 `content.deleted`，taxonomy 关联和评论通过已登记事件处理，并由清理/重算任务兜底。
6. 软删除发布 `content.trashed`，恢复发布 `content.restored`；`content.deleted` 仅表示物理删除。trash/restore 不清理 taxonomy 关系和评论。

### 4. data 声明与 JSONB

1. `contents.data` 保存声明约束的稀疏 JSON 对象，Python/JSONB 边界模型为 `ContentDataValues(RootModel[dict[str, str]])`。
2. 持久化值一律为字符串，例如 `{"featured": "true", "price": "12.50"}`。`number`、`boolean`、`url`、`select` 等是输入组件、校验和规范化类型，不改变存储类型。
3. `ContentField` 至少包含 `slug`、`title`、`description`、`input_type`、`required`、`constraints` 和纯函数 validator。字段不提供默认值；缺少可选字段表示未设置。
4. 未声明字段一律拒绝，不保留松散未知键。字段 slug 在一个内容类型内唯一。
5. Service 只通过解释器获得规范化的 `ContentDataValues`，不得手写 dict 修改 JSONB。

### 5. Content 固定列与查询

1. 固定列保留 `id/type/title/slug/status/owner_id/content/view_count/like_count/rating_sum/rating_count/data/published_at/created_at/updated_at`。
2. 新增 `excerpt`、`comment_count`、`trashed_at`。`updated_at` 即修改时间，不新增重复的 `modified_at`。
3. `q` 在 `title/slug/excerpt` 中按字面包含匹配；独立筛选继续为 AND，多字段关键词为 OR。
4. `comment_count` 加入显式 SQL 排序白名单；`updated_at` 继续支持范围筛选和排序。所有排序追加 `id` 稳定次序。
5. `status` 的 HTTP 值使用字符串，并根据 URL 中已注册的 `type_name` 动态校验，不再由固定全局 Enum 限制。
6. ADR-0030 的分页、taxonomy 组合筛选、UUIDv7 和未来 Meilisearch 边界继续有效。

### 6. Taxonomy

1. 现有 `terms`、`term_relationships` 表结构、URL `type_name` 隔离以及同组 OR、跨组 AND 语义保持不变。
2. 内容类型以 `TaxonomyGroupDef` 声明 group 的 `slug/title/description`；post 固定声明 `category` 与 `tag`，不保留 `tags` 运行期别名。
3. taxonomy 只接受已注册内容类型和已声明 group；未知 type 返回 404，未知 group 返回 422。
4. 本次仍是扁平 term。树形 taxonomy、别名和合并不进入本次重写。

### 7. Comment

1. comment 保留 `target_type + target_id` 多态边界，不读取具体 ContentType 声明，也不导入 content Service。
2. API 组合根注入 `TargetExists(target_type, target_id)`，评论只关心目标是否存在且类型匹配。
3. 评论回复继续由 `parent_id + root_id + depth` 表达；顶层分页后一次加载全部后代，并在内存组树。最大深度、自动审核和限频由该内容类型的 `CommentPolicy` 登记。
4. `comment_count` 定义为目标下 `approved`、未占位的全部评论数量，包含回复。创建、审核转换、删除和占位转换通过事件增减计数；提供 recount 任务修复最终一致性偏差。
5. ADR-0010 的单表、多态关联和两趟组树决策继续有效。

### 8. 类型元数据 API

`GET /api/v1/content-types` 返回全部注册类型及其完整可序列化元数据：

- `type_name`、标题和描述；
- 状态、默认状态、可用动作和转换；
- data 字段元数据与约束；
- taxonomy group 元数据；
- comment policy；
- 允许的查询筛选字段和排序字段。

不返回 validator/callback。API、管理端和 OpenAPI 不维护第二份手写内容类型定义。

### 9. 隔离与权限

1. post/forum/issue 共用内核表，通过 URL `type_name`、Repository 强制 type 条件及 `(type, slug)` 唯一约束实现数据和 API 隔离。
2. 不设计多 type 同查。任何按 id 的读写仍必须同时校验 URL `type_name`。
3. 本次不新增按 type 拆分的 Capability；`type_name` 是数据范围，不是权限边界。需要分区授权时另行登记 Capability 和 ADR。

## 备选方案

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 通用对象实现进 kernel，modules 声明类型 | 基实现唯一、类型定义集中、管理端可由元数据驱动 | 扩大 kernel 稳定面，需要一次破坏性迁移 | 采用 |
| B. content/taxonomy/comment 继续作为 modules | 当前改动少，可整体替换 | 通用能力与业务声明混在一起，新增类型仍依赖组合回调 | 不采用 |
| C. 每个 post/forum/issue 复制独立表和 Service | 物理隔离强 | 重复代码、迁移和查询契约，违背通用 CMS 底座目标 | 不采用 |
| D. 每行 trash 创建延迟任务 | 到期时间精确 | 当前任务即时执行且内存调度不耐重启，长期任务数量膨胀 | 不采用 |
| E. data 允许任意键或存原生多类型值 | 写入自由 | 元数据不完整、校验和演进不稳定 | 不采用 |

## 后果

### 正面

- 新内容类型只需声明并注册，即获得统一 CRUD、查询、taxonomy、评论和 trash 生命周期。
- `/content-types` 可以直接驱动管理员动态表单和动作界面。
- post/forum/issue 共享稳定实现但不互相依赖。
- 评论保持对目标实现无感，taxonomy 组合查询语义不变。

### 负面 / 代价

- content/taxonomy/comment 成为内核稳定 API，后续变更必须更加谨慎。
- 固定字符串 JSONB 放弃 JSON 数字/布尔原生类型；所有解释必须经过字段声明。
- `comment_count` 为最终一致统计，需要事件测试与 recount 兜底。
- 现有 modules 导入路径、固定 Enum、注册 DTO 和管理端表单全部需要一次性替换。

### 逃生门

- 特定内容类型需要独立业务表时，可由模块监听内核事件维护自己的聚合表，不修改通用 contents 表。
- 评论量达到分表上限时，继续按 ADR-0010 在 Repository 层路由同构表。
- data 字段出现可排序、可聚合或多维筛选需求时提升为真实列或 taxonomy；全文搜索进入未来 search 模块。

## 测试边界

- kernel 不导入 modules；post/forum/issue 声明由 API 显式登记并在启动时冻结。
- 重复/非法 type、status、transition、field、taxonomy group 或 comment policy 启动失败。
- 未注册 type 的 content/taxonomy/comment 目标操作返回登记错误；不存在 id 不得跨 type 命中。
- data 只保存声明键和字符串值；未知键、非法规范化和缺少 required 字段返回 422。
- 每个类型的状态转换逐条验证；trash/restore/过期 purge 使用 `trashed_at`，重启不丢失删除资格；只有物理删除触发关联清理。
- `q`、状态、日期、taxonomy、分页和排序可组合；同组 OR、跨组 AND，不支持多 type。
- 评论树仍保持每页两次主查询；深度、目标存在性、占位删除和审核规则有效。
- `comment_count` 覆盖创建、pending→approved、approved→rejected/spam、删除/占位和 recount。
- `/content-types` 返回全部元数据但不暴露 callback；OpenAPI 和管理员端均从该契约生成。
