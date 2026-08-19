# 用户站布局设计（LAYOUT）

本文件是用户站设计案的页面结构合同，适用于 Astro SSR 页面与 Vue islands。基础框架、路由、数据和安全边界见 [`user-site.md`](user-site.md)；颜色、字体、形状、组件外观和 Design Tokens 见 [`DESIGN.md`](DESIGN.md)。当三者冲突时，认证、安全、SEO、可访问性、SSR 和 OpenAPI 合同优先于布局表达。

## 1. 文档目的

本文件定义用户站的**页面布局系统（Layout System）**，用于约束页面结构、区块关系、信息层级、响应式行为与组件在不同容器中的布局方式。

本文件只描述“页面骨架”和“内容如何组织”，不定义视觉皮肤。

### 本文件负责

- 页面模板与布局范式
- 全局页面骨架
- 页面区块划分
- 主次内容层级
- 内容密度
- 栅格与流式布局行为
- 响应式重排规则
- 组件在不同页面上下文中的布局行为
- 可选区块与条件显示逻辑

### 本文件不负责

以下内容必须由 `DESIGN.md` 或 Design Tokens 定义：

- 颜色
- 字体
- 字号
- 字重
- 圆角
- 边框
- 阴影
- 具体间距数值
- 图标风格
- 动效风格
- Surface / Elevation
- 品牌视觉语言

因此实现时应遵循：

> `LAYOUT.md` 决定“放在哪里、先看到什么、怎么折叠”；  
> `DESIGN.md` 决定“长什么样”。

---

# 2. 全局布局原则

## 2.1 Application Shell

所有核心页面共享同一个应用级外壳：

```text
App
└─ AppShell
   ├─ GlobalSidebar
   ├─ MainWorkspace
   │  ├─ TopUtilityBar
   │  └─ RouteContent
   └─ GlobalOverlay
```

### GlobalSidebar

负责全局主导航。

它是应用级结构，不属于任何单一页面模板。

可承载：

- 主入口
- 内容分类
- 功能入口
- 资源入口
- 次级工具入口

### TopUtilityBar

负责全局工具，不承担主导航职责。

可承载：

- 全局搜索
- 快捷操作
- 收藏/历史类入口
- 通知
- 用户菜单
- 当前页面的轻量级上下文操作

### RouteContent

承载具体页面模板。

### GlobalOverlay

承载与路由无强绑定的全局浮层能力，例如：

- Mini Player
- 全局任务状态
- 上传进度
- 临时通知
- 跨页面持续操作

`GlobalOverlay` 必须是可选的，不应成为核心页面布局的必要依赖。

---

# 3. 全局响应式模式

响应式不依赖固定视觉尺寸，而依赖**可用横向空间与内容优先级**。

建议实现以下四种布局状态。

## 3.1 Wide

适用于宽桌面。

```text
┌──────────────┬───────────────────────────────────────────────┐
│ Sidebar      │ Top Utility Bar                               │
│              ├───────────────────────────────────────────────┤
│              │ Main Content                Context Rail?     │
│              │                                               │
└──────────────┴───────────────────────────────────────────────┘
```

行为：

- GlobalSidebar 常驻。
- TopUtilityBar 水平展开。
- 主内容区允许多列。
- 可启用可选 Context Rail。
- Featured 内容可使用多列 Grid。
- Feed 主体保持稳定阅读宽度，不应无限横向拉伸。

---

## 3.2 Standard

适用于普通桌面与横向平板。

行为：

- Sidebar 仍可常驻，但允许收窄或只保留核心导航。
- Context Rail 应优先被移除或并入主内容。
- 多列 Grid 减少列数。
- Header 工具允许折叠次要操作。
- 页面标题与筛选仍保持同一首屏结构。

---

## 3.3 Compact

适用于窄平板与小窗口。

行为：

- GlobalSidebar 从常驻结构变为折叠入口。
- TopUtilityBar 保留搜索、用户与最关键的 1–2 个操作。
- 页面内容变为单主列。
- 卡片 Grid 降级为双列或单列。
- 侧栏内容并入主内容流。
- FilterTabs 可横向滚动。
- 次要 Meta 信息允许折叠。

---

## 3.4 Mobile

适用于手机。

```text
┌───────────────────────┐
│ Top Utility Bar       │
├───────────────────────┤
│ Page Header           │
├───────────────────────┤
│ Main Content          │
│                       │
│                       │
├───────────────────────┤
│ Optional Bottom Nav   │
└───────────────────────┘
```

行为：

- 不显示固定左侧 Sidebar。
- 全局导航进入：
  - 抽屉；
  - 底部导航；
  - 或二者组合。
- 所有核心页面默认单列。
- 横向并列模块按优先级依次堆叠。
- 非核心辅助内容默认后置。
- 重复 Meta、标签、指标应减少展示。
- 交互行为必须保持可达，不允许仅因为空间不足而完全丢失核心操作。

---

# 4. 内容优先级系统

所有模板使用统一的信息优先级。

## P0 — 页面身份

用户必须首先知道“当前在哪里”。

包括：

- Page Title
- 当前 Context
- 当前对象名称
- 核心内容标题

P0 不允许在任何断点隐藏。

---

## P1 — 核心任务

当前页面最主要的操作或内容。

例如：

- 阅读内容
- 浏览 Feed
- 查看推荐
- 创建内容
- 播放媒体
- 进入某个空间

P1 必须优先占据首屏与主列。

---

## P2 — 决策辅助

帮助用户理解或筛选 P1 内容。

例如：

- Filter
- Sort
- Type
- Author
- 时间
- 摘要
- 核心指标
- 推荐理由
- 内容状态

在窄屏可压缩，但不应完全破坏决策能力。

---

## P3 — 次级探索

例如：

- Related Content
- Additional Recommendations
- 热门内容
- 相关空间
- 衍生列表

空间不足时可下移。

---

## P4 — 辅助信息

例如：

- 次要指标
- 低频操作
- 补充 Meta
- 次级工具

空间不足时允许：

- 收起
- 放入 More Menu
- 延后加载
- 移至详情层

---

# 5. 页面模板总览

系统包含 5 种基础模板：

| Template | 用途 | 第一内容实体 |
|---|---|---|
| A. Editorial Home | 发现、首页、聚合入口 | Section / Featured Content |
| B. Content Feed | 连续浏览内容 | Content |
| C. Community Hub | 进入社区/空间前的发现页 | Space / Context |
| D. Community Feed | 浏览用户发布活动 | User Post |
| E. Detail | 深度消费单个对象 | Content Object |

页面应优先由这 5 个模板组合，不应为每个路由建立独立布局系统。

---

# 6. Template A — Editorial Home

## 6.1 布局范式

Editorial Home 是一个**编辑型聚合首页**，不是无限 Feed。

它的任务是：

1. 告知用户当前最值得关注的内容。
2. 建立内容层级。
3. 让不同主题/类型内容拥有不同视觉权重。
4. 最终把用户导向更完整的内容流。

核心结构：

```text
EditorialHome
├─ HeroSlot?              P1
├─ FeaturedSection        P1
├─ ThematicSection[]      P2
└─ LatestSection          P2
```

---

## 6.2 页面骨架

```text
RouteContent
│
├─ HeroSlot                    optional
│
├─ FeaturedSection
│  ├─ SectionHeader
│  └─ FeaturedGrid
│
├─ ThematicSection
│  ├─ SectionHeader
│  ├─ SectionAction?
│  └─ ContentGrid / List
│
├─ ThematicSection
│  └─ ...
│
└─ LatestSection
   ├─ SectionHeader
   └─ DenseContentList
```

---

## 6.3 HeroSlot

Hero 是**高优先级展示槽位**，不是固定广告位。

可以承载：

- 重要内容
- 专题
- 活动
- 新功能
- 产品
- 内容合集

行为：

- 同一时间只突出一个主 Hero。
- Hero 可以没有。
- Hero 不应成为首页功能依赖。
- Hero 缺失时，FeaturedSection 自动成为首屏主内容。
- Hero 内部可以包含多个内容元素，但视觉上必须形成一个主叙事。

移动端：

- Hero 不应拆成多个并列对象。
- 次级 CTA 应折叠或后置。
- 如果 Hero 信息过多，只保留 P0/P1 信息。

---

## 6.4 FeaturedSection

目标：展示少量高价值内容。

```text
FeaturedSection
├─ SectionHeader
└─ FeaturedGrid
   ├─ FeaturedContentCard
   ├─ FeaturedContentCard
   └─ FeaturedContentCard
```

布局行为：

- Wide：多列 Grid。
- Standard：减少列数。
- Compact：双列或单列。
- Mobile：单列。
- FeaturedCard 的媒体区域优先于 Meta。
- 同一区块内卡片应保持可比较的结构。
- 卡片高度不要求绝对一致，但信息槽位应保持一致。

---

## 6.5 ThematicSection

用于组织某一主题、分类或内容集合。

```text
ThematicSection
├─ SectionHeader
│  ├─ Title
│  └─ SectionAction?
└─ ContentCollection
```

`ContentCollection` 可以使用：

- CardGrid
- HorizontalRail
- DenseList
- MixedGrid

但同一个 Section 内必须保持单一主布局逻辑。

避免：

- 同一 Section 中随意混合 3–4 种不同卡片结构。
- 为了视觉变化破坏浏览节奏。

---

## 6.6 LatestSection

用于承接高频更新内容。

```text
LatestSection
├─ SectionHeader
└─ DenseContentList
```

行为：

- 信息密度高于 Featured。
- 每条内容占用空间更低。
- 内容应以标题与核心 Meta 为主。
- 适合连续扫描。
- 不应抢过 Hero / Featured 的视觉优先级。

---

## 6.7 首页内容优先级

推荐顺序：

```text
Hero
↓
Featured
↓
主题内容
↓
最新内容
↓
次要推荐
```

原则：

> 越靠近页面顶部，内容越少、权重越高；  
> 越靠近页面下方，内容越多、密度越高。

---

# 7. Template B — Content Feed

## 7.1 布局范式

Content Feed 是**内容对象中心（Content-centric）**的连续浏览页面。

第一实体是 Content，而不是用户。

用户阅读顺序：

```text
内容是什么
↓
为什么值得看
↓
谁制作
↓
何时发布
↓
其他指标
```

---

## 7.2 页面骨架

```text
ContentFeedPage
├─ PageHeader
│  ├─ PageTitle
│  ├─ PageDescription?
│  └─ PageAction?
│
├─ FeedControls
│  ├─ FilterTabs
│  ├─ Sort?
│  └─ ViewMode?
│
└─ ContentFeed
   ├─ ContentFeedItem
   ├─ ContentFeedItem
   ├─ ContentFeedItem
   └─ ...
```

---

## 7.3 FeedControls

行为：

- 必须位于 Feed 之前。
- Filter 优先级高于 Sort。
- 当筛选条件过多时：
  - 首层只显示常用选项；
  - 其余进入扩展面板。
- 移动端允许横向滚动 Tabs。
- Filter 状态必须与页面内容产生稳定对应关系。

---

## 7.4 ContentFeedItem

标准结构：

```text
ContentFeedItem
├─ Media / Thumbnail
├─ ContentInfo
│  ├─ Type
│  ├─ Title
│  ├─ Summary?
│  └─ Meta
│     ├─ Author
│     ├─ PublishTime
│     └─ CoreMetrics?
└─ ContextAction?
```

布局模式：

### Wide

```text
┌───────────────┬─────────────────────────────┬──────┐
│ Media         │ Content Info                │ Act. │
│               │ Title                       │      │
│               │ Summary                     │      │
│               │ Meta                        │      │
└───────────────┴─────────────────────────────┴──────┘
```

### Mobile

```text
┌─────────────────────────┐
│ Media                   │
├─────────────────────────┤
│ Type                    │
│ Title                   │
│ Summary?                │
│ Meta                    │
└─────────────────────────┘
```

或对于高密度 Feed：

```text
┌────────┬────────────────┐
│ Thumb  │ Title          │
│        │ Meta           │
└────────┴────────────────┘
```

由内容密度决定，不由内容类型决定。

---

## 7.5 Feed Item 优先级

P0：

- Title

P1：

- Media
- Type
- 核心状态

P2：

- Author
- Publish Time
- Summary

P3：

- Engagement Metrics
- 次级标签

P4：

- More Action

窄屏优先移除 P4，再压缩 P3。

---

## 7.6 Feed 密度

允许提供两种密度：

### Comfortable

适合：

- 发现
- 推荐
- 媒体内容
- 视觉内容

### Dense

适合：

- 最新
- 新闻
- 更新日志
- 搜索结果
- 高频信息流

同一页面不建议在同一 Feed 中频繁切换密度。

---

# 8. Template C — Community Hub

## 8.1 布局范式

Community Hub 是**上下文发现页**。

它的目标不是立即让用户进入无限 Feed，而是先建立：

1. 这里是什么。
2. 可以进入哪些空间。
3. 哪些空间值得关注。
4. 如何开始参与。

第一实体是：

> Space / Channel / Context

而不是 Post。

---

## 8.2 页面骨架

```text
CommunityHub
├─ CommunityHeader
│  ├─ Title
│  ├─ Description
│  └─ PrimaryAction
│
├─ RecommendedSpaces
│  ├─ SectionHeader
│  └─ SpaceGrid
│
├─ ExploreSpaces
│  ├─ Search / Filter?
│  └─ SpaceCollection
│
└─ ActivityPreview? 
```

---

## 8.3 CommunityHeader

必须在首屏明确：

- 当前区域性质
- 用户可以做什么
- 最主要的参与入口

PrimaryAction 例如：

- Create
- Join
- Explore
- Start

移动端：

- PrimaryAction 紧跟 Title / Description。
- 不应被推到首屏之外。

---

## 8.4 RecommendedSpaces

```text
RecommendedSpaces
└─ SpaceGrid
   ├─ SpaceCard
   ├─ SpaceCard
   └─ SpaceCard
```

SpaceCard 应聚焦：

- Space Name
- 简短描述
- 代表性内容/状态
- 一个核心动作

不应塞入完整 Feed 信息。

---

## 8.5 ExploreSpaces

用于完整探索。

支持：

- Grid
- List
- Searchable List

Wide：

- 可以多列。

Mobile：

- 单列或双列。
- 如果信息较复杂，优先单列。

---

## 8.6 ActivityPreview

可选。

作用：

- 让用户理解这些空间里“正在发生什么”。

它不是 Community Hub 的核心主体。

因此：

- Wide 可以与 Explore 并列或位于下方。
- Compact/Mobile 应后置。
- 如果页面已经足够复杂，可完全移除。

---

# 9. Template D — Community Feed

## 9.1 布局范式

Community Feed 是**用户行为中心（User-centric）**的活动流。

第一实体是 Post。

用户阅读顺序：

```text
谁发布
↓
发布了什么
↓
附带什么内容
↓
其他人如何回应
```

这与 Content Feed 必须保持结构上的区别。

---

## 9.2 页面骨架

```text
CommunityFeedPage
├─ FeedHeader
│  ├─ ContextTitle
│  ├─ ContextMeta?
│  └─ PrimaryAction
│
├─ FeedToolbar
│  ├─ FeedTabs
│  ├─ Sort?
│  └─ Filter?
│
├─ Composer?             optional
│
└─ CommunityFeed
   ├─ PostCard
   ├─ PostCard
   ├─ PostCard
   └─ ...
```

---

## 9.3 Composer

Composer 是可选的快速发布入口。

```text
Composer
├─ UserIdentity
├─ InputTrigger
└─ QuickActions?
```

规则：

- 不应占据过多垂直空间。
- 如果完整发布流程复杂，应只做 Trigger。
- Mobile 可以压缩成一个单行动作。

---

## 9.4 PostCard

标准结构：

```text
PostCard
├─ AuthorHeader
│  ├─ Avatar
│  ├─ AuthorName
│  ├─ Timestamp
│  └─ ContextAction
│
├─ PostBody
│  ├─ Text
│  ├─ Media[]
│  └─ AttachedContent?
│
└─ InteractionBar
   ├─ PrimaryInteraction
   ├─ Comment
   ├─ Share
   └─ More
```

---

## 9.5 AuthorHeader

优先级：

P0：

- AuthorName

P1：

- Avatar
- Timestamp

P2：

- Space / Context

P4：

- More Action

Mobile 中可以压缩 Context，但不能弱化作者身份。

---

## 9.6 PostBody

布局行为：

- 纯文本内容保持自然文档流。
- 单媒体内容优先全宽展示。
- 多媒体使用统一 Gallery 逻辑。
- AttachedContent 使用嵌套卡片，但其视觉权重必须低于 Post 主体。
- 长文本允许截断，并通过展开进入完整内容。

---

## 9.7 InteractionBar

核心原则：

- 保持位置稳定。
- 同一类操作顺序一致。
- 不因 Post 内容类型变化而随意移动。

移动端：

- 保留最核心 2–3 个操作。
- 其余进入 More。
- 不允许把核心互动完全藏入二级菜单。

---

## 9.8 Community Feed 与 Content Feed 的边界

不要共用一个万能 FeedCard。

应该：

```text
ContentFeedItem
!=
PostCard
```

因为二者核心语义不同：

```text
ContentFeedItem:
Content → Creator → Meta

PostCard:
User → Post → Interaction
```

可以共用底层组件：

- Avatar
- Media
- MetaRow
- InteractionButton
- Thumbnail

但不应共用完整容器。

---

# 10. Template E — Detail

## 10.1 布局范式

Detail 是**单对象深度消费页面**。

适用于：

- Article
- Video
- Audio
- Project
- Event
- Collection
- Topic
- Resource

核心原则：

> 主对象永远优先于推荐、导航与互动。

---

## 10.2 页面骨架

```text
DetailPage
├─ DetailHeader
│  ├─ Type / Context
│  ├─ Title
│  ├─ Subtitle?
│  ├─ Creator
│  ├─ Metadata
│  └─ PrimaryActions
│
├─ PrimaryMedia? 
│
├─ DetailBody
│
├─ ObjectActions
│
├─ RelatedContent?
│
└─ Discussion?
```

Wide 可附带：

```text
DetailPage
├─ MainColumn
└─ ContextRail?
```

---

## 10.3 DetailHeader

P0：

- Title

P1：

- 核心上下文
- Creator
- Primary Action

P2：

- 时间
- 类型
- 状态
- 摘要

P3：

- 次级 Metrics
- Tags

移动端：

- 标题不压缩。
- 次级 Meta 可换行或减少。
- PrimaryActions 可以变成紧凑 Toolbar。
- 次要动作进入 More。

---

## 10.4 PrimaryMedia

存在时位于 DetailHeader 与 DetailBody 之间。

适用于：

- 视频
- 音频
- 大图
- Gallery
- Interactive
- Demo

规则：

- 它属于主对象本身，不是装饰。
- 在移动端优先保持完整可消费性。
- 不得因为响应式重排将其移动到 Related Content 之后。

---

## 10.5 DetailBody

主体阅读区域应：

- 保持稳定阅读宽度。
- 不随屏幕无限拉宽。
- 按自然文档流排列。
- 支持嵌入媒体。
- 支持内容内部小节。

如果有 Table of Contents：

- Wide 可放入 ContextRail。
- Compact 可变成顶部折叠菜单。
- Mobile 默认折叠。

---

## 10.6 ObjectActions

用于对象级操作：

- Save
- Share
- Follow
- Like
- Add to Collection
- More

可以位于：

- Header
- Body 末尾
- Sticky Utility

但不要在同一页面重复展示完整动作组。

---

## 10.7 RelatedContent

优先级低于主体。

Wide：

```text
MainColumn | ContextRail
```

或：

```text
DetailBody
↓
RelatedContent
```

Mobile：

- 默认位于主体之后。
- 不允许插入正文中间破坏阅读。

---

## 10.8 Discussion

评论/讨论始终位于主对象消费之后。

除非产品本身是以实时互动为核心，否则不要：

- 在文章正文中间插入评论；
- 让评论抢占首屏；
- 将 Related 与 Discussion 并列争夺主要阅读空间。

---

# 11. Context Rail

Context Rail 是**上下文辅助列**，不是全局固定结构。

可承载：

- 推荐内容
- 目录
- 作者信息
- 相关空间
- 热门内容
- 辅助工具
- 当前对象状态

规则：

### Wide

允许显示。

### Standard

只保留高价值 Rail。

### Compact / Mobile

必须：

- 并入主内容；
- 变成折叠块；
- 或移除。

Context Rail 内不得放置页面 P0 信息。

---

# 12. Grid、List 与 Rail 的选择规则

## 使用 Grid

当用户主要在做：

- 发现
- 对比
- 浏览多个等权对象

适合：

- Featured
- Space
- Collection
- Visual Content

---

## 使用 List

当用户主要在做：

- 扫描
- 时间顺序浏览
- 高频消费
- 搜索结果浏览

适合：

- Latest
- Feed
- Search
- Notifications

---

## 使用 Horizontal Rail

只适合：

- 辅助推荐
- 次级探索
- 有限数量内容

不适合：

- 页面主 Feed
- 关键列表
- 需要完整可见性的重要内容

Mobile 上 Horizontal Rail 应确保存在明确的横向滚动 affordance。

---

# 13. Card Layout 行为

## 13.1 Card 不决定业务类型

不要建立：

```text
ArticleCard
VideoCard
AudioCard
```

作为完全独立的布局系统。

优先建立：

```text
FeaturedContentCard
DenseContentItem
SpaceCard
PostCard
AttachedContentCard
```

业务类型通过 Variant 或 Content Adapter 处理。

---

## 13.2 Card 变体由展示语境决定

例如同一篇内容可以出现在：

```text
Home → FeaturedContentCard
Feed → DenseContentItem
Post → AttachedContentCard
Detail → RelatedContentCard
```

这比按内容类型永久绑定卡片布局更稳定。

---

# 14. Section 规则

所有页面区块遵循：

```text
Section
├─ SectionHeader
│  ├─ Title
│  ├─ Description?
│  └─ Action?
└─ SectionContent
```

规则：

- 同一级 Section 标题层级一致。
- SectionAction 不得比 SectionTitle 更突出。
- 一个 Section 只承担一个主要信息任务。
- 如果 Section 同时需要多个互不相关的 CTA，应考虑拆分区块。
- Section 不应该仅为了视觉分割而存在。

---

# 15. 空状态、加载状态与错误状态

布局规范必须考虑非理想状态。

## Empty

保留页面骨架：

```text
PageHeader
FeedControls?
EmptyState
```

不要因为没有内容而移除整个页面上下文。

---

## Loading

加载状态应尽量保持最终布局占位：

- Feed 使用行级 Placeholder。
- Grid 使用卡片 Placeholder。
- Detail 保留 Header 与 Body 骨架。

避免页面加载后发生大范围结构跳动。

---

## Error

错误信息应出现在发生错误的区域内。

例如：

```text
PageHeader
FeedControls
FeedError
```

而不是默认用全页错误替代局部 Feed。

---

# 16. Sticky 行为

允许 Sticky 的组件：

- GlobalSidebar
- TopUtilityBar
- Detail TOC
- Feed Filter
- Media Control
- 关键 Object Actions

但原则上：

> Sticky 只用于保持导航、上下文或持续任务，不用于持续占据视觉注意力。

移动端应减少同时 Sticky 的层数。

避免：

```text
TopBar
+ Filter
+ Player
+ BottomNav
```

全部同时固定导致主内容可视区域严重缩小。

---

# 17. 页面滚动模型

默认：

```text
Single Document Scroll
```

即整个 RouteContent 使用单一纵向页面滚动。

只有以下情况可引入独立 Scroll Container：

- Modal
- Drawer
- Data Table
- Chat Panel
- 特殊 Workspace

普通 Feed 页面不要同时出现：

```text
Body Scroll
+ Feed Scroll
+ Sidebar Scroll
```

多个竞争滚动区域。

---

# 18. 页面模板组合规则

允许组合：

### Home + Feed

首页最后接 Latest Feed。

### Hub + Feed Preview

Community Hub 可以展示有限活动预览。

### Detail + Related

Detail 页面底部接 Related Content。

### Detail + Discussion

Detail 页面底部接社区互动。

不推荐：

### Feed + Full Hub

会造成页面目标不清。

### Feed + Multiple Competing Hero

破坏连续扫描。

### Detail + Homepage Sections

会削弱单对象消费。

---

# 19. 页面模板选择决策

创建新页面时按以下顺序判断：

```text
用户主要是在“看一个对象”吗？
→ Detail

用户主要是在“连续浏览内容对象”吗？
→ Content Feed

用户主要是在“连续浏览用户活动”吗？
→ Community Feed

用户主要是在“选择一个上下文/空间”吗？
→ Community Hub

用户主要是在“发现多个高价值入口”吗？
→ Editorial Home
```

如果一个页面同时符合多个模板，应明确：

> 首要用户任务是什么？

模板由首要任务决定，其他能力作为 Secondary Section 加入。

---

# 20. AI Coding Agent 实现约束

AI Coding Agent 在生成页面时必须遵循：

1. 先选择 5 种模板之一。
2. 不自行创建新的全局 Shell。
3. 不在 TopUtilityBar 重复 GlobalSidebar 的主导航。
4. Content Feed 与 Community Feed 使用不同容器。
5. 页面主体只允许一个 P1 主任务。
6. Context Rail 必须是可选结构。
7. Responsive 必须通过重排与降级完成，而不是简单缩小桌面布局。
8. Mobile 默认单列。
9. Secondary Content 在窄屏下后置。
10. 不使用具体视觉参数替代布局规则。
11. 不在 `LAYOUT.md` 中硬编码品牌视觉。
12. 同一对象根据出现语境选择 Card Variant。
13. 页面必须定义 Empty / Loading / Error 状态。
14. 页面必须保持清晰的 P0 → P1 → P2 信息层级。

---

# 21. 推荐组件层级

```text
App
└─ AppShell
   ├─ GlobalSidebar
   │  ├─ Brand
   │  ├─ PrimaryNavigation
   │  ├─ ContentNavigation
   │  └─ SecondaryNavigation
   │
   ├─ MainWorkspace
   │  ├─ TopUtilityBar
   │  │  ├─ GlobalSearch
   │  │  ├─ QuickActions
   │  │  └─ UserMenu
   │  │
   │  └─ RouteContent
   │     │
   │     ├─ EditorialHome
   │     │  ├─ HeroSlot
   │     │  ├─ FeaturedSection
   │     │  ├─ ThematicSection
   │     │  └─ LatestSection
   │     │
   │     ├─ ContentFeedPage
   │     │  ├─ PageHeader
   │     │  ├─ FeedControls
   │     │  └─ ContentFeed
   │     │
   │     ├─ CommunityHub
   │     │  ├─ CommunityHeader
   │     │  ├─ RecommendedSpaces
   │     │  ├─ ExploreSpaces
   │     │  └─ ActivityPreview
   │     │
   │     ├─ CommunityFeedPage
   │     │  ├─ FeedHeader
   │     │  ├─ FeedToolbar
   │     │  ├─ Composer
   │     │  └─ CommunityFeed
   │     │
   │     └─ DetailPage
   │        ├─ DetailHeader
   │        ├─ PrimaryMedia
   │        ├─ DetailBody
   │        ├─ ObjectActions
   │        ├─ RelatedContent
   │        └─ Discussion
   │
   └─ GlobalOverlay
      └─ OptionalPersistentUI
```

---

# 22. 核心布局原则摘要

最终实现必须保持以下原则：

1. **Global Sidebar 是整站主导航。**
2. **Top Utility Bar 是工具层，不重复主导航。**
3. **首页是 Editorial Landing，而不是纯 Feed。**
4. **Hero 是 Optional Slot。**
5. **高价值内容使用低密度布局，高频内容使用高密度布局。**
6. **Content Feed 与 Community Feed 按第一实体严格区分。**
7. **Community Hub 先建立上下文，再进入活动流。**
8. **Detail 页面以单对象深度消费为唯一主任务。**
9. **Context Rail 永远是辅助结构。**
10. **Responsive 的核心是内容重排与优先级降级，而不是简单缩放。**
11. **移动端默认单主列。**
12. **Card Layout 由展示语境决定，而不是由内容业务类型决定。**
13. **P0/P1 信息在所有断点都必须保持可见。**
14. **任何页面都应只有一个最主要的视觉与交互焦点。**
15. **布局规则与视觉规则必须解耦。**

---

# 23. Template F — Account Center

Account Center 服务于当前用户的资料、积分、会员、购买、兑换和下载，不复用管理后台的数据表格工作台。

## 23.1 页面骨架

```text
AccountShell
├─ AccountHeader
│  ├─ AvatarAndIdentity
│  ├─ MembershipBadge
│  └─ PointsBalance
├─ AccountNavigation
│  ├─ Overview
│  ├─ Points
│  ├─ Membership
│  ├─ Purchases
│  ├─ GiftCard
│  └─ Downloads
└─ AccountMain
   ├─ StatusNotice
   ├─ PrimaryTask
   └─ SupportingHistory
```

- Wide/Standard：左侧窄导航 + 右侧主内容；Header 横跨内容区。
- Compact/Mobile：导航变为可横向滚动的 tabs 或当前区段 selector；不能藏进全局汉堡菜单。
- 余额、当前会员和待处理业务属于 P0/P1；账本和历史属于 P2；解释文字属于 P3。
- 单页只保留一个主要写动作，例如“签到”“购买会员”或“兑换卡密”，避免多个高风险 CTA 同时竞争。

## 23.2 Points 页面

```text
BalanceSummary
├─ AvailableCredit
├─ ExpiringSoon
└─ CheckInAction

ExpiringBuckets
└─ BucketRow × N

LedgerList
└─ LedgerRow × N
```

余额数字和最早到期信息必须在首屏。签到结果就地更新，但 ledger 仍以服务端返回为准。移动端 ledger 使用描述列表而非横向滚动表格。

## 23.3 Membership 页面

当前周期卡优先于等级目录：先显示“我现在拥有什么、何时到期、是否续费”，再显示购买选项。等级卡统一展示周期、CNY 价格、周期赠送积分和到期说明；pending fulfillment 使用单独状态卡，不能伪装为 active。

## 23.4 Purchases 与 Gift Card

- Purchases 按时间倒序显示 product、金额/来源、payment 状态和 fulfillment 状态；两类状态不合并为一个含糊 badge。
- Gift Card 使用单任务窄表单；卡密输入默认可隐藏/显示，不回显完整值。
- processing 状态提供恢复说明和 request ID，不重复显示提交按钮。

---

# 24. Template G — Work Purchase & Download

作品详情继续使用 Template E；购买与下载是 Detail 内的受控任务区，不把详情页改造成通用商店。

## 24.1 Work 文件与报价区

```text
DownloadSection
├─ ManifestSummary
│  ├─ FileCount
│  ├─ PartProfile
│  └─ ManifestVersion
├─ FileList
│  └─ PublicFileRow × N
├─ PriceSummary
│  ├─ UnitPrice
│  ├─ Quantity
│  ├─ TotalCredit
│  └─ CurrentBalance
└─ PurchaseState
   ├─ QuoteAction
   ├─ ConfirmDebit
   ├─ Processing
   ├─ InsufficientBalance
   └─ ExistingGrant
```

报价确认使用 modal/drawer，仅呈现服务端 quote；确认按钮同时显示总积分。文件多时默认折叠明细，但 file count、总价、授权窗口和“窗口内刷新不重复扣费”始终可见。

## 24.2 Download Center

已授权下载位于 `/account/downloads`：

- 按作品/manifest 分组，不按 provider 分组；用户不需要知道 OpenList 或 Gofile。
- 每个 grant 显示有效期、文件数、状态和“生成/刷新链接”动作。
- 链接产生后以文件行呈现；短时 URL 不写入页面地址栏之外的分享控件，也不提供一键复制整个 provider payload。
- expired grant 显示重新报价入口，不把刷新失败解释为需要重新扣费。

## 24.3 响应式

- Wide：文件清单与购买摘要可双列，摘要 sticky 但不得遮挡页脚。
- Compact/Mobile：先显示摘要与总价，再显示文件清单；确认动作固定在内容流中，不使用永久底部遮挡条。
- 文件名允许两行截断并提供可访问的完整名称；size/checksum/part number 在窄屏降为次级行。

---

# 25. 认证、支付与业务状态页

- Auth 表单使用单列窄容器，不出现站内内容 feed 或干扰导航。
- provider 跳转前展示订单摘要；回跳页只显示“正在确认”，不得因为 query 参数直接显示成功。
- `processing` 页面保留 order/workflow ID 的安全短显示、刷新动作和返回账户入口。
- `failed` 页面按可重试、需重新下单、需人工支持区分 CTA。
- 所有 account/auth/payment/download 页面默认无 Context Rail，避免把私有任务与推荐内容混排。
