// ===== XXT Bridge — 所有 DOM 操作均运行在 MAIN world =====
// 查询类命令: 响应 background.js 的 sendMessage
// 刷课逻辑: 从一键刷课扩展照搬, 在 MAIN world 内自循环

// ===== 消息监听 — 只在 chrome.runtime 可用时注册 =====
if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    handleCommand(msg.method, msg.params || {})
      .then((result) => sendResponse({ result: result ?? null }))
      .catch((err) => sendResponse({ error: String(err.message || err) }));
    return true;
  });
}

async function handleCommand(method, params) {
  switch (method) {
    // 查询类
    case "evaluate":
      return evaluate(params.expression);
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
    // 刷课控制
    case "run_course":
      return startAutoRun(params);
    case "request_pause":
      requestPause();
      return null;
    case "get_study_status":
      return getStudyStatus();
    default:
      throw new Error("未知命令: " + method);
  }
}

// ===== 查询辅助函数 =====

function evaluate(expression) {
  try {
    return new Function('"use strict"; return (' + expression + ');')();
  } catch (e) {
    var msg = String(e && e.message ? e.message : e);
    throw new Error("[CSP_BLOCKED] evaluate failed: " + msg);
  }
}

function clickElement(selector) {
  var el = document.querySelector(selector);
  if (!el) throw new Error("元素不存在: " + selector);
  el.scrollIntoView({ block: "center" });
  el.click();
  return null;
}

function inputText(selector, text) {
  var el = document.querySelector(selector);
  if (!el) throw new Error("元素不存在: " + selector);
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
  var el = document.querySelector(selector);
  return el ? el.textContent : null;
}

function getElementAttribute(selector, attr) {
  var el = document.querySelector(selector);
  return el ? el.getAttribute(attr) : null;
}

function frameSnapshot(selector) {
  var frame = document.querySelector(selector);
  if (!frame) return { exists: false, selector: selector };
  var fw = frame.contentWindow || null;
  var fd = frame.contentDocument || (fw ? fw.document : null);
  if (!fd) return { exists: true, accessible: false, selector: selector };
  return {
    exists: true, accessible: true, selector: selector,
    url: fw ? fw.location.href : null,
    title: fd.title || null,
    readyState: fd.readyState || null,
    bodyText: ((fd.body && fd.body.innerText) || "").slice(0, 1200),
    courseItems: fd.querySelectorAll("#courseList li.course").length,
    hasCourseList: !!fd.querySelector("#courseList"),
    frameCount: fd.querySelectorAll("iframe").length
  };
}

function frameEvaluate(selector, expression) {
  var frame = document.querySelector(selector);
  if (!frame) throw new Error("iframe不存在: " + selector);
  var fw = frame.contentWindow || null;
  var fd = frame.contentDocument || (fw ? fw.document : null);
  if (!fd) throw new Error("iframe不可访问: " + selector);
  try {
    return new Function("frameWindow", "frameDocument", '"use strict"; return (' + expression + ');')(fw, fd);
  } catch (e) {
    throw new Error("[CSP_BLOCKED] frameEvaluate failed: " + (e && e.message ? e.message : e));
  }
}

function queryElements(selector, limit, attrs) {
  var max = Math.max(1, Math.min(limit || 20, 200));
  var attrNames = Array.isArray(attrs) ? attrs : [];
  var clean = function(s) { return (s || "").replace(/\s+/g, " ").trim(); };
  return Array.from(document.querySelectorAll(selector)).slice(0, max).map(function(el, index) {
    var pickedAttrs = {};
    for (var i = 0; i < attrNames.length; i++) {
      pickedAttrs[attrNames[i]] = el.getAttribute(attrNames[i]);
    }
    return {
      index: index,
      tag: el.tagName,
      id: el.id || null,
      className: typeof el.className === "string" ? el.className : null,
      text: clean(el.textContent || "").slice(0, 300),
      attrs: pickedAttrs
    };
  });
}

// ================================================================
// 一键刷课逻辑 — 从 content-main.js 严格照搬, 全部运行在 MAIN world
// window.name 跨子域名持久化, 零动态注入, 零 CDP
// ================================================================

var AUTO_S = "__xxt_auto__";
function getAutoState() {
  try {
    if (window.name && window.name.indexOf(AUTO_S) === 0) return JSON.parse(window.name.slice(AUTO_S.length));
    var s = sessionStorage.getItem("__xxt_bridge_auto_state__");
    return s ? JSON.parse(s) : { active: false };
  } catch(e) { return { active: false }; }
}
function setAutoState(s) {
  try { window.name = AUTO_S + JSON.stringify(s); sessionStorage.setItem("__xxt_bridge_auto_state__", JSON.stringify(s)); } catch(e) {}
}
function clearAutoState() { window.name = ""; try { sessionStorage.removeItem("__xxt_bridge_auto_state__"); } catch(e) {} }

var _sleep = function(ms) { return new Promise(function(r) { setTimeout(r, ms); }); };
var _log = function(msg) { console.log("[XXT刷课] " + msg); };

function getAllNestedIframes(element) {
  var result = [];
  var iframes = Array.from(element.querySelectorAll("iframe"));
  for (var i = 0; i < iframes.length; i++) {
    result.push(iframes[i]);
    try {
      if (iframes[i].contentDocument) {
        var nested = getAllNestedIframes(iframes[i].contentDocument.documentElement);
        for (var j = 0; j < nested.length; j++) { result.push(nested[j]); }
      }
    } catch(e) {}
  }
  return result;
}

function waitIframeLoad(iframe) {
  return new Promise(function(resolve) {
    var id = setInterval(function() {
      if (iframe.contentDocument && iframe.contentDocument.readyState === "complete") { clearInterval(id); resolve(); }
    }, 500);
  });
}

function processMedia(mediaType, iframeDocument) {
  return new Promise(function(resolve) {
    _log("发现 " + mediaType + ", 播放中");
    var done = false;
    var id = setInterval(function() {
      var el = iframeDocument.documentElement.querySelector(mediaType);
      if (el && !done) {
        el.pause(); el.muted = true; el.play();
        var onPause = function() { _sleep(3).then(function() { el.play(); }); };
        el.addEventListener("pause", onPause);
        el.addEventListener("ended", function() {
          _log(mediaType + " 播放完成");
          el.removeEventListener("pause", onPause);
          clearInterval(id);
          resolve();
        });
        done = true;
        clearInterval(id);
      }
    }, 2500);
  });
}

async function processPpt(iframeWindow) {
  _log("发现 PPT, 阅读中");
  var pw = iframeWindow.document.querySelector("#panView").contentWindow;
  pw.scrollTo({ top: pw.document.body.scrollHeight, behavior: "smooth" });
  _log("阅读完成");
}

async function processBook(iframeWindow) {
  _log("发现电子书, 阅读中");
  window.top.onchangepage(iframeWindow.getFrameAttr("end"));
  _log("阅读完成");
}

async function processWork(iframe, iframeDocument, iframeWindow) {
  if (!iframeDocument) return;
  var txt = (iframeDocument.documentElement.innerText || "");
  if (txt.indexOf("已完成") !== -1 || txt.indexOf("待批阅") !== -1) { _log("答题已完成"); return; }
  var pc = (iframe.parentElement && iframe.parentElement.className) || "";
  if (pc.indexOf("ans-job-finished") !== -1) { _log("任务已完成"); return; }

  _log("检测到答题, 调用 noSubmit 暂存跳过");
  iframeWindow.alert = function() {};
  try {
    if (typeof iframeWindow.noSubmit === "function") {
      await iframeWindow.noSubmit();
      _log("noSubmit 成功");
    } else {
      _log("noSubmit 不可用, 尝试 btnBlueSubmit");
      if (typeof iframeWindow.btnBlueSubmit === "function") await iframeWindow.btnBlueSubmit();
    }
  } catch(e) {
    _log("平台函数调用失败: " + (e && e.message ? e.message : e));
    try {
      var docEl = document.documentElement;
      var cardIfr = docEl.querySelector('iframe[info="card"], #iframe[info="card"]');
      if (cardIfr) {
        var src = cardIfr.getAttribute("src") || cardIfr.src || "";
        var u = new URL(src, location.href);
        var cur = parseInt(u.searchParams.get("num") || "0");
        u.searchParams.set("num", String(cur > 0 ? cur + 1 : 2));
        cardIfr.src = u.toString();
        _log("num+1 跳转: " + cur + " -> " + (cur + 1));
      }
    } catch(e2) {}
  }
}

async function processIframe(iframe) {
  var iframeSrc = iframe.src;
  var iframeDocument = iframe.contentDocument;
  var iframeWindow = iframe.contentWindow;
  if (!iframeDocument || !iframeWindow) return;
  if (iframeSrc.indexOf("javascript:") === 0) return;
  await waitIframeLoad(iframe);

  var parentClass = (iframe.parentElement && iframe.parentElement.className) || "";
  if (parentClass.indexOf("ans-job-finished") !== -1) {
    _log("已完成任务点");
  } else {
    if (iframeSrc.indexOf("api/work") !== -1) {
      return processWork(iframe, iframeDocument, iframeWindow);
    }
    var ansJobIcon = iframe.parentElement && iframe.parentElement.querySelector(".ans-job-icon");
    if (ansJobIcon) {
      if (iframeSrc.indexOf("video") !== -1) return processMedia("video", iframeDocument);
      else if (iframeSrc.indexOf("audio") !== -1) return processMedia("audio", iframeDocument);
      else if (["ppt","doc","pptx","docx","pdf"].some(function(t) { return iframeSrc.indexOf("modules/" + t) !== -1; })) return processPpt(iframeWindow);
      else if (["innerbook"].some(function(t) { return iframeSrc.indexOf("modules/" + t) !== -1; })) return processBook(iframeWindow);
    }
  }
}

var _currentWatchIframeTaskId = 0;
var __interceptorId = null;

function useCxChapterLogic() {
  var currentUrl = window.location.href;
  if (currentUrl.indexOf("&mooc2=1") === -1) {
    _log("添加 mooc2=1 参数");
    window.location.href = currentUrl + "&mooc2=1";
    return;
  }
  _log("进入章节学习页面, 正在解析任务点...");

  function processIframeTask() {
    var docEl = document.documentElement;
    var iframe = docEl.querySelector("iframe");
    if (!iframe) { _log("No iframe found."); return; }
    watchIframe(docEl);
    iframe.addEventListener("load", function() { watchIframe(docEl); });
  }

  function setupInterceptor() {
    if (__interceptorId) return;
    var curUrl = window.location.href;
    __interceptorId = setInterval(function() {
      if (curUrl !== window.location.href) {
        curUrl = window.location.href;
        processIframeTask();
      }
    }, 2000);
  }

  async function watchIframe(docEl) {
    var thisTaskId = ++_currentWatchIframeTaskId;
    var allIframes = getAllNestedIframes(docEl);
    _log("找到 " + allIframes.length + " 个 iframe");
    for (var i = 0; i < allIframes.length; i++) {
      var st = getAutoState();
      if (!st || !st.active) return;
      await processIframe(allIframes[i]);
    }
    if (thisTaskId === _currentWatchIframeTaskId) {
      var st2 = getAutoState();
      if (!st2 || !st2.active) return;
      _log("本页任务点全部完成，前往下一章节");
      var nextBtn = docEl.querySelector("#prevNextFocusNext");
      if (!nextBtn || nextBtn.style.display === "none") {
        _log("已到达最后一章，无法跳转");
        var st3 = getAutoState();
        if (st3) { st3.active = false; setAutoState(st3); }
      } else {
        await _sleep(3);
        var chapterBtn = document.querySelector(".jb_btn.jb_btn_92.fr.fs14.nextChapter");
        if (chapterBtn) { chapterBtn.click(); _log("点击下一章"); }
        else { _log("未找到下一章按钮"); }
      }
    }
  }

  processIframeTask();
  setupInterceptor();
}

function handleStandaloneWork() {
  _log("答题/考试页, 尝试返回");
  var btn = document.querySelector("#prevNextFocusNext,.nextChapter");
  if (btn && btn.style.display !== "none") { btn.click(); return; }
  _log("无可用按钮, 返回上一页");
  history.back();
}

// ===== 刷课控制命令 =====

function startAutoRun(params) {
  var courseId = params.courseId || "";
  var clazzId = params.clazzId || "";
  var cpi = params.cpi || "";
  if (!courseId || !clazzId) return { error: "缺少 courseId / clazzId" };

  var state = { active: true, courseId: courseId, clazzId: clazzId, cpi: cpi };
  setAutoState(state);
  _log("启动刷课: cid=" + courseId + " clz=" + clazzId + " cpi=" + cpi);

  var url = location.href;
  if (url.indexOf("/mycourse/studentstudy") !== -1) {
    useCxChapterLogic();
  } else {
    // 不在学习页, 先导航到章节任务页
    var navUrl = "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid=" + courseId + "&clazzid=" + clazzId + "&cpi=" + cpi + "&ut=s";
    window.location.href = navUrl;
  }
  return { started: true };
}

function requestPause() {
  var st = getAutoState();
  if (st) { st.active = false; setAutoState(st); }
  if (__interceptorId) { clearInterval(__interceptorId); __interceptorId = null; }
  _log("已请求暂停");
}

function getStudyStatus() {
  var st = getAutoState();
  return {
    active: st.active || false,
    courseId: st.courseId || null,
    clazzId: st.clazzId || null,
    cpi: st.cpi || null,
    url: window.location.href
  };
}

// ===== 自动续跑: 跨子域名导航后自动恢复 =====
(function autoContinue() {
  if (window.top !== window.self) return; // 只在顶层 frame
  var st = getAutoState();
  if (!st || !st.active) return;
  var url = window.location.href;
  _log("检测到刷课活跃状态, url=" + url.substring(0, 80));
  if (url.indexOf("/mycourse/studentstudy") !== -1) {
    useCxChapterLogic();
  } else if (url.indexOf("/mooc2/work/dowork") !== -1 || url.indexOf("/exam-ans/exam") !== -1 || url.indexOf("/stuExamWeb.html") !== -1) {
    handleStandaloneWork();
  }
})();
