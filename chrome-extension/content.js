// aPaaS Builder Helper — content script
//
// 在每个 tab (含 iframe, all_frames:true) 注入。
// 接 background 转发的命令，操作 DOM。

(function () {
  if (window.__apaasHelperInstalled) return;
  window.__apaasHelperInstalled = true;

  // ─────────────────────────── recorded events ───────────────────────────
  // demonstration learning: 用户操作时存到这里，stop_recording 时读
  window.__apaasRec = window.__apaasRec || null;

  // ─────────────────────────── AI cursor visualizer (2026-05-25) ───────────────────────────
  // 让用户看到 agent 操作时的鼠标移动+点击效果. fixed 浮层 z-index 顶天, 每帧独立 (content
  // script 在 iframe 自己也跑, 操作哪帧 cursor 就在哪帧浮).
  // - click: cursor 滑到目标 (320ms cubic-bezier) → ripple 涟漪 → 真 click → 800ms 后 fade
  // - type:  cursor 滑到目标 → 显示 "AI 输入中…" 小气泡 → setNativeValue → fade
  // - press_key (uid 不空): brief pulse on target
  const CURSOR_ID = "__apaasCursorOverlay";
  const RIPPLE_STYLE_ID = "__apaasCursorStyles";
  const SLIDE_MS = 320;
  const FADE_MS = 220;
  const HOLD_AFTER_CLICK_MS = 600;

  function ensureCursorStyles() {
    if (document.getElementById(RIPPLE_STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = RIPPLE_STYLE_ID;
    style.textContent = `
      @keyframes __apaasRipple {
        0%   { transform: translate(-50%, -50%) scale(0.3); opacity: 0.85; }
        80%  { transform: translate(-50%, -50%) scale(2.6); opacity: 0.15; }
        100% { transform: translate(-50%, -50%) scale(3.2); opacity: 0; }
      }
      @keyframes __apaasPulse {
        0%   { box-shadow: 0 0 0 0 rgba(124, 58, 237, 0.55); }
        100% { box-shadow: 0 0 0 14px rgba(124, 58, 237, 0); }
      }
    `;
    document.head.appendChild(style);
  }

  function getOrCreateCursor() {
    let el = document.getElementById(CURSOR_ID);
    if (el) return el;
    ensureCursorStyles();
    el = document.createElement("div");
    el.id = CURSOR_ID;
    el.setAttribute("aria-hidden", "true");
    el.style.cssText = [
      "position: fixed",
      "width: 18px",
      "height: 18px",
      "left: 50vw",
      "top: 50vh",
      "pointer-events: none",
      "z-index: 2147483647",
      // 紫色 AI 风格 cursor (类似 macOS 箭头剪影的圆点)
      "background: radial-gradient(circle at 32% 32%, #c4b5fd 0%, #7c3aed 60%, #5b21b6 100%)",
      "border: 1.5px solid white",
      "border-radius: 50% 50% 50% 0%",
      "box-shadow: 0 4px 14px rgba(124, 58, 237, 0.45), 0 0 0 1px rgba(0,0,0,0.08)",
      "opacity: 0",
      "transform-origin: top left",
      `transition: left ${SLIDE_MS}ms cubic-bezier(0.4, 0, 0.2, 1), top ${SLIDE_MS}ms cubic-bezier(0.4, 0, 0.2, 1), opacity ${FADE_MS}ms, transform 180ms`,
    ].join(";");
    (document.body || document.documentElement).appendChild(el);
    return el;
  }

  function getTargetPoint(el) {
    const rect = el.getBoundingClientRect();
    // 点击的"逻辑命中点": 不要正中央 (有些 control 中心被 child 元素覆盖), 偏向左上偏移一点
    const x = Math.max(0, Math.min(window.innerWidth - 4, rect.left + Math.min(rect.width / 2, 28)));
    const y = Math.max(0, Math.min(window.innerHeight - 4, rect.top + Math.min(rect.height / 2, 14)));
    return { x, y };
  }

  function spawnRipple(x, y) {
    ensureCursorStyles();
    const r = document.createElement("div");
    r.setAttribute("aria-hidden", "true");
    r.style.cssText = [
      "position: fixed",
      `left: ${x}px`,
      `top: ${y}px`,
      "width: 22px",
      "height: 22px",
      "border-radius: 50%",
      "background: rgba(124, 58, 237, 0.45)",
      "border: 1.5px solid rgba(196, 181, 253, 0.8)",
      "pointer-events: none",
      "z-index: 2147483646",
      "transform: translate(-50%, -50%) scale(0.3)",
      "animation: __apaasRipple 520ms ease-out forwards",
    ].join(";");
    (document.body || document.documentElement).appendChild(r);
    setTimeout(() => { try { r.remove(); } catch (_) {} }, 700);
  }

  function spawnTypingBubble(x, y, text) {
    const b = document.createElement("div");
    b.setAttribute("aria-hidden", "true");
    b.style.cssText = [
      "position: fixed",
      `left: ${x + 14}px`,
      `top: ${y - 28}px`,
      "padding: 4px 10px",
      "font: 600 11px/1.4 -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif",
      "color: white",
      "background: linear-gradient(135deg, #7c3aed, #5b21b6)",
      "border-radius: 10px 10px 10px 2px",
      "box-shadow: 0 4px 12px rgba(124,58,237,0.4)",
      "pointer-events: none",
      "z-index: 2147483646",
      "opacity: 0",
      "transform: translateY(4px)",
      "transition: opacity 180ms, transform 180ms",
      "max-width: 240px",
      "overflow: hidden",
      "text-overflow: ellipsis",
      "white-space: nowrap",
    ].join(";");
    b.textContent = "✦ AI " + (text || "操作中") + "…";
    (document.body || document.documentElement).appendChild(b);
    // 触发 transition
    requestAnimationFrame(() => {
      b.style.opacity = "1";
      b.style.transform = "translateY(0)";
    });
    return b;
  }

  function moveCursorTo(el) {
    const cursor = getOrCreateCursor();
    const { x, y } = getTargetPoint(el);
    cursor.style.opacity = "1";
    cursor.style.left = x + "px";
    cursor.style.top = y + "px";
    return { cursor, x, y };
  }

  function fadeCursor(after = HOLD_AFTER_CLICK_MS) {
    setTimeout(() => {
      const cursor = document.getElementById(CURSOR_ID);
      if (cursor) cursor.style.opacity = "0";
    }, after);
  }

  // 视觉点击: cursor 滑入 (SLIDE_MS) → ripple + 真 click → fade
  function visualClick(el, done) {
    try { el.scrollIntoView({ block: "center", inline: "nearest" }); } catch (_) {}
    const { x, y } = moveCursorTo(el);
    setTimeout(() => {
      spawnRipple(x, y);
      try { el.click(); } catch (_) {}
      fadeCursor(HOLD_AFTER_CLICK_MS);
      done();
    }, SLIDE_MS + 20);
  }

  // 视觉输入: cursor 滑入 → typing 气泡 → setNativeValue → 气泡淡出
  function visualType(el, text, done) {
    try { el.scrollIntoView({ block: "center", inline: "nearest" }); } catch (_) {}
    const { x, y } = moveCursorTo(el);
    setTimeout(() => {
      el.focus();
      const proto = Object.getPrototypeOf(el);
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      const previewText = (text || "").length > 12
        ? `输入 "${(text || "").slice(0, 10)}…"`
        : `输入 "${text || ""}"`;
      const bubble = spawnTypingBubble(x, y, previewText);
      if (setter) {
        setter.call(el, text || "");
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        el.value = text || "";
      }
      setTimeout(() => {
        if (bubble) {
          bubble.style.opacity = "0";
          setTimeout(() => { try { bubble.remove(); } catch (_) {} }, 220);
        }
      }, 700);
      fadeCursor(900);
      done();
    }, SLIDE_MS + 20);
  }

  // 视觉按键: 仅在 uid 给了时定位; 否则直接干
  function visualPressKey(el, runKey, done) {
    if (!el) { runKey(); done(); return; }
    moveCursorTo(el);
    // pulse 一下当前 cursor 表示按下
    setTimeout(() => {
      const cursor = document.getElementById(CURSOR_ID);
      if (cursor) {
        cursor.style.animation = "__apaasPulse 320ms ease-out";
        setTimeout(() => { if (cursor) cursor.style.animation = ""; }, 340);
      }
      runKey();
      fadeCursor(700);
      done();
    }, Math.min(SLIDE_MS, 220));
  }

  function summarizeElement(el) {
    if (!el) return null;
    return {
      tag: el.tagName,
      text: (el.innerText || el.value || "").slice(0, 60),
      id: el.id || null,
      cls: (el.className || "").slice(0, 80),
      role: el.getAttribute && el.getAttribute("role"),
      type: el.getAttribute && el.getAttribute("type"),
      placeholder: el.getAttribute && el.getAttribute("placeholder"),
      ariaLabel: el.getAttribute && el.getAttribute("aria-label"),
      // CSS selector hint (best-effort)
      selector: buildSelector(el),
    };
  }

  function buildSelector(el) {
    if (!el || el === document.body) return "body";
    if (el.id) return `#${el.id}`;
    // 尝试构建一个 unique-ish 选择器
    const parts = [];
    let cur = el;
    while (cur && cur.tagName && parts.length < 5) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) { part += `#${cur.id}`; parts.unshift(part); break; }
      if (cur.className && typeof cur.className === "string") {
        const cls = cur.className.split(/\s+/).filter(Boolean).slice(0, 2).join(".");
        if (cls) part += `.${cls}`;
      }
      const sibIdx = Array.from(cur.parentNode?.children || []).indexOf(cur);
      if (sibIdx >= 0) part += `:nth-child(${sibIdx + 1})`;
      parts.unshift(part);
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  }

  // ─────────────────────────── snapshot (轻量 a11y-like tree) ───────────────────────────

  function uid() { return "u" + Math.random().toString(36).slice(2, 8); }

  function buildSnapshotNode(el, depth = 0, maxDepth = 30, count = { n: 0 }) {
    if (count.n > 400) return null; // 限 400 节点防爆
    if (!el || depth > maxDepth) return null;
    if (el.nodeType !== 1) return null;
    const style = el.ownerDocument && el.ownerDocument.defaultView
      ? el.ownerDocument.defaultView.getComputedStyle(el)
      : null;
    if (style && (style.display === "none" || style.visibility === "hidden")) return null;
    const tag = el.tagName;
    const interesting = ["BUTTON", "A", "INPUT", "TEXTAREA", "SELECT", "LABEL", "H1", "H2", "H3", "H4", "DIALOG", "NAV", "HEADER", "MAIN", "ASIDE"];
    const role = el.getAttribute && el.getAttribute("role");
    const isInteresting =
      interesting.includes(tag) ||
      (role && ["button", "link", "tab", "tabpanel", "textbox", "checkbox", "menu", "menuitem", "dialog", "navigation"].includes(role)) ||
      (el.onclick || el.getAttribute("onclick"));

    const myUid = uid();
    el.setAttribute && el.setAttribute("data-apaas-uid", myUid);
    count.n += 1;

    const node = {
      uid: myUid,
      tag,
      role,
      text: (el.innerText || el.value || "").trim().slice(0, 80),
      placeholder: el.getAttribute && el.getAttribute("placeholder") || null,
      ariaLabel: el.getAttribute && el.getAttribute("aria-label") || null,
      type: el.getAttribute && el.getAttribute("type") || null,
      checked: el.checked,
      value: typeof el.value === "string" ? el.value.slice(0, 60) : null,
      visible: true,
      interesting: !!isInteresting,
      children: [],
    };
    for (const child of el.children) {
      const cn = buildSnapshotNode(child, depth + 1, maxDepth, count);
      if (cn) node.children.push(cn);
    }
    // 没 interesting 子节点 且自身不 interesting 且没文字 — 跳过自己（向上 promote 子节点）
    if (!isInteresting && !node.text && node.children.length === 0) return null;
    return node;
  }

  function makeSnapshot() {
    // 每次 snapshot 前清理上一轮的 data-apaas-uid, 避免 uid 累积污染 DOM
    try {
      document.querySelectorAll("[data-apaas-uid]").forEach((el) => el.removeAttribute("data-apaas-uid"));
    } catch (_) { /* ignore */ }
    const root = buildSnapshotNode(document.body, 0, 30, { n: 0 });
    return {
      url: location.href,
      title: document.title,
      // 2026-05-25: 给 backend frame 路由用 — 标识本 frame 是不是 top
      is_top_frame: window.top === window,
      root,
    };
  }

  function findByUid(uid) {
    return document.querySelector(`[data-apaas-uid="${uid}"]`);
  }

  // 2026-05-25: press_key / wait_for_text — 让 AI 能触发回车/Tab/ESC + 等异步渲染
  function pressKey(args) {
    const key = String(args.key || "").trim();
    if (!key) return { ok: false, error_code: "INVALID_KEY", message: "key 必填" };
    let target = null;
    if (args.uid) {
      target = findByUid(args.uid);
      if (!target) return { ok: false, error_code: "ELEM_NOT_FOUND", args };
      try { target.focus(); } catch (_) { /* ignore */ }
    } else {
      target = document.activeElement || document.body;
    }
    // 常用 key → keyCode 映射（dispatch KeyboardEvent 时要给 code/keyCode 兼容老逻辑）
    const map = {
      Enter:      { code: "Enter",      keyCode: 13 },
      Tab:        { code: "Tab",        keyCode: 9 },
      Escape:     { code: "Escape",     keyCode: 27 },
      Esc:        { code: "Escape",     keyCode: 27 },
      ArrowDown:  { code: "ArrowDown",  keyCode: 40 },
      ArrowUp:    { code: "ArrowUp",    keyCode: 38 },
      ArrowLeft:  { code: "ArrowLeft",  keyCode: 37 },
      ArrowRight: { code: "ArrowRight", keyCode: 39 },
      Backspace:  { code: "Backspace",  keyCode: 8 },
      Delete:     { code: "Delete",     keyCode: 46 },
      Space:      { code: "Space",      keyCode: 32 },
      " ":        { code: "Space",      keyCode: 32 },
    };
    const m = map[key] || { code: key, keyCode: 0 };
    for (const evType of ["keydown", "keypress", "keyup"]) {
      try {
        const ev = new KeyboardEvent(evType, {
          key, code: m.code, keyCode: m.keyCode, which: m.keyCode,
          bubbles: true, cancelable: true,
        });
        target.dispatchEvent(ev);
      } catch (_) { /* ignore */ }
    }
    return { ok: true, key, target_tag: target && target.tagName };
  }

  async function waitForText(args) {
    const text = String(args.text || "");
    if (!text) return { ok: false, error_code: "INVALID_TEXT", message: "text 必填" };
    const timeout = Math.max(100, Math.min(30000, Number(args.timeout_ms) || 5000));
    const start = Date.now();
    // 200ms 轮询; 命中即返
    while (Date.now() - start < timeout) {
      const body = (document.body && document.body.innerText) || "";
      if (body.includes(text)) {
        return { ok: true, text, elapsed_ms: Date.now() - start };
      }
      await new Promise((r) => setTimeout(r, 200));
    }
    return {
      ok: false,
      error_code: "WAIT_TIMEOUT",
      message: `等 ${timeout}ms 没出现文本「${text.slice(0, 60)}」`,
      elapsed_ms: Date.now() - start,
    };
  }

  // ─────────────────────────── recording ───────────────────────────

  function startRecording() {
    if (window.__apaasRec) {
      // already
      window.__apaasRec.length = 0;
      return { ok: true, status: "reset" };
    }
    window.__apaasRec = [];
    const log = window.__apaasRec;
    const clickHandler = (e) => {
      log.push({ type: "click", time: Date.now(), target: summarizeElement(e.target), url: location.href });
    };
    const changeHandler = (e) => {
      log.push({ type: "change", time: Date.now(), target: summarizeElement(e.target), value: (e.target.value || "").slice(0, 80), url: location.href });
    };
    const inputDebounce = {};
    const inputHandler = (e) => {
      const t = e.target;
      const k = (t.id || t.name || t.placeholder || "anon") + "@" + location.href;
      if (inputDebounce[k]) clearTimeout(inputDebounce[k]);
      inputDebounce[k] = setTimeout(() => {
        log.push({ type: "input", time: Date.now(), target: summarizeElement(t), value: (t.value || "").slice(0, 80), url: location.href });
      }, 500);
    };
    document.addEventListener("click", clickHandler, true);
    document.addEventListener("change", changeHandler, true);
    document.addEventListener("input", inputHandler, true);
    window.__apaasRecHandlers = { clickHandler, changeHandler, inputHandler };
    return { ok: true, status: "started" };
  }

  function stopRecording() {
    const log = window.__apaasRec || [];
    const handlers = window.__apaasRecHandlers || {};
    if (handlers.clickHandler) document.removeEventListener("click", handlers.clickHandler, true);
    if (handlers.changeHandler) document.removeEventListener("change", handlers.changeHandler, true);
    if (handlers.inputHandler) document.removeEventListener("input", handlers.inputHandler, true);
    window.__apaasRec = null;
    window.__apaasRecHandlers = null;
    return { ok: true, count: log.length, events: log };
  }

  // ─────────────────────────── command exec ───────────────────────────

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "exec") {
      const { cmd, args } = msg;
      try {
        if (cmd === "snapshot") {
          sendResponse(makeSnapshot());
          return false;
        }
        if (cmd === "click") {
          const el = args.selector ? document.querySelector(args.selector)
            : args.uid ? findByUid(args.uid) : null;
          if (!el) {
            sendResponse({ ok: false, error_code: "ELEM_NOT_FOUND", args, frame_url: location.href });
            return false;
          }
          // 2026-05-25: 异步走 visual 流程 (cursor 滑动 + ripple), 完事再 sendResponse
          visualClick(el, () => {
            try {
              sendResponse({ ok: true, clicked: summarizeElement(el), frame_url: location.href });
            } catch (_) { /* channel 可能已关 */ }
          });
          return true;
        }
        if (cmd === "type") {
          const el = args.selector ? document.querySelector(args.selector)
            : args.uid ? findByUid(args.uid) : null;
          if (!el) {
            sendResponse({ ok: false, error_code: "ELEM_NOT_FOUND", args, frame_url: location.href });
            return false;
          }
          // 2026-05-25: 异步走 visual 流程 (cursor 滑动 + typing 气泡)
          visualType(el, args.text || "", () => {
            try {
              sendResponse({ ok: true, typed: args.text, target: summarizeElement(el), frame_url: location.href });
            } catch (_) {}
          });
          return true;
        }
        if (cmd === "press_key") {
          // press_key: 如果 uid 给了, cursor 滑过去 + pulse, 然后再 dispatch keyboard event
          let target = null;
          if (args && args.uid) {
            target = findByUid(args.uid);
            if (!target) {
              sendResponse({ ok: false, error_code: "ELEM_NOT_FOUND", args, frame_url: location.href });
              return false;
            }
          }
          let resPayload = null;
          visualPressKey(
            target,
            () => { resPayload = pressKey(args || {}); },  // runKey: 真派发键盘事件
            () => {
              try {
                sendResponse({ ...(resPayload || { ok: true }), frame_url: location.href });
              } catch (_) {}
            },
          );
          return true;
        }
        if (cmd === "wait_for_text") {
          // 异步: 返 true 让 channel 保持开放, 等 waitForText 完成再 sendResponse
          waitForText(args || {})
            .then((res) => { try { sendResponse({ ...res, frame_url: location.href }); } catch (_) {} })
            .catch((e) => {
              try { sendResponse({ ok: false, error: String(e && e.message || e), frame_url: location.href }); } catch (_) {}
            });
          return true;
        }
        if (cmd === "evaluate") {
          // 在 page world 没法直接跑 (隔离 world)，只能跑 content script 上下文里的 expression。
          // POC 阶段：限定纯 DOM 查询 + Function 字符串构造（生产要 sandbox 限制）。
          try {
            // eslint-disable-next-line no-new-func
            const fn = new Function("return (" + (args.code || "() => null") + ")()");
            const result = fn();
            sendResponse({ ok: true, result });
          } catch (e) {
            sendResponse({ ok: false, error: String(e) });
          }
          return false;
        }
        if (cmd === "start_recording") {
          sendResponse(startRecording());
          return false;
        }
        if (cmd === "stop_recording") {
          sendResponse(stopRecording());
          return false;
        }
        if (cmd === "screenshot") {
          // content script 拿不到 viewport capture — 让 background 用 chrome.tabs.captureVisibleTab 处理
          sendResponse({ ok: false, error_code: "DELEGATE_TO_BG", message: "background.js 用 captureVisibleTab" });
          return false;
        }
        sendResponse({ ok: false, error_code: "UNKNOWN_CMD", cmd });
      } catch (e) {
        sendResponse({ ok: false, error: String(e && e.message || e), stack: String(e && e.stack || "") });
      }
    }
    return false;
  });
})();
