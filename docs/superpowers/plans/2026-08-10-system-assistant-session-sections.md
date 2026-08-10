# 系统助手双会话区 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在系统助手左侧栏并列提供隔离的系统会话和按应用分组的应用会话。

**Architecture:** `RailSidebar.vue` 在系统助手路由下并行加载系统 AI 会话与现有 Code Rail History，分别归一后渲染两个区域。系统会话继续使用当前管理动作，应用会话复用现有 Code 会话跳转与激活逻辑。

**Tech Stack:** Vue 3、TypeScript、Vue Router、Playwright

## Global Constraints

- 不修改后端 API 和会话数据模型。
- 系统会话与应用会话的数据源、失败状态和交互必须隔离。
- 不显示日期分组。
- 不合并、不推送、不发布，先通过本地真实浏览器验证。

---

### Task 1: 双数据源与双区域

**Files:**
- Modify: `frontend/src/components/v2/RailSidebar.vue`
- Modify: `frontend/src/composables/railSessions.ts`

**Interfaces:**
- Consumes: `aiChatApi.listSessions(...)`、`codeRuntimeApi.listRailHistory(...)`
- Produces: 系统会话列表、按应用分组的应用会话列表、各自独立的加载结果

- [ ] **Step 1: 补充系统助手双区域的浏览器失败断言**
- [ ] **Step 2: 并行加载系统会话和应用会话，保持失败隔离**
- [ ] **Step 3: 渲染“系统会话”和“应用会话”，应用会话按应用分组**
- [ ] **Step 4: 复用原有应用会话激活和跳转逻辑**
- [ ] **Step 5: 运行 TypeScript 检查和真实浏览器验证**

### Task 2: 本地验收入口

**Files:**
- Modify: `/tmp/d-ai-code/system-assistant-sidebar/sidebar-sessions-e2e.mjs`
- Modify: `/tmp/d-ai-code/system-assistant-sidebar/verification-entry.yaml`

**Interfaces:**
- Consumes: 本地 `5194` 服务和真实登录账号
- Produces: 双会话区截图、跳转证据、无失败请求的入口合同

- [ ] **Step 1: 验证两个区域标题和真实会话数量**
- [ ] **Step 2: 分别点击系统会话和应用会话并核对 URL**
- [ ] **Step 3: 验证低高度滚动和底部区域无重叠**
- [ ] **Step 4: 更新当前 revision 的验证入口合同**
