# context/ — 唯一规格来源

`context/spec/` 是当前唯一权威文档集合。代码、测试、OpenAPI 和 Compose 与规格不一致时，先更新规格，再更新测试和实现。

阅读顺序：`architecture.md` → `kernel.md` → `cms.md` → `modules.md` → `http-openapi.md` → `admin.md` → `quality-release.md`。

登记物（Capability、事件、Pipeline、扩展槽、错误码、Cron）必须在对应规格和代码常量中同时出现；禁止自动发现式装配。历史决策不在当前 context 维护，Git 历史是唯一追溯来源。
