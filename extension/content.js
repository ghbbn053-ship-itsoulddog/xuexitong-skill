chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  handleCommand(msg.method, msg.params || {})
    .then((result) => sendResponse({ result: result ?? null }))
    .catch((err) => sendResponse({ error: String(err.message || err) }));
  return true;
});

async function handleCommand(method, params) {
  switch (method) {
    case "frame_snapshot":
      return frameSnapshot(params.selector);
    case "frame_evaluate":
      return frameEvaluate(params.selector, params.expression);
    case "has_element":
      return hasElement(params.selector);
    case "get_element_text":
      return getElementText(params.selector);
    case "get_element_attribute":
      return getElementAttribute(params.selector, params.attr);
    case "query_elements":
      return queryElements(params.selector, params.limit, params.attrs);
    case "get_url":
      return window.location.href;
    case "click_element":
      return clickElement(params.selector);
    case "input_text":
      return inputText(params.selector, params.text);
    default:
      throw new Error(`未知命令: ${method}`);
  }
}

function clickElement(selector) {
  const el = document.querySelector(selector);
  if (!el) {
    throw new Error(`元素不存在: ${selector}`);
  }
  el.scrollIntoView({ block: "center" });
  el.click();
  return null;
}

function inputText(selector, text) {
  const el = document.querySelector(selector);
  if (!el) {
    throw new Error(`元素不存在: ${selector}`);
  }
  el.focus();
  el.value = text;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return null;
}

function hasElement(selector) {
  return document.querySelector(selector) !== null;
}

function getElementText(selector) {
  const el = document.querySelector(selector);
  return el ? el.textContent : null;
}

function getElementAttribute(selector, attr) {
  const el = document.querySelector(selector);
  return el ? el.getAttribute(attr) : null;
}

function frameSnapshot(selector) {
  const frame = document.querySelector(selector);
  if (!frame) {
    return { exists: false, selector };
  }
  const frameWindow = frame.contentWindow || null;
  const frameDocument = frame.contentDocument || (frameWindow ? frameWindow.document : null);
  if (!frameDocument) {
    return {
      exists: true,
      accessible: false,
      selector
    };
  }
  return {
    exists: true,
    accessible: true,
    selector,
    url: frameWindow ? frameWindow.location.href : null,
    title: frameDocument.title || null,
    readyState: frameDocument.readyState || null,
    bodyText: ((frameDocument.body && frameDocument.body.innerText) || "").slice(0, 1200),
    courseItems: frameDocument.querySelectorAll("#courseList li.course").length,
    hasCourseList: !!frameDocument.querySelector("#courseList"),
    frameCount: frameDocument.querySelectorAll("iframe").length
  };
}

function frameEvaluate(selector, expression) {
  const frame = document.querySelector(selector);
  if (!frame) {
    throw new Error(`iframe不存在: ${selector}`);
  }
  const frameWindow = frame.contentWindow || null;
  const frameDocument = frame.contentDocument || (frameWindow ? frameWindow.document : null);
  if (!frameDocument) {
    throw new Error(`iframe不可访问: ${selector}`);
  }
  // new Function() is blocked by strict CSP (no unsafe-eval).
  // If it throws, we tag the error with [CSP_BLOCKED] so background.js
  // can detect it and fall back to chrome.debugger, which bypasses CSP.
  try {
    return new Function(
      "frameWindow",
      "frameDocument",
      `"use strict"; return (${expression});`
    )(frameWindow, frameDocument);
  } catch (e) {
    // CSP blocked new Function() — throw a recognizable error so background.js
    // can detect it and fall back to the debugger (chrome.debugger) path.
    const msg = String(e && e.message ? e.message : e);
    throw new Error(`[CSP_BLOCKED] frameEvaluate failed: ${msg}`);
  }
}

function queryElements(selector, limit = 20, attrs = []) {
  const max = Math.max(1, Math.min(limit || 20, 200));
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  return Array.from(document.querySelectorAll(selector)).slice(0, max).map((el, index) => {
    const pickedAttrs = {};
    for (const name of attrs || []) {
      pickedAttrs[name] = el.getAttribute(name);
    }
    return {
      index,
      tag: el.tagName,
      id: el.id || null,
      className: typeof el.className === "string" ? el.className : null,
      text: clean(el.textContent || "").slice(0, 300),
      attrs: pickedAttrs,
    };
  });
}
