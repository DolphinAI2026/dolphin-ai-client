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
    const root = buildSnapshotNode(document.body, 0, 30, { n: 0 });
    return {
      url: location.href,
      title: document.title,
      root,
    };
  }

  function findByUid(uid) {
    return document.querySelector(`[data-apaas-uid="${uid}"]`);
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

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
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
            sendResponse({ ok: false, error_code: "ELEM_NOT_FOUND", args });
            return false;
          }
          try { el.scrollIntoView({ block: "center" }); } catch {}
          el.click();
          sendResponse({ ok: true, clicked: summarizeElement(el) });
          return false;
        }
        if (cmd === "type") {
          const el = args.selector ? document.querySelector(args.selector)
            : args.uid ? findByUid(args.uid) : null;
          if (!el) {
            sendResponse({ ok: false, error_code: "ELEM_NOT_FOUND", args });
            return false;
          }
          el.focus();
          const proto = Object.getPrototypeOf(el);
          const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
          if (setter) {
            setter.call(el, args.text || "");
            el.dispatchEvent(new Event("input", { bubbles: true }));
            el.dispatchEvent(new Event("change", { bubbles: true }));
          } else {
            el.value = args.text || "";
          }
          sendResponse({ ok: true, typed: args.text, target: summarizeElement(el) });
          return false;
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
