// Popup — 显示 2 项状态: backend HTTP 在线 + WebSocket 真连
const manifest = chrome.runtime.getManifest();
document.getElementById("version").textContent = manifest.version;

function setStatus(prefix, ok, msg) {
  const dot = document.getElementById("dot" + prefix);
  const txt = document.getElementById("text" + prefix);
  if (ok) { dot.classList.add("ok"); dot.classList.remove("err"); }
  else { dot.classList.add("err"); dot.classList.remove("ok"); }
  txt.textContent = msg;
}

async function checkBackend() {
  try {
    const r = await fetch("http://localhost:8000/api/health");
    if (r.ok) setStatus("Backend", true, "backend HTTP 在线");
    else setStatus("Backend", false, `backend HTTP ${r.status}`);
  } catch {
    setStatus("Backend", false, "backend 离线 (uvicorn 没跑?)");
  }
}

async function checkWs() {
  // 询问 background.js 的实际 WS 状态
  try {
    const resp = await chrome.runtime.sendMessage({ type: "get_ws_status" });
    if (resp && resp.connected) {
      setStatus("Ws", true, `WS 已连 — AI 能操作此 Chrome`);
    } else {
      setStatus("Ws", false, `WS 未连 — backend 启动了 /ws/browser-ext 吗?`);
    }
  } catch {
    setStatus("Ws", false, "background 通信失败");
  }
}

checkBackend();
checkWs();

document.getElementById("docLink").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: "https://github.com/Mars-hub404/apaas-builder-ai/blob/local/cleanup-2026-05-16/docs/browser-extension-setup.md" });
});
