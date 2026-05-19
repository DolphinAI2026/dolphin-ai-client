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

async function dispatchCommand(cmd, args) {
  const tab = await getActiveTab();
  switch (cmd) {
    case "tab_info":
      return { id: tab.id, url: tab.url, title: tab.title };
    case "list_tabs": {
      const all = await chrome.tabs.query({});
      return {
        count: all.length,
        tabs: all.map(t => ({ id: t.id, url: t.url, title: t.title, active: t.active, windowId: t.windowId })),
      };
    }
    case "snapshot":
    case "click":
    case "type":
    case "screenshot":
    case "start_recording":
    case "stop_recording":
    case "evaluate":
      // 转发给 content script 执行
      return await sendToTab(tab.id, { type: "exec", cmd, args });
    case "navigate":
      await chrome.tabs.update(tab.id, { url: args.url });
      return { ok: true, navigated: args.url };
    default:
      throw new Error(`unknown cmd ${cmd}`);
  }
}

// 监听 popup 的状态查询
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "get_ws_status") {
    const connected = !!(socket && socket.readyState === 1);
    sendResponse({ connected, readyState: socket ? socket.readyState : -1 });
    return false;
  }
});

// 启动
connect();
