# Kernel Boot 与 Registry 规格

## 1. Registry

registry 是 application container 所有的可变构建对象，freeze 后只读。kernel 提供通用 typed registry，但不预置业务注册项。

至少支持：

- capability/feature definitions。
- Command/Query handlers。
- event schemas/handlers。
- workflow/activity/signal/Cron specs。
- Port bindings。
- RouterSpec。
- diagnostics/metrics/readmodel providers。
- content types、taxonomy dimensions、points behaviors 等由 capability 提供的专用 registry factory。

专用 registry 的业务校验规则属于对应 capability，不得进入 kernel 通用 registry。

## 2. 注册行为

- `register()` 只能在 boot build phase 调用。
- key、owner、version、factory 和 dependencies 均需记录。
- 重复 key 即使对象相等也失败，避免导入顺序掩盖错误。
- 依赖解析必须确定性；禁止“最后注册覆盖前者”。
- registry 能输出排序稳定且不含 secret 的 manifest report。

## 3. Freeze 与访问

- validate 全部通过后统一 freeze；不得逐个 registry 提前冻结造成部分状态。
- freeze 后新增、替换或删除注册项均抛出 `kernel.registry_frozen`。
- 运行时 lookup 未知 key 返回稳定错误，不回退到自动导入。
- registry 不保存 request-scoped 实例；factory 生命周期由 container 管理。

## 4. 生命周期接口

可启动 provider 实现显式 `start()`/`stop()` 或 async context manager，并声明依赖顺序。构造函数和 module import 不得连接网络、数据库或启动线程。

启动失败时按已完成顺序反向 stop。停止必须幂等，并允许部分构造对象安全释放。

## 5. Fail-fast 清单

启动前至少检查：

- manifest 引用的 capability/feature 存在且版本满足。
- 所有必需 Port 唯一绑定。
- command/query/router 权限已登记。
- event/activity/workflow/Cron key 唯一且 schema/version 完整。
- handler 消费的事件版本已注册。
- feature 声明的 content type、dimension、points behavior 无冲突。
- provider 配置完整，只有被启用 provider 才要求其 secret。
- migration manifest 包含所有随发行版交付的 table owners。

## 6. 验收

- 随机化声明导入顺序不改变 manifest report。
- 构造、import、validate 阶段均没有后台任务。
- freeze 后变更测试失败。
- 部分 provider 启动失败时已启动资源全部关闭。
- 未启用 provider 的配置可以不存在且不会建立连接。
