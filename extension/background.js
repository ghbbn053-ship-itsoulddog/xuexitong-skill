const BRIDGE_URL = "ws://localhost:9333";
let ws = null;
let lastKnownTabId = null;

chrome.alarms.create("keepAlive", { periodInMinutes: 2 });
chrome.alarms.create("wsPing", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "wsPing") {
    // 保持 WebSocket 不闲置断开
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ ping: true })); } catch (_) {}
    }
    return;
  }
  if (!ws || ws.readyState !== WebSocket.OPEN) connect();
});

connect();

function connect() {
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
    return;
  }

  ws = new WebSocket(BRIDGE_URL);

  ws.onopen = () => {
    ws.send(JSON.stringify({ role: "extension" }));
  };

  ws.onmessage = async (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }

    try {
      const result = await handleCommand(msg);
      ws.send(JSON.stringify({ id: msg.id, result: result ?? null }));
    } catch (err) {
      ws.send(JSON.stringify({ id: msg.id, error: String(err.message || err) }));
    }
  };

  ws.onclose = () => {
    setTimeout(connect, 3000);
  };
}

async function handleCommand(msg) {
  const { method, params = {} } = msg;

  switch (method) {
    case "navigate":
      return await cmdNavigate(params);
    case "wait_for_load":
      return await cmdWaitForLoad(params);
    case "debug_tabs":
      return await cmdDebugTabs();
    case "evaluate":
      return await cmdDom(method, params);
    case "frame_snapshot":
    case "frame_evaluate":
      return await cmdDom(method, params);
    case "has_element":
    case "get_element_text":
    case "get_element_attribute":
    case "query_elements":
    case "get_url":
      return await cmdDom(method, params);
    default:
      return await cmdDom(method, params);
  }
}

async function getActiveTab() {
  if (lastKnownTabId !== null) {
    const knownTab = await chrome.tabs.get(lastKnownTabId).catch(() => null);
    if (knownTab && knownTab.url && /chaoxing|edu\.cn/.test(knownTab.url)) {
      return knownTab;
    }
  }

  const activeTabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const activeTarget = activeTabs.find((tab) => tab.url && /chaoxing|edu\.cn/.test(tab.url));
  if (activeTarget) {
    lastKnownTabId = activeTarget.id;
    return activeTarget;
  }

  const tabs = await chrome.tabs.query({});
  const candidates = tabs
    .filter((tab) => tab.url && /chaoxing|edu\.cn/.test(tab.url))
    .sort((a, b) => (b.id || 0) - (a.id || 0));
  const fallback = candidates[0];
  if (!fallback) {
    throw new Error("未找到学习站标签页");
  }
  lastKnownTabId = fallback.id;
  return fallback;
}

async function cmdNavigate({ url }) {
  const tab = await getActiveTab();
  await chrome.tabs.update(tab.id, { url });
  lastKnownTabId = tab.id;
  return null;
}

async function cmdWaitForLoad({ timeout = 30000 }) {
  const tab = await getActiveTab();
  await waitForTabComplete(tab.id, timeout);
  return null;
}

async function cmdDebugTabs() {
  const tabs = await chrome.tabs.query({});
  return tabs
    .filter((tab) => tab.url && /chaoxing|edu\.cn/.test(tab.url))
    .map((tab) => ({
      id: tab.id,
      active: tab.active,
      status: tab.status,
      title: tab.title || null,
      url: tab.url || null
    }));
}

function waitForTabComplete(tabId, timeout) {
  return new Promise((resolve, reject) => {
    const end = Date.now() + timeout;

    function check() {
      chrome.tabs.get(tabId).then((tab) => {
        if (tab.status === "complete") {
          resolve();
          return;
        }
        if (Date.now() > end) {
          reject(new Error("页面加载超时"));
          return;
        }
        setTimeout(check, 300);
      }).catch(reject);
    }

    check();
  });
}

async function cmdDom(method, params) {
  const tab = await getActiveTab();

  try {
    const response = await chrome.tabs.sendMessage(tab.id, { method, params }, { frameId: 0 });
    if (response?.error) {
      throw new Error(response.error);
    }
    return response?.result ?? null;
  } catch (err) {
    const msg = String(err && err.message ? err.message : err);
    if (
      msg.includes("Blocked") ||
      msg.includes("Receiving end does not exist") ||
      msg.includes("未知命令") ||
      msg.includes("CSP_BLOCKED") ||
      msg.includes("unsafe-eval") ||
      msg.includes("Content Security Policy") ||
      msg.includes("Refused to evaluate")
    ) {
      return await cmdDomViaDebugger(tab.id, method, params);
    }
    throw err;
  }
}

async function cmdDomViaDebugger(tabId, method, params) {
  await attachDebugger(tabId);
  try {
    const expression = buildDebuggerExpression(method, params);
    const result = await chrome.debugger.sendCommand(
      { tabId },
      "Runtime.evaluate",
      {
        expression,
        returnByValue: true,
        awaitPromise: true,
      },
    );
    const value = result?.result?.value;
    if (value && typeof value === "object" && value.__error) {
      throw new Error(value.__error);
    }
    return value ?? null;
  } finally {
    await detachDebugger(tabId);
  }
}

async function attachDebugger(tabId) {
  try {
    await chrome.debugger.attach({ tabId }, "1.3");
  } catch (err) {
    const msg = String(err && err.message ? err.message : err);
    if (!msg.includes("Another debugger is already attached")) {
      throw err;
    }
  }
}

async function detachDebugger(tabId) {
  try {
    await chrome.debugger.detach({ tabId });
  } catch {
    // ignore detach failures
  }
}

function buildDebuggerExpression(method, params) {
  switch (method) {
    case "evaluate":
      return params.expression;
    case "has_element":
      return `(() => document.querySelector(${JSON.stringify(params.selector)}) !== null)()`;
    case "get_element_text":
      return `(() => { const el = document.querySelector(${JSON.stringify(params.selector)}); return el ? el.textContent : null; })()`;
    case "get_element_attribute":
      return `(() => { const el = document.querySelector(${JSON.stringify(params.selector)}); return el ? el.getAttribute(${JSON.stringify(params.attr)}) : null; })()`;
    case "get_url":
      return "window.location.href";
    case "click_element":
      return `(() => { const el = document.querySelector(${JSON.stringify(params.selector)}); if (!el) return { __error: '元素不存在: ${escapeForError(params.selector)}' }; el.scrollIntoView({ block: 'center' }); el.click(); return null; })()`;
    case "input_text":
      return `(() => { const el = document.querySelector(${JSON.stringify(params.selector)}); if (!el) return { __error: '元素不存在: ${escapeForError(params.selector)}' }; el.focus(); el.value = ${JSON.stringify(params.text)}; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return null; })()`;
    case "query_elements":
      return `(() => {
        const selector = ${JSON.stringify(params.selector)};
        const limit = Math.max(1, Math.min(${JSON.stringify(params.limit || 20)}, 200));
        const attrNames = ${JSON.stringify(params.attrs || [])};
        const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
        return Array.from(document.querySelectorAll(selector)).slice(0, limit).map((el, index) => {
          const attrs = {};
          for (const name of attrNames) {
            attrs[name] = el.getAttribute(name);
          }
          return {
            index,
            tag: el.tagName,
            id: el.id || null,
            className: typeof el.className === 'string' ? el.className : null,
            text: clean(el.textContent || '').slice(0, 300),
            attrs
          };
        });
      })()`;
    case "frame_snapshot":
      return `(() => {
        const frame = document.querySelector(${JSON.stringify(params.selector)});
        if (!frame) return { exists: false, selector: ${JSON.stringify(params.selector)} };
        const frameWindow = frame.contentWindow || null;
        const frameDocument = frame.contentDocument || (frameWindow ? frameWindow.document : null);
        if (!frameDocument) return { exists: true, accessible: false, selector: ${JSON.stringify(params.selector)} };
        return {
          exists: true,
          accessible: true,
          selector: ${JSON.stringify(params.selector)},
          url: frameWindow ? frameWindow.location.href : null,
          title: frameDocument.title || null,
          readyState: frameDocument.readyState || null,
          bodyText: ((frameDocument.body && frameDocument.body.innerText) || '').slice(0, 1200),
          courseItems: frameDocument.querySelectorAll('#courseList li.course').length,
          hasCourseList: !!frameDocument.querySelector('#courseList'),
          frameCount: frameDocument.querySelectorAll('iframe').length
        };
      })()`;
    case "frame_evaluate":
      return `(() => {
        const frame = document.querySelector(${JSON.stringify(params.selector)});
        if (!frame) return { __error: 'iframe不存在: ${escapeForError(params.selector)}' };
        const frameWindow = frame.contentWindow || null;
        const frameDocument = frame.contentDocument || (frameWindow ? frameWindow.document : null);
        if (!frameDocument) return { __error: 'iframe不可访问: ${escapeForError(params.selector)}' };
        return (${params.expression});
      })()`;
    case "run_course":
      return `(typeof startAutoRun === 'function' ? startAutoRun(${JSON.stringify(params)}) : { error: 'content.js 未加载, 请刷新页面后重试' })`;
    case "request_pause":
      return `(typeof requestPause === 'function' ? (requestPause(), null) : null)`;
    case "get_study_status":
      return `(typeof getStudyStatus === 'function' ? getStudyStatus() : { active: false, url: window.location.href })`;
    default:
      return `(() => ({ __error: '未知命令: ${escapeForError(method)}' }))()`;
  }
}

function escapeForError(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

