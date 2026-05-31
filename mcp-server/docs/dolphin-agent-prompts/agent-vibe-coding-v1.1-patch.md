# Vibe Coding agent prompt v1 → v1.1 补丁（2026-05-11）

> v1 实测发现两个铁律必须加，否则 agent 写的代码沙箱里的 dev server 起不来 / 公网访问被拦。
>
> 在 `agent-vibe-coding-v1.prompt.md` 的「硬规则」节追加 2 条。

---

## 实测发现的痛点

用户对话「做 HR 全生命周期管理系统」，agent 跑完 17 步任务后报 preview URL `http://127.0.0.1:36049` — 两个真问题暴露：

1. **vite dev server 默认拦外部 host**：用户用浏览器访问 `https://p36049.vibe-first.cn` 看到：
   ```
   Blocked request. This host ("p36049.vibe-first.cn") is not allowed.
   To allow this host, add "p36049.vibe-first.cn" to `server.allowedHosts` in vite.config.js.
   ```
   vite 5+ 默认只接 localhost 的 Host header — agent 写的 `vite.config.ts` 没加 `allowedHosts`。

2. **`vibe_get_preview_url` 之前硬编 `http://127.0.0.1:<port>`** — 用户拿到内网 URL 没法访问。**已修**：现在返 `https://p<port>.vibe-first.cn`（实测 commit 已部署）。

---

## 追加这两条到现有 prompt「## 硬规则」节末尾

```markdown
9. **🚨 vite/next/express 必须配 allowedHosts**：
   生产部署的 dev server 走 `*.vibe-first.cn` 反代域，默认 host header 安全检查会拦。每个 `vite.config.ts` / `next.config.js` / express 必须配置：

   ```ts
   // vite.config.ts 必须长这样
   import { defineConfig } from 'vite'
   import vue from '@vitejs/plugin-vue'
   export default defineConfig({
     plugins: [vue()],
     server: {
       host: '0.0.0.0',                         // 监听全部接口（默认只 127.0.0.1）
       port: 6173,
       allowedHosts: ['.vibe-first.cn'],        // 接受 *.vibe-first.cn 反代
       hmr: { clientPort: 443 },                // HMR 走 https 443
     },
   })
   ```

   Next.js / Express / FastAPI 同理：
   - Next.js v15 `next.config.js` 加 `experimental.allowedDevOrigins: ['*.vibe-first.cn']` + `next dev --hostname 0.0.0.0`
   - Express：监听 `0.0.0.0` 而不是默认 `localhost`，不要在 helmet 加严格 Host 检查
   - FastAPI/uvicorn：`uvicorn app:app --host 0.0.0.0 --port 6400`（FastAPI 默认不拦 host）
   - Spring Boot：`server.address=0.0.0.0` + 不开 `server.forward-headers-strategy` 严格模式

   ⚠️ 用户访问预览 URL 拿到 "Blocked request: not allowed" → 必然是这条规则没遵守。**立即调
   `vibe_write_sandbox_files` 改 config + `vibe_run_in_sandbox(command="pkill -f vite && npm run dev",
   background=true)` 重启**，然后让用户刷新预览页。

10. **预览 URL 公网格式**：
    `vibe_get_preview_url` 返回的 `preview_url` 字段已是公网 https URL：
    ```
    https://p<host_port>.vibe-first.cn
    ```
    直接给用户这个 URL，**不要**再拼成 `http://127.0.0.1:<port>`（那是错的，内网用户访问不到）。

    如果工具返了 `http://127.0.0.1:...` 说明 host_port 不在 nginx 反代区间 [30000, 65999]，
    告诉用户「沙箱端口分配异常，请销毁重建」。
```

## 同时更新 prompt 中的「典型对话 案例 1」预览 URL 拼法

把：
```
预览：http://101.132.123.203:32768
```

改成：
```
预览：https://p32768.vibe-first.cn
```

## 改动应用

进 dolphin admin → 智能体管理 → 选 Vibe Coding (51ebb5937b) → 配置 →
人设提示词框拉到「## 硬规则」末尾追加上面 9/10 两条 + 改典型对话 1 URL → 保存 → 发布。

实测同样 prompt：用户说「做个 todo app」→ agent 应该直接生成正确 vite.config（含 allowedHosts），preview URL 一次成功。
