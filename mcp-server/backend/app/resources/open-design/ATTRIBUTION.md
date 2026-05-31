# Open Design 资源归属

本目录内的所有 markdown 内容均来自 nexu-io/open-design（MIT License），
为 ai-builder MCP server 内置的设计能力库（craft 设计原则 + 精选品牌 design systems）。

## 上游

- 仓库：https://github.com/nexu-io/open-design
- 协议：MIT（见同级 `UPSTREAM_LICENSE` 文件）
- 收录时点：2026-05-13
- 收录方式：单次 shallow clone + 选择性复制（无 fork，无双向同步）

## 内容范围

### craft/ — 11 篇设计原则文档（open-design 原创内容）

| 文件 | 简介 |
|---|---|
| anti-ai-slop.md | 7 条 AI 痕迹铁律（禁默认 indigo / 禁 emoji 当图标 / 禁两段 trust 渐变 / 禁假数据）|
| color.md | 色彩系统设计原则 |
| typography.md / typography-hierarchy.md / typography-hierarchy-editorial.md | 排版层级 |
| accessibility-baseline.md | 无障碍底线 |
| state-coverage.md | 状态覆盖 |
| form-validation.md | 表单校验 |
| animation-discipline.md | 动效纪律 |
| laws-of-ux.md | UX 法则速查 |
| rtl-and-bidi.md | RTL / 双向文本 |

### design-systems/ — 20 个精选主流品牌 DESIGN.md

涵盖消费品牌、开发者工具、enterprise、低代码搭建、AI 时代标杆、团队协作 6 大类：

- 消费品牌：apple / airbnb / notion / nike（精选未含 nike）
- 开发者工具：vercel / github / cursor / claude / supabase
- Enterprise：ibm / stripe / ant
- 低代码搭建：airtable / webflow / figma / framer
- AI 时代标杆：linear-app / shadcn
- 团队协作：slack / discord
- 现代消费应用：material

## 暴露方式

通过 4 个 MCP 工具（`app/design_mcp.py`）暴露给 dolphin agent：

- `list_design_principles()` → craft 11 篇标题列表
- `get_design_principle(name)` → 整篇 markdown
- `list_design_systems()` → 20 个 brand 名
- `get_design_system(name)` → 整份 DESIGN.md（含 visual theme / color / typography / spacing）

## 升级路径

若上游 open-design 有重要更新，手工 re-clone + re-copy 即可（不做 git submodule，避免 build / CI 复杂化）。
