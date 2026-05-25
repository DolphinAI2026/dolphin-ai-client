// aPaaS Builder Helper — background service worker
//
// 职责：
// 1. 保持 WebSocket 连到 backend (ws://localhost:8000/ws/browser-ext)
// 2. 收到 backend 命令 → 转给 active tab 的 content script 执行
// 3. 把 content script 的回执发回 backend
// 4. 断线 5s 后自动重连

const WS_URL = "ws://localhost:8000/ws/browser-ext";
let socket = null;
let reconnectTimer = null;
let pingTimer = null;

function log(...args) {
  console.log("[apaas-helper bg]", ...args);
}

function connect() {
  if (socket && socket.readyState <= 1) return; // already connecting/open
  log("connecting", WS_URL);
  try {
    socket = new WebSocket(WS_URL);
  } catch (e) {
    log("connect fail", e);
    scheduleReconnect();
    return;
  }

  socket.addEventListener("open", () => {
    log("connected");
    // 上报 hello
    socket.send(JSON.stringify({
      type: "hello",
      version: chrome.runtime.getManifest().version,
      ua: navigator.userAgent.slice(0, 120),
    }));
    // 心跳，避免 60s idle 断
    pingTimer = setInterval(() => {
      if (socket && socket.readyState === 1) {
        socket.send(JSON.stringify({ type: "ping", t: Date.now() }));
      }
    }, 25000);
  });

  socket.addEventListener("message", async (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { log("bad json", e); return; }
    if (msg.type === "pong") return;
    // backend 派来命令: {type:'cmd', id, cmd, args}
    if (msg.type !== "cmd") return;
    try {
      const result = await dispatchCommand(msg.cmd, msg.args || {});
      socket.send(JSON.stringify({ type: "result", id: msg.id, ok: true, result }));
    } catch (e) {
      socket.send(JSON.stringify({
        type: "result", id: msg.id, ok: false,
        error: { message: String(e && e.message || e), stack: String(e && e.stack || "") },
      }));
    }
  });

  socket.addEventListener("close", () => {
    log("closed");
    clearInterval(pingTimer);
    scheduleReconnect();
  });
  socket.addEventListener("error", (e) => {
    log("error", e);
  });
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 5000);
}

// ─────────────────────────── command dispatch ───────────────────────────

async function getActiveTab() {
  // 取用户当前 window 的 active tab
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) throw new Error("no active tab");
  return tab;
}

async function sendToTab(tabId, message, opts = {}) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, opts, (resp) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(resp);
    });
  });
}

// 2026-05-25 Phase: frame-aware snapshot/click/type. 枚举 tab 全部 frame, 每帧调
// 自己的 content script 拿 a11y tree, 聚合 frames[]. click/type 接 frame_id 精确投递.
async function getFramesForTab(tabId) {
  if (!chrome.webNavigation || !chrome.webNavigation.getAllFrames) {
    // 老 Chrome 没 webNavigation API, 退化成单 top frame
    return [{ frameId: 0, parentFrameId: -1, url: "" }];
  }
  return new Promise((resolve) => {
    chrome.webNavigation.getAllFrames({ tabId }, (frames) => {
      if (chrome.runtime.lastError || !frames || !frames.length) {
        // 权限缺 / api 不可用 → 退化到 top frame
        resolve([{ frameId: 0, parentFrameId: -1, url: "" }]);
        return;
      }
      // 过滤明显加载失败的 frame（errorOccurred）
      const usable = frames.filter(f => !f.errorOccurred);
      resolve(usable.length ? usable : [{ frameId: 0, parentFrameId: -1, url: "" }]);
    });
  });
}

function classifyFrame(url, isTop) {
  // platform iframe 判定: URL 含 /platform/ 或 /api/platform-proxy/entry (跟 backend
  // platform_proxy 路由对齐). 同源 proxy 后 src 会先打 /api/platform-proxy/entry, JS
  // 重定向到 /platform/<tid>/admin/...，两阶段都要识别为 "platform"。
  const u = String(url || "");
  if (u.includes("/platform/") || u.includes("/api/platform-proxy/entry")) return "platform";
  if (isTop) return "host";
  // 顶层 ChatPage 自己也算 host (URL 含 /ai-builder/), 但顶层已被 isTop 兜住
  return "other";
}

// 2026-05-25 自愈: agent 给的 frame_id 可能因 iframe 重建过期. role 或老 frame_id
// 命中不上时, 重新枚举 frame 按 URL 模式找当前 platform frame, retry.
async function resolveFrameByRole(tabId, role) {
  const frames = await getFramesForTab(tabId);
  for (const meta of frames) {
    const r = classifyFrame(meta.url || "", meta.frameId === 0);
    if (r === role) return meta.frameId;
  }
  return null;
}

async function snapshotAllFrames(tabId) {
  const frames = await getFramesForTab(tabId);
  const results = [];
  for (const meta of frames) {
    const isTop = meta.frameId === 0;
    try {
      const resp = await sendToTab(
        tabId,
        { type: "exec", cmd: "snapshot", args: {} },
        { frameId: meta.frameId },
      );
      const tree = resp && resp.root ? resp.root : null;
      const url = (resp && resp.url) || meta.url || "";
      results.push({
        frame_id: meta.frameId,
        parent_frame_id: typeof meta.parentFrameId === "number" ? meta.parentFrameId : -1,
        url,
        title: (resp && resp.title) || "",
        role: classifyFrame(url, isTop),
        tree,
      });
    } catch (e) {
      // 没 content script (chrome:// / about:blank / sandbox) — 留个 stub
      results.push({
        frame_id: meta.frameId,
        parent_frame_id: typeof meta.parentFrameId === "number" ? meta.parentFrameId : -1,
        url: meta.url || "",
        role: classifyFrame(meta.url || "", isTop),
        tree: null,
        error: String((e && e.message) || e),
      });
    }
  }
  return results;
}

// click/type/wait_for_text/press_key/start_recording/stop_recording/evaluate
// 统一通过 sendToTab + (可选) frameId 路由 + 自愈 retry。
//
// 寻址优先级:
//   1. args.frame_id (number)  — 显式 id, 跟以前一样
//   2. args.frame_role ("platform"/"host") — 按 role 解析当前 frame, 鲁棒抗 iframe 重建
// 都没给默认 top frame (0).
//
// 自愈: 第一次 sendToTab 撞 "Receiving end does not exist" (frame_id 过期, 通常是
// iframe 元素被 Vue :key 重建导致 frameId 变了), 立刻按 URL 重新找 platform frame
// retry 一次. response 里附 frame_id_used 让 agent 知道真实落点 (可能跟它传的不一样).
async function dispatchFrameCommand(tabId, cmd, args) {
  const a = args || {};
  let frameId = (typeof a.frame_id === "number") ? a.frame_id : undefined;
  let frameRole = (typeof a.frame_role === "string") ? a.frame_role : null;

  // role 给了 frame_id 没给 → 现场解析
  if (frameId === undefined && frameRole) {
    const fid = await resolveFrameByRole(tabId, frameRole);
    if (fid !== null) frameId = fid;
  }

  const targetFrameId = frameId;
  const opts = (targetFrameId !== undefined) ? { frameId: targetFrameId } : {};
  const STALE_MSG = "Could not establish connection";  // chrome.runtime.lastError.message 前缀

  try {
    const resp = await sendToTab(tabId, { type: "exec", cmd, args: a }, opts);
    return { ...(resp || {}), frame_id_used: targetFrameId };
  } catch (e) {
    const msg = String((e && e.message) || e);
    if (!msg.includes(STALE_MSG)) throw e;  // 别的错原样抛

    // 自愈: 老 frame_id 失效, 重新找 platform frame
    // 优先级: (a) 先按 role 找 (agent 给了 role 或我们能从 URL pattern 推断); (b) 拿原 frame_id 找它的 URL
    const desiredRole = frameRole || "platform";
    const newFrameId = await resolveFrameByRole(tabId, desiredRole);
    if (newFrameId === null) {
      // 没找到 platform frame, 报错给 agent — 这才是真"找不到 platform iframe"
      return {
        ok: false,
        error_code: "PLATFORM_FRAME_LOST",
        message: `frame_id=${targetFrameId} 已过期 (iframe 可能被重建), 重新枚举后也找不到 role=${desiredRole} 的 frame. 请重新 browser_snapshot 拿新 frame_id.`,
        original_error: msg,
        stale_frame_id: targetFrameId,
      };
    }
    if (newFrameId === targetFrameId) {
      // 找到的还是同一个 — 说明 content script 未 ready (frame 刚 nav, document_idle 没 fire)
      // 等 300ms 后 retry 一次, 还不行就报错
      await new Promise((r) => setTimeout(r, 300));
      try {
        const resp2 = await sendToTab(tabId, { type: "exec", cmd, args: a }, { frameId: newFrameId });
        return { ...(resp2 || {}), frame_id_used: newFrameId, retried_after_load: true };
      } catch (e2) {
        return {
          ok: false,
          error_code: "FRAME_NOT_READY",
          message: `frame ${newFrameId} 存在但 content script 未 ready (页面刚 navigate), retry 后仍失败`,
          original_error: msg,
        };
      }
    }
    // 不同的 frame_id, retry
    try {
      const resp2 = await sendToTab(tabId, { type: "exec", cmd, args: a }, { frameId: newFrameId });
      return {
        ...(resp2 || {}),
        frame_id_used: newFrameId,
        frame_id_was_stale: targetFrameId,
        self_healed: true,
      };
    } catch (e2) {
      return {
        ok: false,
        error_code: "FRAME_RETRY_FAILED",
        message: `老 frame_id=${targetFrameId} 过期, 自愈拿到新 frame_id=${newFrameId} retry 仍失败: ${String((e2 && e2.message) || e2)}`,
        original_error: msg,
      };
    }
  }
}

async function dispatchCommand(cmd, args) {
  const tab = await getActiveTab();
  switch (cmd) {
    case "tab_info":
      return { id: tab.id, url: tab.url, title: tab.title };
    case "list_tabs": {
      // 2026-05-21: 跟 backend browser_list_pages 字段名对齐 (pages 数组)
      const all = await chrome.tabs.query({});
      return {
        count: all.length,
        tabs: all.map(t => ({ id: t.id, url: t.url, title: t.title, active: t.active, windowId: t.windowId, type: "page" })),
      };
    }
    case "select_tab": {
      // 2026-05-21 新增 — 跟 backend browser_select_page 对齐 (chrome.tabs.update active)
      const tabId = args.tabId;
      if (typeof tabId !== "number") throw new Error("select_tab: tabId 必须是 number");
      await chrome.tabs.update(tabId, { active: true });
      if (args.bringToFront !== false) {
        try {
          const targetTab = await chrome.tabs.get(tabId);
          if (targetTab.windowId !== undefined) {
            await chrome.windows.update(targetTab.windowId, { focused: true });
          }
        } catch (e) { /* window 可能已关，忽略 */ }
      }
      return { ok: true, tabId };
    }
    case "screenshot": {
      // 2026-05-21: 改用 chrome.tabs.captureVisibleTab 比 content script 截图快得多
      // 直接拿 png dataUrl, 跟 backend browser_screenshot return schema 对齐
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
      const sizeApprox = Math.floor((dataUrl.length - "data:image/png;base64,".length) * 0.75);
      return {
        ok: true,
        image_data_url: dataUrl,
        mime_type: "image/png",
        data_size: sizeApprox,
      };
    }
    case "capture_frame_jpeg": {
      // 2026-05-21 Phase 3d: 给 MJPEG 实时流用的轻量 frame.
      // 用 jpeg quality 60 + (隐含) 浏览器原生缩放, 单帧 ~30-50KB.
      // backend MJPEG 流 endpoint 每 500ms 调一次, ~60-100KB/s 流量.
      const quality = args.quality || 60;
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
        format: "jpeg",
        quality: quality,
      });
      const sizeApprox = Math.floor((dataUrl.length - "data:image/jpeg;base64,".length) * 0.75);
      return {
        ok: true,
        image_data_url: dataUrl,
        mime_type: "image/jpeg",
        data_size: sizeApprox,
        tab_url: tab.url,
        tab_title: tab.title,
      };
    }
    case "snapshot": {
      // 2026-05-25: 聚合 tab 全部 frame. 老协议只问 top frame, 撞 iframe 内 platform
      // 拿不到 a11y tree. 现在每帧调自己的 content script, 标 role=host/platform/other.
      const frames = await snapshotAllFrames(tab.id);
      return {
        ok: true,
        tab_id: tab.id,
        tab_url: tab.url,
        tab_title: tab.title,
        frame_count: frames.length,
        frames,
      };
    }
    case "click":
    case "type":
    case "wait_for_text":
    case "press_key":
    case "start_recording":
    case "stop_recording":
    case "evaluate":
      return await dispatchFrameCommand(tab.id, cmd, args || {});
    case "navigate":
      await chrome.tabs.update(tab.id, { url: args.url });
      return { ok: true, navigated: args.url };
    default:
      throw new Error(`unknown cmd ${cmd}`);
  }
}

// 监听 popup 的状态查询
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "get_ws_status") {
    const connected = !!(socket && socket.readyState === 1);
    sendResponse({ connected, readyState: socket ? socket.readyState : -1 });
    return false;
  }
});

// 启动
connect();

// MV3 service worker 会在 ~30s idle 后睡眠。用 chrome.alarms 每 25s 唤醒一次，
// 确保 WS 心跳 + 重连 timer 持续运行。
try {
  chrome.alarms.create("apaas-keepalive", { periodInMinutes: 0.5 }); // 30s
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === "apaas-keepalive") {
      // 简单 touch：检查 socket 状态，没连就 connect
      if (!socket || socket.readyState !== 1) {
        log("keepalive: socket dead, reconnecting");
        connect();
      } else {
        // 已连：发个 ping 保活
        try { socket.send(JSON.stringify({ type: "ping", t: Date.now() })); } catch {}
      }
    }
  });
} catch (e) {
  log("alarms unavailable", e);
}

// onStartup / onInstalled 也启动 connect，避免 idle 后失联
chrome.runtime.onStartup && chrome.runtime.onStartup.addListener(() => connect());
chrome.runtime.onInstalled && chrome.runtime.onInstalled.addListener(() => connect());
