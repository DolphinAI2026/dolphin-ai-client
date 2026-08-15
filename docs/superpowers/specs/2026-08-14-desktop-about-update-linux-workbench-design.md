# 桌面端关于更新与 Linux 工作台修复设计

## 目标

- 在桌面设置中提供清晰的客户端版本与手动更新入口。
- 修复 Linux 客户端打开 Code 工作台时，Runtime 已就绪但 iframe 仍无法进入可交互状态的问题。

## 关于与更新

桌面设置左侧在“存储与诊断”之后新增“关于与更新”。页面展示：

- 产品名 `Dolphin Code`。
- 当前客户端版本 `v${__APP_VERSION__}`。
- 当前运行形态：桌面客户端或 Web 调试预览。
- “检查更新”按钮。

桌面客户端直接复用现有 `checkAndPromptUpdate({ silentIfNone: false })` 更新链路，不新增后端接口或更新协议。
Web 调试预览仍展示版本信息，但禁用更新按钮，并明确说明更新仅能在桌面客户端执行。

## Linux Code 工作台

已确认本地 Runtime manager、Codex、会话创建和 `/open` 接口正常，因此修复范围限定在工作台 iframe 链路：

1. 检查 `/api/code-runtime/<session>/builder/` 返回的 HTML、重定向和 Cookie。
2. 检查 HTML 引用的 JavaScript、CSS、动态模块和 API 路径是否保留代理前缀，并验证 Content-Type。
3. 检查 iframe 页面是否实际发送 `builder.ready`，以及宿主是否因来源、`frameKey` 或消息格式丢弃事件。
4. 只修复被证据证明失败的边界，不再调整已经正常的 Runtime manager。

## 错误处理

- 更新检查失败继续显示现有 updater 的真实错误，不使用模糊的“无法连接”提示。
- iframe 资源或 readiness 失败应记录可定位的阶段和资源信息；界面仍使用现有工作台加载与重试入口。

## 验证范围

- 桌面设置专项组件验证：版本显示、桌面更新按钮、Web 禁用状态。
- Linux 专项验证：代理 HTML 及关键资源返回正确内容，`builder.ready` 能让 pending iframe 转为 active。
- 不运行无关的全量测试，不重新验证已通过的 Runtime manager 跨平台锁测试。
