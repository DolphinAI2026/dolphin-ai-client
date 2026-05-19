// 检查 service worker 的 WS 连接状态
chrome.runtime.getManifest && (document.getElementById("version").textContent = chrome.runtime.getManifest().version);

async function check() {
  const dot = document.getElementById("dot");
  const txt = document.getElementById("statusText");
  try {
    const r = await fetch("http://localhost:8000/api/health", { method: "GET" });
    if (r.ok) {
      dot.classList.remove("err"); dot.classList.add("ok");
      txt.textContent = "backend 在线";
    } else {
      dot.classList.add("err"); dot.classList.remove("ok");
      txt.textContent = `backend HTTP ${r.status}`;
    }
  } catch (e) {
    dot.classList.add("err"); dot.classList.remove("ok");
    txt.textContent = "backend 离线 (确认 uvicorn 跑在 8000)";
  }
}
check();
document.getElementById("docLink").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: "https://github.com/Mars-hub404/apaas-builder-ai/blob/local/cleanup-2026-05-16/docs/browser-extension-setup.md" });
});
