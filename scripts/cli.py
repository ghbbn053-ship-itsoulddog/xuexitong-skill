from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
import re
import time
import traceback
from typing import Any, Callable

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from xxt.bridge import BridgePage
from xxt import selectors
from xxt.page_state import detect_page_state

# ── 超时配置 ──────────────────────────────────────────────
COMMAND_TIMEOUT = 10  # 秒 — bridge 级超时，避免 OpenClaw SIGKILL

# ── 统一输出 ──────────────────────────────────────────────
STATE_FILE = Path(__file__).with_name(".runtime_state.json")


def _now_ms(start: float) -> int:
    return int((time.time() - start) * 1000)


def _make_response(
    ok: bool,
    command: str,
    data: Any | None = None,
    state: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    allowed_actions: list[str] | None = None,
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    resp: dict[str, Any] = {"ok": ok, "command": command, "elapsedMs": elapsed_ms}
    if state:
        resp["state"] = state
    if data is not None:
        resp["data"] = data
    if error_code:
        resp["error"] = {"code": error_code, "message": error_message or ""}
    if allowed_actions:
        resp["allowedActions"] = allowed_actions
    return resp


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_absolute_url(current_url: str, src: str) -> str:
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if src.startswith("/"):
        origin = current_url.split("/", 3)
        return f"{origin[0]}//{origin[2]}{src}"
    return src


def load_runtime_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def timed_command(fn: Callable) -> Callable:
    """装饰器：统一包装 CLI 命令。自动计时 + 统一输出格式 + 超时守卫。"""
    import functools

    @functools.wraps(fn)
    def wrapper(page: BridgePage, args: argparse.Namespace, command_name: str | None = None) -> None:
        cmd = command_name or fn.__name__.replace("cmd_", "").replace("_", "-")
        t0 = time.time()
        try:
            # patch page timeout to be short-lived
            page._timeout = COMMAND_TIMEOUT
            fn(page, args)
        except Exception as exc:
            msg = str(exc)
            # Known timeout / bridge fail → give actionable error
            if "timeout" in msg.lower() or "timed out" in msg.lower():
                code = "BRIDGE_TIMEOUT"
                msg = "Bridge 响应超时 — 请确认浏览器已打开目标页面"
            elif "connection" in msg.lower() or "refused" in msg.lower():
                code = "BRIDGE_DISCONNECTED"
                msg = "Bridge 断开 — 请确认 bridge server 正在运行"
            else:
                code = "INTERNAL_ERROR"
            print_json(
                _make_response(
                    ok=False,
                    command=cmd,
                    error_code=code,
                    error_message=msg[:200],
                    elapsed_ms=_now_ms(t0),
                )
            )
        except SystemExit:
            raise
    return wrapper


def save_runtime_state(data: dict[str, Any]) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)  # atomic on POSIX; near-atomic on Windows


def merge_runtime_state(**updates: Any) -> dict[str, Any]:
    state = load_runtime_state()
    state.update({k: v for k, v in updates.items() if v is not None})
    save_runtime_state(state)
    return state


def retry_call(fn, retries: int = 10, delay_s: float = 0.4):
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if attempt == retries - 1:
                raise
            time.sleep(delay_s)
    if last_error:
        raise last_error
    return None


def safe_get_url(page: BridgePage) -> str | None:
    return retry_call(page.get_url)


def safe_has_element(page: BridgePage, selector: str, retries: int = 6, delay_s: float = 0.3) -> bool:
    return bool(retry_call(lambda: page.has_element(selector), retries=retries, delay_s=delay_s))


def safe_get_element_text(page: BridgePage, selector: str, retries: int = 6, delay_s: float = 0.3) -> str | None:
    return retry_call(lambda: page.get_element_text(selector), retries=retries, delay_s=delay_s)


def safe_get_element_attribute(
    page: BridgePage, selector: str, attr: str, retries: int = 6, delay_s: float = 0.3
) -> str | None:
    return retry_call(lambda: page.get_element_attribute(selector, attr), retries=retries, delay_s=delay_s)


def wait_for_element(page: BridgePage, selector: str, timeout_s: float = 12.0, interval_s: float = 0.5) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if page.has_element(selector):
                return True
        except Exception:
            pass
        time.sleep(interval_s)
    return False


def read_hidden_value(page: BridgePage, selector: str) -> str | None:
    return safe_get_element_attribute(page, selector, "value")


def read_frame_src(page: BridgePage, selector: str) -> str | None:
    return safe_get_element_attribute(page, selector, "src")


def parse_course_list_from_frame(page: BridgePage, frame_selector: str) -> list[dict[str, Any]]:
    return page.frame_evaluate(
        frame_selector,
        """
        (() => {
            const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim() || null;
            return Array.from(frameDocument.querySelectorAll('#courseList li.course')).map((li) => {
                const link = li.querySelector('a.color1');
                const name = li.querySelector('.course-name');
                const teacherCandidates = Array.from(li.querySelectorAll('.line2'))
                  .map((el) => clean(el.textContent))
                  .filter(Boolean);
                const teacher = teacherCandidates.length ? teacherCandidates[teacherCandidates.length - 1] : null;
                const id = li.id || null;
                const match = id ? id.match(/^course_(\\d+)_(\\d+)$/) : null;
                let cpi = null, enc = null;
                if (link && link.href) {
                    try {
                        const u = new URL(link.href);
                        cpi = u.searchParams.get('cpi') || null;
                        enc = u.searchParams.get('enc') || null;
                    } catch(e) {}
                }
                return {
                  id,
                  courseId: match ? match[1] : null,
                  clazzId: match ? match[2] : null,
                  cpi,
                  enc,
                  title: clean(name ? name.textContent : null),
                  teacher,
                  href: link ? link.href : null
                };
            });
        })()
        """,
    )


def parse_course_list(page: BridgePage) -> list[dict[str, Any]]:
    return page.evaluate(
        """
        (() => {
            const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim() || null;
            return Array.from(document.querySelectorAll('#courseList li.course')).map((li) => {
                const link = li.querySelector('a.color1');
                const name = li.querySelector('.course-name');
                const teacherCandidates = Array.from(li.querySelectorAll('.line2'))
                  .map((el) => clean(el.textContent))
                  .filter(Boolean);
                const teacher = teacherCandidates.length ? teacherCandidates[teacherCandidates.length - 1] : null;
                const id = li.id || null;
                const match = id ? id.match(/^course_(\\d+)_(\\d+)$/) : null;
                let cpi = null, enc = null;
                if (link && link.href) {
                    try {
                        const u = new URL(link.href);
                        cpi = u.searchParams.get('cpi') || null;
                        enc = u.searchParams.get('enc') || null;
                    } catch(e) {}
                }
                return {
                  id,
                  courseId: match ? match[1] : null,
                  clazzId: match ? match[2] : null,
                  cpi,
                  enc,
                  title: clean(name ? name.textContent : null),
                  teacher,
                  href: link ? link.href : null
                };
            });
        })()
        """
    )


def parse_study_state(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    next_match = re.search(r"nextChapterId\s*:\s*(\d+)", raw)
    unfinish_match = re.search(r"unfinishCount\s*:\s*(\d+)", raw)
    return {
        "raw": raw,
        "nextChapterId": next_match.group(1) if next_match else None,
        "unfinishCount": int(unfinish_match.group(1)) if unfinish_match else None,
    }


def parse_progress_from_text(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    match = re.search(r"已完成任务点[:：]\s*(\d+)\s*/\s*(\d+)", text)
    if not match:
        return None
    completed = int(match.group(1))
    total = int(match.group(2))
    return {
        "completedTaskPoints": completed,
        "totalTaskPoints": total,
        "unfinishedTaskPoints": max(total - completed, 0),
    }


def parse_chapter_item_id(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.match(r"cur(\d+)$", raw)
    return match.group(1) if match else None


def parse_task_points(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"(\d+)个待完成任务点", text)
    return int(match.group(1)) if match else None


def parse_task_points_from_item(item: dict[str, Any]) -> int | None:
    for key in ("hoverTaskText", "taskText", "pointsText", "rawText"):
        value = item.get(key)
        parsed = parse_task_points(value) if isinstance(value, str) else None
        if parsed is not None:
            return parsed

    hidden_value = item.get("knowledgeJobCount")
    if hidden_value is None:
        return None
    try:
        return int(hidden_value)
    except (TypeError, ValueError):
        return None


def parse_chapter_outline(page: BridgePage) -> dict[str, Any]:
    items = page.evaluate(
        """
        (() => {
            const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim() || null;
            const itemNodes = Array.from(document.querySelectorAll('.chapter_item[id^="cur"]'));
            const unitNodes = Array.from(document.querySelectorAll('.chapter_unit'));
            return {
              itemCount: itemNodes.length,
              unitCount: unitNodes.length,
              items: itemNodes.map((node) => {
                const titleNode = node.querySelector('.catalog_name');
                const orderNode = node.querySelector('.catalog_sbar');
                const taskNode = node.querySelector('.catalog_task');
                const hoverTips = node.querySelector('.bntHoverTips');
                const pointsNode = node.querySelector('.catalog_points_yi');
                const jobCount = node.querySelector('.knowledgeJobCount');
                return {
                  domId: node.id || null,
                  titleAttr: clean(node.getAttribute('title')),
                  onclick: clean(node.getAttribute('onclick')),
                  title: clean(titleNode ? titleNode.textContent : null),
                  orderLabel: clean(orderNode ? orderNode.textContent : null),
                  taskText: clean(taskNode ? taskNode.textContent : null),
                  hoverTaskText: clean(hoverTips ? hoverTips.textContent : null),
                  pointsText: clean(pointsNode ? pointsNode.textContent : null),
                  knowledgeJobCount: jobCount ? jobCount.value : null,
                  text: clean(node.textContent),
                  className: node.className || null
                };
              }),
              units: unitNodes.map((node) => {
                const header = node.querySelector('.chapter_Thats_bnt .catalog_name, .chapter_Thats_bnt .catalog_name.newCatalog_name, .chapter_Thats_bnt');
                return {
                  title: clean(header ? header.textContent : null),
                  text: clean(node.textContent)
                };
              })
            };
        })()
        """
    )

    parsed_items: list[dict[str, Any]] = []
    for item in items.get("items", []):
        task_text = item.get("taskText")
        parsed_items.append(
            {
                "chapterId": parse_chapter_item_id(item.get("domId")),
                "domId": item.get("domId"),
                "title": item.get("title") or item.get("titleAttr"),
                "orderLabel": item.get("orderLabel"),
                "taskText": task_text,
                "hoverTaskText": item.get("hoverTaskText"),
                "pointsText": item.get("pointsText"),
                "knowledgeJobCount": item.get("knowledgeJobCount"),
                "unfinishedTaskPoints": parse_task_points_from_item(item),
                "onclick": item.get("onclick"),
                "rawText": item.get("text"),
                "className": item.get("className"),
            }
        )

    return {
        "itemCount": items.get("itemCount", len(parsed_items)),
        "unitCount": items.get("unitCount", 0),
        "items": parsed_items,
        "units": items.get("units", []),
    }


def parse_to_old_onclick(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    match = re.search(r"toOld\('(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*(\d+)\)", raw)
    if not match:
        return None
    return {
        "courseId": match.group(1),
        "chapterId": match.group(2),
        "clazzId": match.group(3),
        "hideType": int(match.group(4)),
    }


def build_study_page_url(course_id: str, chapter_id: str, clazz_id: str, cpi: str, enc: str, hide_type: int = 0) -> str:
    return (
        "https://mooc1.chaoxing.com/mycourse/studentstudy"
        f"?chapterId={chapter_id}&courseId={course_id}&clazzid={clazz_id}"
        f"&cpi={cpi}&enc={enc}&mooc2=1&hidetype={hide_type}"
    )


def build_task_card_url(course_id: str, chapter_id: str, clazz_id: str, cpi: str) -> str:
    return (
        "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards"
        f"?clazzid={clazz_id}&courseid={course_id}&knowledgeid={chapter_id}"
        f"&num=0&ut=s&cpi={cpi}&v=2025-0424-1038-3&mooc2=1&isMicroCourse=false&editorPreview=0"
    )


def capture_context_from_task_card(page: BridgePage) -> dict[str, Any]:
    task_page = inspect_task_page(page)
    hidden = task_page.get("hiddenValues", {})
    course_id = hidden.get("courseId") or hidden.get("curCourseId")
    clazz_id = hidden.get("clazzId")
    chapter_id = hidden.get("knowledgeId") or hidden.get("chapterId")
    cpi = hidden.get("cpi")
    state0 = load_runtime_state()
    enc = hidden.get("enc") or state0.get("enc")
    state = merge_runtime_state(
        last_task_card_url=safe_get_url(page),
        course_id=course_id,
        clazz_id=clazz_id,
        chapter_id=chapter_id,
        cpi=cpi,
        enc=enc,
        last_study_page_url=build_study_page_url(course_id, chapter_id, clazz_id, cpi, enc) if all([course_id, chapter_id, clazz_id, cpi, enc]) else None,
    )
    return {"taskPage": task_page, "runtimeState": state}


def capture_context_from_study_page(page: BridgePage) -> dict[str, Any]:
    course_id = read_hidden_value(page, selectors.CHAPTER_PAGE_COURSE_ID)
    clazz_id = read_hidden_value(page, selectors.CHAPTER_PAGE_CLASS_ID)
    chapter_id = read_hidden_value(page, selectors.CHAPTER_PAGE_CHAPTER_ID)
    cpi = read_hidden_value(page, "#cpi, #userId, #curcpi") or load_runtime_state().get("cpi")
    current_url = safe_get_url(page) or ""
    # 从当前 URL 中提取 enc 参数
    enc = None
    try:
        parsed = urlparse(current_url)
        query_params = parse_qs(parsed.query)
        enc = query_params.get("enc", [None])[0]
    except Exception:
        pass
    enc = enc or read_hidden_value(page, "#enc") or load_runtime_state().get("enc")
    card_src = read_frame_src(page, selectors.CHAPTER_PAGE_CARD_IFRAME)
    state = merge_runtime_state(
        last_study_page_url=current_url,
        course_id=course_id,
        clazz_id=clazz_id,
        chapter_id=chapter_id,
        cpi=cpi,
        enc=enc,
        last_task_card_url=build_task_card_url(course_id, chapter_id, clazz_id, cpi) if all([course_id, chapter_id, clazz_id, cpi]) else None,
    )
    return {
        "courseId": course_id,
        "clazzId": clazz_id,
        "chapterId": chapter_id,
        "cpi": cpi,
        "enc": enc,
        "currentUrl": current_url,
        "cardIframeSrc": card_src,
        "runtimeState": state,
    }


def goto_study_page_from_state(page: BridgePage) -> dict[str, Any]:
    """从 runtime state 恢复学习页。优先用 last_study_page_url，其次用课程上下文重建。"""
    state = load_runtime_state()
    target_url = state.get("last_study_page_url")
    if not target_url:
        course_id = state.get("course_id")
        clazz_id = state.get("clazz_id")
        chapter_id = state.get("chapter_id")
        cpi = state.get("cpi")
        enc = state.get("enc")
        if all([course_id, clazz_id, chapter_id, cpi, enc]):
            target_url = build_study_page_url(course_id, chapter_id, clazz_id, cpi, enc)
    if not target_url:
        # 最终回退：尝试从当前页面 URL 推断 enc
        current_url = safe_get_url(page) or ""
        try:
            parsed = urlparse(current_url)
            params = parse_qs(parsed.query)
            fallback_enc = params.get("enc", [None])[0]
            if fallback_enc:
                merge_runtime_state(enc=fallback_enc)
                course_id = state.get("course_id")
                clazz_id = state.get("clazz_id")
                chapter_id = state.get("chapter_id")
                cpi = state.get("cpi")
                if all([course_id, clazz_id, chapter_id, cpi, fallback_enc]):
                    target_url = build_study_page_url(course_id, chapter_id, clazz_id, cpi, fallback_enc)
        except Exception:
            pass
    if not target_url:
        raise RuntimeError("没有可用的学习页上下文 (缺少 enc 或课程上下文)")
    page.navigate(target_url)
    page.wait_for_load(20)
    return {"targetUrl": target_url, "pageState": detect_page_state(page)}


def inspect_task_page(page: BridgePage) -> dict[str, Any]:
    return page.evaluate(
        """
        (() => {
            const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim() || null;
            const parseJsonAttr = (value) => {
                if (!value) return null;
                try {
                    return JSON.parse(value);
                } catch {
                    return null;
                }
            };

            const hiddenIds = [
              'curCourseId', 'courseId', 'clazzId', 'knowledgeId', 'chapterId',
              'cpi', 'cardId', 'ut'
            ];
            const hiddenValues = {};
            for (const id of hiddenIds) {
              const el = document.getElementById(id);
              hiddenValues[id] = el ? (el.value ?? null) : null;
            }

            return {
              title: document.title || null,
              hiddenValues,
              videoElements: Array.from(document.querySelectorAll('video')).map((el, index) => ({
                index,
                src: el.currentSrc || el.src || null,
                paused: !!el.paused,
                ended: !!el.ended,
                duration: Number.isFinite(el.duration) ? el.duration : null,
                currentTime: Number.isFinite(el.currentTime) ? el.currentTime : null,
                muted: !!el.muted,
                playbackRate: Number.isFinite(el.playbackRate) ? el.playbackRate : null,
                autoplay: !!el.autoplay,
                controls: !!el.controls
              })),
              iframeAttachments: Array.from(document.querySelectorAll('iframe')).map((el, index) => ({
                index,
                id: el.id || null,
                className: typeof el.className === 'string' ? el.className : null,
                src: el.getAttribute('src'),
                data: parseJsonAttr(el.getAttribute('data')),
                dataRaw: el.getAttribute('data'),
                style: el.getAttribute('style')
              })),
              jobIcons: Array.from(document.querySelectorAll('.ans-job-icon')).map((el, index) => ({
                index,
                id: el.id || null,
                className: typeof el.className === 'string' ? el.className : null,
                style: el.getAttribute('style'),
                text: clean(el.textContent)
              })),
              playerGlobals: Object.keys(window).filter((key) => /player|video|ananas|job/i.test(key)).slice(0, 50),
              bodyTextPreview: clean(document.body ? document.body.innerText : '')?.slice(0, 1500) || null
            };
        })()
        """
    )


def inspect_video_tasks(page: BridgePage) -> dict[str, Any]:
    data = inspect_task_page(page)
    video_tasks: list[dict[str, Any]] = []

    for item in data.get("iframeAttachments", []):
        parsed = item.get("data") or {}
        class_name = item.get("className") or ""
        src = item.get("src") or ""
        if "video" not in class_name and "/video/" not in src and "/video" not in src:
            continue

        video_tasks.append(
            {
                "index": item.get("index"),
                "iframeClassName": class_name,
                "iframeSrc": src,
                "objectId": parsed.get("objectid"),
                "jobId": parsed.get("jobid") or parsed.get("_jobid"),
                "mid": parsed.get("mid"),
                "name": parsed.get("name"),
                "size": parsed.get("size"),
                "humanSize": parsed.get("hsize"),
                "fileType": parsed.get("type"),
                "allowSwitchWindow": parsed.get("switchwindow"),
                "allowFastForward": parsed.get("fastforward"),
                "doubleSpeed": parsed.get("doublespeed"),
                "jobIconState": data.get("jobIcons", []),
            }
        )

    return {
        "pageTitle": data.get("title"),
        "hiddenValues": data.get("hiddenValues"),
        "videoTaskCount": len(video_tasks),
        "videoTasks": video_tasks,
    }


def inspect_video_runtime(page: BridgePage) -> dict[str, Any]:
    return page.evaluate(
        """
        (() => {
            const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim() || null;
            const frame = document.querySelector('.ans-attach-online.ans-insertvideo-online');
            if (!frame) {
                return {
                    exists: false,
                    selector: '.ans-attach-online.ans-insertvideo-online'
                };
            }

            const frameWindow = frame.contentWindow || null;
            const frameDocument = frame.contentDocument || (frameWindow ? frameWindow.document : null);
            if (!frameWindow || !frameDocument) {
                return {
                    exists: true,
                    accessible: false,
                    selector: '.ans-attach-online.ans-insertvideo-online'
                };
            }

            const safeCall = (fn) => {
                try {
                    return fn();
                } catch (error) {
                    return `ERR:${error && error.message ? error.message : String(error)}`;
                }
            };

            const configValue = (name) => safeCall(() => (
                typeof frameWindow.config === 'function' ? frameWindow.config(name) : null
            ));

            const playerKeys = safeCall(() => (
                frameWindow.videojs && frameWindow.videojs.players
                    ? Object.keys(frameWindow.videojs.players)
                    : []
            ));

            return {
                exists: true,
                accessible: true,
                frameUrl: safeCall(() => frameWindow.location.href),
                frameReadyState: frameDocument.readyState || null,
                frameTitle: frameDocument.title || null,
                bodyTextPreview: clean(frameDocument.body ? frameDocument.body.innerText : '')?.slice(0, 1200) || null,
                globals: {
                    videoName: safeCall(() => frameWindow.videoName || null),
                    videoJobId: safeCall(() => frameWindow.videoJobId || null),
                    videoObjectId: safeCall(() => frameWindow.videoObjectId || null),
                    playerTime: safeCall(() => frameWindow.playerTime ?? null),
                    supportH5Video: safeCall(() => frameWindow.supportH5Video ?? null),
                    loadVideoType: safeCall(() => typeof frameWindow.loadVideo),
                    playVideoType: safeCall(() => typeof frameWindow.playVideo),
                    showMoocPlayerType: safeCall(() => typeof frameWindow.showMoocPlayer),
                    createVideoTaskType: safeCall(() => typeof frameWindow.createVideoTask),
                    pushVideoInfoType: safeCall(() => typeof frameWindow.pushVideoInfo),
                    chapterPlayNextVideoType: safeCall(() => typeof frameWindow.chapterPlayNextVideo),
                    isUnFinishJobType: safeCall(() => typeof frameWindow.isUnFinishJob),
                    configType: safeCall(() => typeof frameWindow.config),
                    playerType: safeCall(() => typeof frameWindow.player),
                    videojsType: safeCall(() => typeof frameWindow.videojs),
                    videojsPlayerKeys: Array.isArray(playerKeys) ? playerKeys : [],
                    markersPlayerType: safeCall(() => typeof frameWindow.markersPlayer),
                    markersPlayerV2Type: safeCall(() => typeof frameWindow.markersPlayerV2),
                },
                configValues: {
                    objectid: configValue('objectid'),
                    jobid: configValue('jobid'),
                    mid: configValue('mid'),
                    name: configValue('name'),
                    dtoken: configValue('dtoken'),
                    otherInfo: configValue('otherInfo'),
                },
                videoElements: Array.from(frameDocument.querySelectorAll('video')).map((el, index) => ({
                    index,
                    src: el.currentSrc || el.src || null,
                    paused: !!el.paused,
                    ended: !!el.ended,
                    duration: Number.isFinite(el.duration) ? el.duration : null,
                    currentTime: Number.isFinite(el.currentTime) ? el.currentTime : null,
                    muted: !!el.muted,
                    playbackRate: Number.isFinite(el.playbackRate) ? el.playbackRate : null,
                    autoplay: !!el.autoplay,
                    controls: !!el.controls,
                })),
                iframeElements: Array.from(frameDocument.querySelectorAll('iframe')).map((el, index) => ({
                    index,
                    id: el.id || null,
                    className: typeof el.className === 'string' ? el.className : null,
                    src: el.getAttribute('src'),
                    style: el.getAttribute('style'),
                })),
                playerLikeElements: Array.from(
                    frameDocument.querySelectorAll('[class*="video"], [class*="player"], [id*="video"], [id*="player"]')
                ).slice(0, 40).map((el, index) => ({
                    index,
                    tag: el.tagName,
                    id: el.id || null,
                    className: typeof el.className === 'string' ? el.className : null,
                    text: clean(el.textContent)?.slice(0, 200) || null,
                }))
            };
        })()
        """
    )


def try_init_video_player(page: BridgePage) -> dict[str, Any]:
    return page.evaluate(
        """
        (async () => {
            const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim() || null;
            const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const frame = document.querySelector('.ans-attach-online.ans-insertvideo-online');
            if (!frame) {
                return {
                    ok: false,
                    reason: 'video iframe not found'
                };
            }

            const frameWindow = frame.contentWindow || null;
            const frameDocument = frame.contentDocument || (frameWindow ? frameWindow.document : null);
            if (!frameWindow || !frameDocument) {
                return {
                    ok: false,
                    reason: 'video iframe not accessible'
                };
            }

            const actions = [];
            const safe = (label, fn) => {
                try {
                    const result = fn();
                    actions.push({ step: label, ok: true });
                    return result;
                } catch (error) {
                    actions.push({ step: label, ok: false, error: error && error.message ? error.message : String(error) });
                    return null;
                }
            };

            const snapshot = () => {
                let playerKeys = [];
                try {
                    if (frameWindow.videojs && frameWindow.videojs.players) {
                        playerKeys = Object.keys(frameWindow.videojs.players);
                    }
                } catch {}

                return {
                    readyState: frameDocument.readyState || null,
                    bodyTextPreview: clean(frameDocument.body ? frameDocument.body.innerText : '')?.slice(0, 800) || null,
                    videoName: safe('read videoName', () => frameWindow.videoName || null),
                    videoJobId: safe('read videoJobId', () => frameWindow.videoJobId || null),
                    videoObjectId: safe('read videoObjectId', () => frameWindow.videoObjectId || null),
                    configObjectId: safe('read config(objectid)', () => typeof frameWindow.config === 'function' ? frameWindow.config('objectid') : null),
                    configJobId: safe('read config(jobid)', () => typeof frameWindow.config === 'function' ? frameWindow.config('jobid') : null),
                    playerKeys,
                    hasPlayerObject: safe('read player object', () => !!frameWindow.player),
                    videoCount: frameDocument.querySelectorAll('video').length
                };
            };

            const before = snapshot();

            if (typeof frameWindow.loadVideo === 'function') {
                safe('call loadVideo()', () => frameWindow.loadVideo());
            } else {
                actions.push({ step: 'call loadVideo()', ok: false, error: 'loadVideo is not a function' });
            }

            await wait(2000);

            const middle = snapshot();

            if (typeof frameWindow.playVideo === 'function') {
                safe('call playVideo()', () => frameWindow.playVideo());
            } else {
                actions.push({ step: 'call playVideo()', ok: false, error: 'playVideo is not a function' });
            }

            await wait(2000);

            const after = snapshot();

            return {
                ok: true,
                actions,
                before,
                middle,
                after
            };
        })()
        """
    )


def get_video_playback_state(page: BridgePage) -> dict[str, Any]:
    return page.evaluate(
        """
        (() => {
            const frame = document.querySelector('.ans-attach-online.ans-insertvideo-online');
            if (!frame) {
                return { ok: false, reason: 'video iframe not found' };
            }
            const w = frame.contentWindow || null;
            const d = frame.contentDocument || (w ? w.document : null);
            if (!w || !d) {
                return { ok: false, reason: 'video iframe not accessible' };
            }

            const player = w.videojs && w.videojs.players ? w.videojs.players.video : null;
            const video = d.querySelector('video');
            const guard = w.__openclawVideoGuard || null;
            return {
                ok: true,
                hasPlayer: !!player,
                hasVideo: !!video,
                playerState: player ? {
                    currentTime: player.currentTime(),
                    duration: Number.isFinite(player.duration()) ? player.duration() : null,
                    paused: player.paused(),
                    ended: player.ended(),
                    muted: player.muted(),
                    playbackRate: player.playbackRate(),
                    volume: player.volume()
                } : null,
                videoState: video ? {
                    currentTime: video.currentTime,
                    duration: Number.isFinite(video.duration) ? video.duration : null,
                    paused: video.paused,
                    ended: video.ended,
                    muted: video.muted,
                    playbackRate: video.playbackRate,
                    volume: video.volume,
                    src: video.currentSrc || video.src || null
                } : null,
                runtime: {
                    videoName: w.videoName || null,
                    videoJobId: w.videoJobId || null,
                    videoObjectId: w.videoObjectId || null,
                    guardInstalled: !!guard,
                    guardEnabled: !!(guard && guard.enabled),
                    manualPause: !!(guard && guard.manualPause)
                }
            };
        })()
        """
    )


def play_video_task(page: BridgePage) -> dict[str, Any]:
    return page.evaluate(
        """
        (async () => {
            const frame = document.querySelector('.ans-attach-online.ans-insertvideo-online');
            if (!frame) {
                return { ok: false, reason: 'video iframe not found' };
            }
            const w = frame.contentWindow || null;
            const d = frame.contentDocument || (w ? w.document : null);
            if (!w || !d) {
                return { ok: false, reason: 'video iframe not accessible' };
            }
            const player = w.videojs && w.videojs.players ? w.videojs.players.video : null;
            const video = d.querySelector('video');
            if (!player && !video) {
                return { ok: false, reason: 'no player or video element' };
            }

            if (w.__openclawVideoGuard) {
                w.__openclawVideoGuard.manualPause = false;
            }

            try {
                if (player) {
                    const result = player.play();
                    if (result && typeof result.then === 'function') {
                        await result;
                    }
                } else {
                    const result = video.play();
                    if (result && typeof result.then === 'function') {
                        await result;
                    }
                }
            } catch (error) {
                return { ok: false, reason: error && error.message ? error.message : String(error) };
            }

            return { ok: true };
        })()
        """
    )


def pause_video_task(page: BridgePage) -> dict[str, Any]:
    return page.evaluate(
        """
        (() => {
            const frame = document.querySelector('.ans-attach-online.ans-insertvideo-online');
            if (!frame) {
                return { ok: false, reason: 'video iframe not found' };
            }
            const w = frame.contentWindow || null;
            const d = frame.contentDocument || (w ? w.document : null);
            if (!w || !d) {
                return { ok: false, reason: 'video iframe not accessible' };
            }
            const player = w.videojs && w.videojs.players ? w.videojs.players.video : null;
            const video = d.querySelector('video');
            if (!player && !video) {
                return { ok: false, reason: 'no player or video element' };
            }

            if (!w.__openclawVideoGuard) {
                w.__openclawVideoGuard = { enabled: false, manualPause: true };
            } else {
                w.__openclawVideoGuard.manualPause = true;
            }

            if (player) {
                player.pause();
            } else {
                video.pause();
            }

            return { ok: true };
        })()
        """
    )


def set_video_rate(page: BridgePage, rate: float) -> dict[str, Any]:
    return page.evaluate(
        f"""
        (() => {{
            const frame = document.querySelector('.ans-attach-online.ans-insertvideo-online');
            if (!frame) {{
                return {{ ok: false, reason: 'video iframe not found' }};
            }}
            const w = frame.contentWindow || null;
            const d = frame.contentDocument || (w ? w.document : null);
            if (!w || !d) {{
                return {{ ok: false, reason: 'video iframe not accessible' }};
            }}
            const player = w.videojs && w.videojs.players ? w.videojs.players.video : null;
            const video = d.querySelector('video');
            if (!player && !video) {{
                return {{ ok: false, reason: 'no player or video element' }};
            }}
            const rate = {json.dumps(rate)};
            if (player) {{
                player.playbackRate(rate);
            }}
            if (video) {{
                video.playbackRate = rate;
            }}
            return {{ ok: true, rate }};
        }})()
        """
    )


def mute_video_task(page: BridgePage, muted: bool) -> dict[str, Any]:
    return page.evaluate(
        f"""
        (() => {{
            const frame = document.querySelector('.ans-attach-online.ans-insertvideo-online');
            if (!frame) {{
                return {{ ok: false, reason: 'video iframe not found' }};
            }}
            const w = frame.contentWindow || null;
            const d = frame.contentDocument || (w ? w.document : null);
            if (!w || !d) {{
                return {{ ok: false, reason: 'video iframe not accessible' }};
            }}
            const player = w.videojs && w.videojs.players ? w.videojs.players.video : null;
            const video = d.querySelector('video');
            if (!player && !video) {{
                return {{ ok: false, reason: 'no player or video element' }};
            }}
            const muted = {json.dumps(muted)};
            if (player) {{
                player.muted(muted);
            }}
            if (video) {{
                video.muted = muted;
            }}
            return {{ ok: true, muted }};
        }})()
        """
    )


def arm_video_guard(page: BridgePage) -> dict[str, Any]:
    return page.evaluate(
        """
        (() => {
            const frame = document.querySelector('.ans-attach-online.ans-insertvideo-online');
            if (!frame) {
                return { ok: false, reason: 'video iframe not found' };
            }
            const w = frame.contentWindow || null;
            const d = frame.contentDocument || (w ? w.document : null);
            if (!w || !d) {
                return { ok: false, reason: 'video iframe not accessible' };
            }
            const player = w.videojs && w.videojs.players ? w.videojs.players.video : null;
            const video = d.querySelector('video');
            if (!player && !video) {
                return { ok: false, reason: 'no player or video element' };
            }

            const guard = w.__openclawVideoGuard || {
                enabled: true,
                manualPause: false,
                installed: false,
                resumeDelayMs: 250,
                listeners: []
            };

            const activeVideo = () => d.querySelector('video');
            const activePlayer = () => (w.videojs && w.videojs.players ? w.videojs.players.video : null);

            const resumeIfNeeded = () => {
                if (!guard.enabled || guard.manualPause) {
                    return;
                }
                const v = activeVideo();
                const p = activePlayer();
                if (v && !v.ended && v.paused) {
                    setTimeout(() => {
                        const latestVideo = activeVideo();
                        const latestPlayer = activePlayer();
                        if (!guard.enabled || guard.manualPause) {
                            return;
                        }
                        try {
                            if (latestPlayer) {
                                const result = latestPlayer.play();
                                if (result && typeof result.catch === 'function') {
                                    result.catch(() => {});
                                }
                            } else if (latestVideo) {
                                const result = latestVideo.play();
                                if (result && typeof result.catch === 'function') {
                                    result.catch(() => {});
                                }
                            }
                        } catch {}
                    }, guard.resumeDelayMs);
                }
            };

            if (!guard.installed) {
                const v = activeVideo();
                if (v) {
                    const pauseHandler = () => resumeIfNeeded();
                    v.addEventListener('pause', pauseHandler, true);
                    guard.listeners.push({ target: v, type: 'pause', handler: pauseHandler });

                    const clickBlock = (event) => {
                        if (!guard.enabled) {
                            return;
                        }
                        event.preventDefault();
                        event.stopPropagation();
                    };
                    for (const type of ['click', 'dblclick', 'touchend']) {
                        v.addEventListener(type, clickBlock, true);
                        guard.listeners.push({ target: v, type, handler: clickBlock });
                    }
                }
                guard.installed = true;
            }

            guard.enabled = true;
            guard.manualPause = false;
            w.__openclawVideoGuard = guard;
            return {
                ok: true,
                installed: guard.installed,
                enabled: guard.enabled,
                listenerCount: guard.listeners.length
            };
        })()
        """
    )


def disarm_video_guard(page: BridgePage) -> dict[str, Any]:
    return page.evaluate(
        """
        (() => {
            const frame = document.querySelector('.ans-attach-online.ans-insertvideo-online');
            if (!frame) {
                return { ok: false, reason: 'video iframe not found' };
            }
            const w = frame.contentWindow || null;
            const guard = w ? w.__openclawVideoGuard : null;
            if (!guard) {
                return { ok: true, installed: false, enabled: false };
            }
            for (const item of guard.listeners || []) {
                try {
                    item.target.removeEventListener(item.type, item.handler, true);
                } catch {}
            }
            guard.enabled = false;
            guard.installed = false;
            guard.listeners = [];
            w.__openclawVideoGuard = guard;
            return { ok: true, installed: false, enabled: false };
        })()
        """
    )


# ============================================================
# 新增命令：wait-video-end / go-next-task-point / run-course
# ============================================================


def cmd_wait_video_end(page: BridgePage, args: argparse.Namespace) -> None:
    """轮询等待当前视频播完（仅适用于 task_card 页面）。"""
    state = detect_page_state(page)
    if state["page"] != "task_card":
        print_json(
            {
                "ok": False,
                "command": "wait-video-end",
                "reason": "当前页面不是任务卡页",
                "pageState": state,
            }
        )
        return

    timeout_s = getattr(args, "timeout", 1800) or 1800
    interval_s = getattr(args, "interval", 3.0) or 3.0
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        rt = load_runtime_state()
        if rt.get("pause_requested"):
            print_json({"ok": True, "command": "wait-video-end", "action": "paused_by_user"})
            return

        playback = get_video_playback_state(page)
        player = playback.get("playerState") or {}
        video = playback.get("videoState") or {}

        if player.get("ended") or video.get("ended"):
            print_json(
                {
                    "ok": True,
                    "command": "wait-video-end",
                    "action": "video_ended",
                    "playbackState": playback,
                }
            )
            return

        current_page = detect_page_state(page)
        if current_page["page"] != "task_card":
            print_json(
                {
                    "ok": True,
                    "command": "wait-video-end",
                    "action": "page_changed",
                    "newPage": current_page,
                }
            )
            return

        time.sleep(interval_s)

    print_json({"ok": False, "command": "wait-video-end", "reason": "timeout"})


def cmd_go_next_task_point(page: BridgePage, _args: argparse.Namespace) -> None:
    """在 study_page 上跳到下一个任务点 (num+1)。"""
    state = detect_page_state(page)
    if state["page"] != "study_page":
        print_json(
            {
                "ok": False,
                "command": "go-next-task-point",
                "reason": "当前页面不是学习页",
                "pageState": state,
            }
        )
        return

    context = capture_context_from_study_page(page)
    current_url = context.get("currentUrl") or ""
    card_src = context.get("cardIframeSrc") or ""

    if not card_src or card_src == "about:blank":
        print_json(
            {
                "ok": False,
                "command": "go-next-task-point",
                "reason": "未找到任务卡 iframe src",
                "pageState": state,
            }
        )
        return

    try:
        parsed = urlparse(card_src)
        params = parse_qs(parsed.query)
        current_num = int(params.get("num", ["0"])[0])
        next_num = current_num + 1
        params["num"] = [str(next_num)]
        new_query = urlencode(params, doseq=True)
        next_url = urlunparse(parsed._replace(query=new_query))
        next_url = build_absolute_url(current_url, next_url)
    except Exception as exc:
        print_json(
            {
                "ok": False,
                "command": "go-next-task-point",
                "reason": f"URL 解析失败: {exc}",
            }
        )
        return

    page.navigate(next_url)
    page.wait_for_load(20)
    time.sleep(1)

    new_state = detect_page_state(page)
    new_context = capture_context_from_task_card(page) if new_state["page"] == "task_card" else {}

    print_json(
        {
            "ok": True,
            "command": "go-next-task-point",
            "previousNum": current_num,
            "nextNum": next_num,
            "targetUrl": next_url,
            "pageState": new_state,
            "context": new_context,
        }
    )


def cmd_request_pause(_page: BridgePage, _args: argparse.Namespace) -> None:
    """设置暂停标志，run-course 会在当前视频播完后停止。"""
    merge_runtime_state(pause_requested=True)
    print_json(
        {
            "ok": True,
            "command": "request-pause",
            "message": "已请求暂停，当前视频播完后停止",
        }
    )


def cmd_get_loop_status(page: BridgePage, _args: argparse.Namespace) -> None:
    """查看当前自动化循环的运行状态。"""
    rt = load_runtime_state()
    state = detect_page_state(page)
    print_json(
        {
            "ok": True,
            "command": "get-loop-status",
            "loopActive": rt.get("loop_active", False),
            "pauseRequested": rt.get("pause_requested", False),
            "completedChapters": rt.get("completed_chapters", []),
            "completedChapterCount": len(rt.get("completed_chapters", [])),
            "totalVideosWatched": rt.get("total_videos_watched", 0),
            "blockedItems": rt.get("blocked_items", []),
            "currentPage": state,
            "currentUrl": safe_get_url(page),
        }
    )


def cmd_run_course(page: BridgePage, args: argparse.Namespace) -> None:
    """整门课循环自动化：自动播完所有章节的视频任务点。"""
    course_id = args.course_id
    clazz_id = args.clazz_id
    cpi = args.cpi
    enc = getattr(args, "enc", None) or None
    max_chapters = getattr(args, "max_chapters", 999) or 999

    # 导航操作可能较慢，放宽 bridge 超时
    _saved_timeout = page._timeout
    page._timeout = 30

    try:
        _run_course_loop(page, course_id, clazz_id, cpi, enc, max_chapters)
    finally:
        page._timeout = _saved_timeout


def _run_course_loop(
    page: BridgePage,
    course_id: str,
    clazz_id: str,
    cpi: str,
    enc: str | None,
    max_chapters: int,
) -> None:

    # --- 进度持久化：同名课程续跑，换课程重置 ---
    existing = load_runtime_state()
    same_course = (
        existing.get("course_id") == course_id
        and existing.get("loop_active")
    )

    if same_course:
        # 续跑：保留已完成章节和视频计数
        completed_chapters = existing.get("completed_chapters", [])
        blocked_items = existing.get("blocked_items", [])
        total_videos_watched = existing.get("total_videos_watched", 0)
        last_chapter_id = existing.get("last_completed_chapter_id")
        last_task_num = existing.get("last_completed_task_num", 0)
        resume_msg = (
            f"续跑模式：已完成 {len(completed_chapters)} 章，"
            f"{total_videos_watched} 个视频"
        )
        if last_chapter_id:
            resume_msg += f"，上次停在章节 {last_chapter_id} 任务点 {last_task_num}"
        print_json(_make_response(
            ok=True, command="run-course",
            data={"action": "resuming", "detail": resume_msg},
        ))
    else:
        completed_chapters = []
        blocked_items = []
        total_videos_watched = 0
        last_chapter_id = None
        last_task_num = 0

    merge_runtime_state(
        course_id=course_id,
        clazz_id=clazz_id,
        cpi=cpi,
        enc=enc,
        pause_requested=False,
        loop_active=True,
        completed_chapters=completed_chapters,
        blocked_items=blocked_items,
        total_videos_watched=total_videos_watched,
        last_completed_chapter_id=last_chapter_id,
        last_completed_task_num=last_task_num,
    )

    chapter_task_url = (
        "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse"
        f"?courseid={course_id}&clazzid={clazz_id}&cpi={cpi}&ut=s"
    )
    page.navigate(chapter_task_url)
    page.wait_for_load(20)
    time.sleep(2)

    chapters_processed = 0

    while chapters_processed < max_chapters:
        rt = load_runtime_state()
        if rt.get("pause_requested"):
            print_json(_make_response(
                ok=True, command="run-course",
                data={"action": "paused", "chaptersProcessed": chapters_processed},
            ))
            return

        # 确保在章节任务页
        state = detect_page_state(page)
        if state["page"] != "chapter_task":
            page.navigate(chapter_task_url)
            page.wait_for_load(20)
            time.sleep(2)
            state = detect_page_state(page)
            if state["page"] != "chapter_task":
                print_json(_make_response(
                    ok=False, command="run-course",
                    error_code="NAVIGATION_FAILED",
                    error_message="无法到达章节任务页",
                    data={"chaptersProcessed": chapters_processed},
                ))
                return

        wait_for_element(page, selectors.CHAPTER_PAGE_COURSETREE, timeout_s=12.0)
        chapter_outline = parse_chapter_outline(page)

        next_chapter = next(
            (
                item
                for item in chapter_outline["items"]
                if (item.get("unfinishedTaskPoints") or 0) > 0
                and item["chapterId"] not in rt.get("completed_chapters", [])
            ),
            None,
        )

        if not next_chapter:
            print_json(_make_response(
                ok=True, command="run-course",
                data={"action": "course_complete", "chaptersProcessed": chapters_processed},
            ))
            return

        chapter_id = next_chapter["chapterId"]

        # 点击章节进入学习页
        page.click_element(f"#{next_chapter['domId']}")
        page.wait_for_load(20)
        time.sleep(2)

        study_state = detect_page_state(page)
        if study_state["page"] == "study_page":
            capture_context_from_study_page(page)

        # 处理当前章节的所有任务点
        # 续跑：如上次停在同一章节，从上次任务点继续，否则从 0 开始
        rt_pre = load_runtime_state()
        same_chapter = rt_pre.get("last_completed_chapter_id") == chapter_id
        task_num = rt_pre.get("last_completed_task_num", 0) if same_chapter else 0
        max_tasks = 50
        chapter_done = True  # assume complete：遇 break 才改 False

        while task_num < max_tasks:
            rt = load_runtime_state()
            if rt.get("pause_requested"):
                chapter_done = False
                break

            current_state = detect_page_state(page)

            if current_state["page"] == "study_page":
                context = capture_context_from_study_page(page)
                card_src = context.get("cardIframeSrc")
                if not card_src or card_src == "about:blank":
                    chapter_done = False
                    break
                cur_url = context.get("currentUrl") or ""
                target_url = build_absolute_url(cur_url, card_src)
                page.navigate(target_url)
                page.wait_for_load(20)
                time.sleep(1)
                capture_context_from_task_card(page)
                continue

            if current_state["page"] == "task_card":
                rt = load_runtime_state()
                if rt.get("pause_requested"):
                    chapter_done = False
                    break

                video_tasks = inspect_video_tasks(page)

                if video_tasks.get("videoTaskCount", 0) > 0:
                    playback = get_video_playback_state(page)
                    player = playback.get("playerState") or {}

                    if player.get("ended"):
                        # 视频已结束，跳到下一任务点
                        task_num += 1
                        merge_runtime_state(
                            total_videos_watched=rt.get("total_videos_watched", 0) + 1,
                            last_completed_chapter_id=chapter_id,
                            last_completed_task_num=task_num,
                        )
                        goto_study_page_from_state(page)
                        time.sleep(2)
                        page.wait_for_load(20)

                        # 跳 num+1
                        ctx = capture_context_from_study_page(page)
                        next_card_src = ctx.get("cardIframeSrc") or ""
                        if next_card_src and next_card_src != "about:blank":
                            try:
                                cur_u = ctx.get("currentUrl") or ""
                                parsed = urlparse(next_card_src)
                                params_n = parse_qs(parsed.query)
                                next_num = int(params_n.get("num", ["0"])[0]) + 1
                                params_n["num"] = [str(next_num)]
                                new_q = urlencode(params_n, doseq=True)
                                next_card = urlunparse(parsed._replace(query=new_q))
                                next_card = build_absolute_url(cur_u, next_card)
                                page.navigate(next_card)
                                page.wait_for_load(20)
                                time.sleep(1)
                                capture_context_from_task_card(page)
                            except Exception:
                                chapter_done = False
                                break
                        else:
                            chapter_done = False
                            break
                        continue

                    # 视频未结束，启动播放并轮询等待结束
                    arm_video_guard(page)
                    mute_video_task(page, True)
                    play_video_task(page)

                    video_deadline = time.time() + 1800
                    while time.time() < video_deadline:
                        rt2 = load_runtime_state()
                        if rt2.get("pause_requested"):
                            break
                        pb = get_video_playback_state(page)
                        p = pb.get("playerState") or {}
                        if p.get("ended"):
                            break
                        if detect_page_state(page)["page"] != "task_card":
                            break
                        time.sleep(3)
                    continue

                # 无视频任务 — 检查作业/测验阻塞
                task_page = inspect_task_page(page)
                body = task_page.get("bodyTextPreview") or ""
                if any(k in body for k in ["作业", "测验", "考试", "题", "答题"]):
                    merge_runtime_state(
                        blocked_items=rt.get("blocked_items", [])
                        + [
                            {
                                "chapterId": chapter_id,
                                "taskNum": task_num,
                                "type": "quiz_or_assignment",
                            }
                        ]
                    )
                    goto_study_page_from_state(page)
                    time.sleep(2)
                    page.wait_for_load(20)
                    task_num += 1
                    continue

                # 无视频、无阻塞 = 空任务点
                task_num += 1
                continue

            # 不在预期页面，退出当前章节
            chapter_done = False
            break

        if chapter_done:
            chapters_processed += 1
            merge_runtime_state(
                completed_chapters=rt.get("completed_chapters", []) + [chapter_id],
                last_completed_chapter_id=chapter_id,
                last_completed_task_num=0,
            )
        else:
            # 非正常退出（pause / 错误 / about:blank）— 不标记完成，下次续跑同一章
            merge_runtime_state(
                last_completed_chapter_id=chapter_id,
                last_completed_task_num=task_num,
            )
        page.navigate(chapter_task_url)
        page.wait_for_load(20)
        time.sleep(2)

    final_rt = load_runtime_state()
    print_json(_make_response(
        ok=True, command="run-course",
        data={
            "action": "finished",
            "chaptersProcessed": chapters_processed,
            "totalVideosWatched": final_rt.get("total_videos_watched", 0),
            "blockedItems": final_rt.get("blocked_items", []),
            "completedChapters": final_rt.get("completed_chapters", []),
        },
    ))


def allowed_actions_for_state(state: dict[str, Any]) -> list[str]:
    """根据页面状态返回可执行的动作列表。
    
    注意: where-am-i 是元命令，始终可用但不列入返回值，避免 OpenClaw 自引用循环。
    """
    page = state.get("page", "unknown")
    actions: dict[str, list[str]] = {
        "login": ["navigate-to-chaoxing"],
        "home_after_login": ["go-to-course-list"],
        "personal_space": ["go-to-course-list"],
        "space_wrapper": ["go-to-course-list", "list-courses", "list-courses-from-frame"],
        "course_list": ["go-to-course-list", "list-courses", "open-course-by-id"],
        "course_detail": [
            "open-course",
            "list-chapters",
            "get-progress",
            "run-course",
        ],
        "chapter_task": [
            "list-chapters",
            "get-chapter-summary",
            "get-progress",
            "get-current-context",
            "open-chapter-by-id",
            "auto-advance-step",
            "run-course",
        ],
        "study_page": [
            "auto-advance-step",
            "go-next-task-point",
            "next-chapter",
            "return-to-study-page",
            "wait-video-end",
        ],
        "task_card": [
            "auto-advance-step",
            "inspect-task-page",
            "inspect-video-tasks",
            "play-video-task",
            "pause-video-task",
            "set-video-rate",
            "mute-video-task",
            "arm-video-guard",
            "get-video-playback-state",
            "wait-video-end",
        ],
        "video_attachment": [
            "get-video-playback-state",
            "play-video-task",
            "pause-video-task",
            "set-video-rate",
        ],
        "unknown": ["navigate", "check-login"],
    }
    return actions.get(page, actions["unknown"])


def cmd_where_am_i(page: BridgePage, _args: argparse.Namespace) -> None:
    """纯 DOM 检测 — 0 导航，返回当前页面状态 + 可执行动作。

    替代旧的 get-current-context，核心区别：
    - 不导航、不等待、不触发页面加载
    - 在 course_detail 页自动提取并缓存 courseId/clazzId/cpi
    - 返回 allowedActions 告诉上层能做什么
    """
    t0 = time.time()
    state = detect_page_state(page)
    current_url = safe_get_url(page)
    actions = allowed_actions_for_state(state)

    data: dict[str, Any] = {
        "currentUrl": current_url,
        "pageState": state,
        "allowedActions": actions,
    }

    # 在 course_detail 页自动缓存课程参数
    if state["page"] == "course_detail":
        try:
            course_id = read_hidden_value(page, selectors.COURSE_PAGE_COURSE_ID)
            clazz_id = read_hidden_value(page, selectors.COURSE_PAGE_CLASS_ID)
            cpi = read_hidden_value(page, selectors.COURSE_PAGE_CPI)
            if course_id and clazz_id:
                from xxt.cache import set_cache as cache_set
                params = {"courseId": course_id, "clazzId": clazz_id, "cpi": cpi}
                cache_set("courseParams", params, source="where-am-i")
                # 同步到 runtime state
                merge_runtime_state(course_id=course_id, clazz_id=clazz_id, cpi=cpi)
                data["cachedParams"] = params
        except Exception:
            pass

    print_json(
        _make_response(
            ok=True,
            command="where-am-i",
            state=state["page"],
            data=data,
            allowed_actions=actions,
            elapsed_ms=_now_ms(t0),
        )
    )


def cmd_get_current_context(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    data: dict[str, Any] = {
        "ok": True,
        "command": "get-current-context",
        "pageState": state,
        "currentUrl": safe_get_url(page),
    }

    if state["page"] == "space_wrapper":
        frame_courses = parse_course_list_from_frame(page, selectors.SPACE_WRAPPER_FRAME)
        data["space"] = {
            "userName": safe_get_element_text(page, selectors.SPACE_WRAPPER_USER_NAME),
            "courseMenuLinkId": selectors.SPACE_WRAPPER_COURSE_LINK,
            "courseFrameSrc": read_frame_src(page, selectors.SPACE_WRAPPER_FRAME),
            "frameCourseCount": len(frame_courses),
        }
        data["courseList"] = {
            "count": len(frame_courses),
            "courses": frame_courses[:10],
        }
    elif state["page"] == "course_list":
        courses = parse_course_list(page)
        data["courseList"] = {
            "count": len(courses),
            "courses": courses[:10],
        }
    elif state["page"] == "course_detail":
        wait_for_element(page, selectors.COURSE_PAGE_COURSE_ID, timeout_s=8.0)
        data["course"] = {
            "courseId": read_hidden_value(page, selectors.COURSE_PAGE_COURSE_ID),
            "clazzId": read_hidden_value(page, selectors.COURSE_PAGE_CLASS_ID),
            "cpi": read_hidden_value(page, selectors.COURSE_PAGE_CPI),
            "chapterIframeSrc": read_frame_src(page, selectors.COURSE_PAGE_CHAPTER_IFRAME),
        }
    elif state["page"] == "chapter_task":
        wait_for_element(page, selectors.CHAPTER_PAGE_COURSETREE, timeout_s=12.0)
        study_state_raw = read_hidden_value(page, selectors.CHAPTER_PAGE_STUDYSTATE)
        body_text = safe_get_element_text(page, selectors.CHAPTER_PAGE_PROGRESS_TEXT, retries=3, delay_s=0.2)
        chapter_outline = parse_chapter_outline(page)
        data["course"] = {
            "courseId": read_hidden_value(page, selectors.CHAPTER_PAGE_COURSE_ID),
            "clazzId": read_hidden_value(page, selectors.CHAPTER_PAGE_CLASS_ID),
            "chapterId": read_hidden_value(page, selectors.CHAPTER_PAGE_CHAPTER_ID),
            "activeNodeName": safe_get_element_text(page, selectors.CHAPTER_PAGE_ACTIVE_NODE),
            "studyStateRaw": study_state_raw,
            "studyState": parse_study_state(study_state_raw),
            "cardIframeSrc": read_frame_src(page, selectors.CHAPTER_PAGE_CARD_IFRAME),
            "chapterTreeReady": safe_has_element(page, selectors.CHAPTER_PAGE_COURSETREE, retries=2, delay_s=0.2),
            "searchInputReady": safe_has_element(page, selectors.CHAPTER_PAGE_SEARCH_INPUT, retries=2, delay_s=0.2),
            "bodyProgress": parse_progress_from_text(body_text),
            "chapterItemCount": chapter_outline["itemCount"],
            "chapterUnitCount": chapter_outline["unitCount"],
            "chapterPreview": chapter_outline["items"][:10],
        }
    elif state["page"] in {"study_page", "task_card", "video_attachment"}:
        data["taskPage"] = inspect_task_page(page)

    print_json(data)


def cmd_get_chapter_summary(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "chapter_task":
        print_json(
            {
                "ok": False,
                "command": "get-chapter-summary",
                "reason": "当前页面不是章节任务页",
                "pageState": state,
            }
        )
        return

    wait_for_element(page, selectors.CHAPTER_PAGE_COURSETREE, timeout_s=12.0)
    study_state_raw = read_hidden_value(page, selectors.CHAPTER_PAGE_STUDYSTATE)
    body_text = safe_get_element_text(page, selectors.CHAPTER_PAGE_PROGRESS_TEXT, retries=3, delay_s=0.2)
    chapter_outline = parse_chapter_outline(page)
    summary = {
        "activeNodeName": safe_get_element_text(page, selectors.CHAPTER_PAGE_ACTIVE_NODE),
        "studyStateRaw": study_state_raw,
        "studyState": parse_study_state(study_state_raw),
        "chapterTreeReady": safe_has_element(page, selectors.CHAPTER_PAGE_COURSETREE, retries=2, delay_s=0.2),
        "hasTaskCardIframe": safe_has_element(page, selectors.CHAPTER_PAGE_CARD_IFRAME, retries=2, delay_s=0.2),
        "hasNextChapterButton": safe_has_element(page, selectors.CHAPTER_PAGE_NEXT, retries=2, delay_s=0.2),
        "hasCompletedMarker": safe_has_element(page, selectors.CHAPTER_PAGE_COMPLETED, retries=2, delay_s=0.2),
        "hasUnfinishedMarker": safe_has_element(page, selectors.CHAPTER_PAGE_UNFINISHED, retries=2, delay_s=0.2),
        "hasSearchInput": safe_has_element(page, selectors.CHAPTER_PAGE_SEARCH_INPUT, retries=2, delay_s=0.2),
        "progressFromBodyText": parse_progress_from_text(body_text),
        "chapterItemCount": chapter_outline["itemCount"],
        "chapterUnitCount": chapter_outline["unitCount"],
        "chapterPreview": chapter_outline["items"][:10],
        "chapterUnitsPreview": chapter_outline["units"][:10],
    }

    print_json(
        {
            "ok": True,
            "command": "get-chapter-summary",
            "pageState": state,
            "summary": summary,
        }
    )


def cmd_list_chapters(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "chapter_task":
        print_json(
            {
                "ok": False,
                "command": "list-chapters",
                "reason": "当前页面不是章节任务页",
                "pageState": state,
            }
        )
        return

    wait_for_element(page, selectors.CHAPTER_PAGE_COURSETREE, timeout_s=12.0)
    chapter_outline = parse_chapter_outline(page)
    print_json(
        {
            "ok": True,
            "command": "list-chapters",
            "pageState": state,
            "itemCount": chapter_outline["itemCount"],
            "unitCount": chapter_outline["unitCount"],
            "items": chapter_outline["items"],
            "units": chapter_outline["units"],
        }
    )


def cmd_open_chapter_by_id(page: BridgePage, args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "chapter_task":
        print_json(
            {
                "ok": False,
                "command": "open-chapter-by-id",
                "reason": "当前页面不是章节任务页",
                "pageState": state,
            }
        )
        return

    wait_for_element(page, selectors.CHAPTER_PAGE_COURSETREE, timeout_s=12.0)
    chapter_outline = parse_chapter_outline(page)
    target = next((item for item in chapter_outline["items"] if item["chapterId"] == args.chapter_id), None)

    if not target:
        print_json(
            {
                "ok": False,
                "command": "open-chapter-by-id",
                "chapterId": args.chapter_id,
                "reason": "chapter not found",
            }
        )
        return

    dom_id = target.get("domId")
    if not dom_id:
        print_json(
            {
                "ok": False,
                "command": "open-chapter-by-id",
                "chapterId": args.chapter_id,
                "reason": "chapter dom id missing",
            }
        )
        return

    selector = f"#{dom_id}"
    onclick_meta = parse_to_old_onclick(target.get("onclick"))
    current_cpi = read_hidden_value(page, "#cpi") or load_runtime_state().get("cpi")
    current_enc = read_hidden_value(page, "#enc") or load_runtime_state().get("enc")
    if onclick_meta:
        merge_runtime_state(
            course_id=onclick_meta["courseId"],
            clazz_id=onclick_meta["clazzId"],
            chapter_id=onclick_meta["chapterId"],
            cpi=current_cpi,
            enc=current_enc,
            last_study_page_url=build_study_page_url(
                onclick_meta["courseId"],
                onclick_meta["chapterId"],
                onclick_meta["clazzId"],
                current_cpi,
                current_enc,
                onclick_meta["hideType"],
            ) if current_cpi and current_enc else None,
        )
    page.click_element(selector)
    print_json(
        {
            "ok": True,
            "command": "open-chapter-by-id",
            "chapter": target,
            "selector": selector,
            "onclickMeta": onclick_meta,
        }
    )


def cmd_inspect_task_page(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] not in {"study_page", "task_card", "video_attachment"}:
        print_json(
            {
                "ok": False,
                "command": "inspect-task-page",
                "reason": "当前页面不是学习页、任务卡页或视频附件页",
                "pageState": state,
            }
        )
        return

    payload = {
        "ok": True,
        "command": "inspect-task-page",
        "pageState": state,
        "currentUrl": safe_get_url(page),
        "taskPage": inspect_task_page(page),
    }
    if state["page"] == "task_card":
        payload["context"] = capture_context_from_task_card(page)
    elif state["page"] == "study_page":
        payload["context"] = capture_context_from_study_page(page)
    print_json(payload)


def cmd_return_to_study_page(page: BridgePage, _args: argparse.Namespace) -> None:
    result = goto_study_page_from_state(page)
    if detect_page_state(page)["page"] == "study_page":
        result["context"] = capture_context_from_study_page(page)
    print_json({"ok": True, "command": "return-to-study-page", **result})


def cmd_next_chapter(page: BridgePage, _args: argparse.Namespace) -> None:
    """从任意页面可靠跳转到下一章节。先回到学习页，再点击下一章节按钮。"""
    current_state = detect_page_state(page)
    if current_state["page"] != "study_page":
        result = goto_study_page_from_state(page)
        time.sleep(2)
        page.wait_for_load(20)
    else:
        result = {"targetUrl": safe_get_url(page), "pageState": current_state}

    state = detect_page_state(page)
    if state["page"] != "study_page":
        print_json(
            {
                "ok": False,
                "command": "next-chapter",
                "reason": "无法到达学习页",
                **result,
            }
        )
        return

    selectors_to_try = [
        ".nextChapter",
        "#prevNextFocusNext",
        ".jb_btn.jb_btn_92.fr.fs14.nextChapter",
        ".nextChapter a",
        "[onclick*='next']",
    ]
    clicked = None
    for selector in selectors_to_try:
        try:
            if page.has_element(selector):
                page.click_element(selector)
                clicked = selector
                break
        except Exception:
            pass
    if not clicked:
        print_json(
            {
                "ok": False,
                "command": "next-chapter",
                "reason": "未找到下一章节按钮",
                **result,
            }
        )
        return
    time.sleep(3)
    page.wait_for_load(20)
    new_state = detect_page_state(page)
    payload = {
        "ok": True,
        "command": "next-chapter",
        "clickedSelector": clicked,
        "pageState": new_state,
        "currentUrl": safe_get_url(page),
    }
    if new_state["page"] == "study_page":
        payload["context"] = capture_context_from_study_page(page)
    print_json(payload)


def cmd_auto_advance_step(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)

    if state["page"] == "task_card":
        context = capture_context_from_task_card(page)
        video_tasks = inspect_video_tasks(page)
        if video_tasks.get("videoTaskCount", 0) > 0:
            playback_state = get_video_playback_state(page)
            player_state = playback_state.get("playerState") or {}
            if player_state.get("ended"):
                print_json(
                    {
                        "ok": True,
                        "command": "auto-advance-step",
                        "action": "video_already_finished_wait_manual_progress_check",
                        "pageState": state,
                        "playbackState": playback_state,
                    }
                )
                return

            arm_video_guard(page)
            mute_video_task(page, True)
            play_result = play_video_task(page)
            playback_after = get_video_playback_state(page)
            print_json(
                {
                    "ok": True,
                    "command": "auto-advance-step",
                    "action": "video_playing",
                    "pageState": state,
                    "context": context,
                    "playResult": play_result,
                    "playbackState": playback_after,
                }
            )
            return

        task_page = context["taskPage"]
        body = task_page.get("bodyTextPreview") or ""
        blockers = []
        if any(key in body for key in ["作业", "测验", "考试", "题", "答题"]):
            blockers.append("quiz_or_assignment_detected")

        print_json(
            {
                "ok": True,
                "command": "auto-advance-step",
                "action": "blocked",
                "pageState": state,
                "context": context,
                "blockers": blockers,
            }
        )
        return

    if state["page"] == "study_page":
        context = capture_context_from_study_page(page)
        next_result = goto_task_card_from_study(page)
        print_json(
            {
                "ok": True,
                "command": "auto-advance-step",
                "action": "entered_task_card",
                "pageState": state,
                "context": context,
                "next": next_result,
            }
        )
        return

    if state["page"] == "chapter_task":
        chapter_outline = parse_chapter_outline(page)
        next_target = next((item for item in chapter_outline["items"] if (item.get("unfinishedTaskPoints") or 0) > 0), None)
        if not next_target:
            print_json(
                {
                    "ok": True,
                    "command": "auto-advance-step",
                    "action": "no_unfinished_chapter_found",
                    "pageState": state,
                }
            )
            return
        page.click_element(f"#{next_target['domId']}")
        page.wait_for_load(20)
        payload = {
            "ok": True,
            "command": "auto-advance-step",
            "action": "opened_unfinished_chapter",
            "pageState": detect_page_state(page),
            "chapter": next_target,
            "currentUrl": safe_get_url(page),
        }
        if detect_page_state(page)["page"] == "study_page":
            payload["context"] = capture_context_from_study_page(page)
        print_json(payload)
        return

    print_json(
        {
            "ok": False,
            "command": "auto-advance-step",
            "reason": "当前页面不支持自动推进",
            "pageState": state,
        }
    )


def goto_task_card_from_study(page: BridgePage) -> dict[str, Any]:
    context = capture_context_from_study_page(page)
    card_src = context.get("cardIframeSrc")
    current_url = context.get("currentUrl") or ""
    if not card_src:
        raise RuntimeError("学习页未找到任务卡 iframe")
    target_url = build_absolute_url(current_url, card_src)
    page.navigate(target_url)
    page.wait_for_load(20)
    capture_context_from_task_card(page)
    return {"targetUrl": target_url, "pageState": detect_page_state(page), "currentUrl": safe_get_url(page)}


def cmd_progress_guard(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] == "task_card":
        context = capture_context_from_task_card(page)
        task_page = context["taskPage"]
        video_tasks = inspect_video_tasks(page)
        has_video = video_tasks.get("videoTaskCount", 0) > 0
        player_state = get_video_playback_state(page) if has_video else None
        blockers = []
        if not has_video:
            body = task_page.get("bodyTextPreview") or ""
            if any(key in body for key in ["作业", "测验", "考试", "题", "答题"]):
                blockers.append("quiz_or_assignment_detected")
        print_json(
            {
                "ok": True,
                "command": "progress-guard",
                "pageState": state,
                "currentUrl": safe_get_url(page),
                "hasVideoTask": has_video,
                "videoTasks": video_tasks,
                "playbackState": player_state,
                "blockers": blockers,
            }
        )
        return

    if state["page"] == "study_page":
        context = capture_context_from_study_page(page)
        print_json(
            {
                "ok": True,
                "command": "progress-guard",
                "pageState": state,
                "currentUrl": safe_get_url(page),
                "context": context,
            }
        )
        return

    print_json(
        {
            "ok": False,
            "command": "progress-guard",
            "reason": "当前页面不是学习页或任务卡页",
            "pageState": state,
        }
    )


def cmd_inspect_video_tasks(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "task_card":
        print_json(
            {
                "ok": False,
                "command": "inspect-video-tasks",
                "reason": "当前页面不是任务卡页",
                "pageState": state,
            }
        )
        return

    print_json(
        {
            "ok": True,
            "command": "inspect-video-tasks",
            "pageState": state,
            "currentUrl": safe_get_url(page),
            "videoTasks": inspect_video_tasks(page),
        }
    )


def cmd_inspect_video_runtime(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "task_card":
        print_json(
            {
                "ok": False,
                "command": "inspect-video-runtime",
                "reason": "当前页面不是任务卡页",
                "pageState": state,
            }
        )
        return

    print_json(
        {
            "ok": True,
            "command": "inspect-video-runtime",
            "pageState": state,
            "currentUrl": safe_get_url(page),
            "videoRuntime": inspect_video_runtime(page),
        }
    )


def cmd_try_init_video_player(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "task_card":
        print_json(
            {
                "ok": False,
                "command": "try-init-video-player",
                "reason": "当前页面不是任务卡页",
                "pageState": state,
            }
        )
        return

    print_json(
        {
            "ok": True,
            "command": "try-init-video-player",
            "pageState": state,
            "currentUrl": safe_get_url(page),
            "result": try_init_video_player(page),
        }
    )


def cmd_get_video_playback_state(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "task_card":
        print_json(
            {
                "ok": False,
                "command": "get-video-playback-state",
                "reason": "当前页面不是任务卡页",
                "pageState": state,
            }
        )
        return

    print_json(
        {
            "ok": True,
            "command": "get-video-playback-state",
            "pageState": state,
            "currentUrl": safe_get_url(page),
            "state": get_video_playback_state(page),
        }
    )


def cmd_play_video_task(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "task_card":
        print_json(
            {
                "ok": False,
                "command": "play-video-task",
                "reason": "当前页面不是任务卡页",
                "pageState": state,
            }
        )
        return
    result = play_video_task(page)
    print_json({"ok": True, "command": "play-video-task", "result": result})


def cmd_pause_video_task(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "task_card":
        print_json(
            {
                "ok": False,
                "command": "pause-video-task",
                "reason": "当前页面不是任务卡页",
                "pageState": state,
            }
        )
        return
    result = pause_video_task(page)
    print_json({"ok": True, "command": "pause-video-task", "result": result})


def cmd_set_video_rate(page: BridgePage, args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "task_card":
        print_json(
            {
                "ok": False,
                "command": "set-video-rate",
                "reason": "当前页面不是任务卡页",
                "pageState": state,
            }
        )
        return
    result = set_video_rate(page, args.rate)
    print_json({"ok": True, "command": "set-video-rate", "result": result})


def cmd_mute_video_task(page: BridgePage, args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "task_card":
        print_json(
            {
                "ok": False,
                "command": "mute-video-task",
                "reason": "当前页面不是任务卡页",
                "pageState": state,
            }
        )
        return
    result = mute_video_task(page, args.muted)
    print_json({"ok": True, "command": "mute-video-task", "result": result})


def cmd_arm_video_guard(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "task_card":
        print_json(
            {
                "ok": False,
                "command": "arm-video-guard",
                "reason": "当前页面不是任务卡页",
                "pageState": state,
            }
        )
        return
    result = arm_video_guard(page)
    print_json({"ok": True, "command": "arm-video-guard", "result": result})


def cmd_disarm_video_guard(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] != "task_card":
        print_json(
            {
                "ok": False,
                "command": "disarm-video-guard",
                "reason": "当前页面不是任务卡页",
                "pageState": state,
            }
        )
        return
    result = disarm_video_guard(page)
    print_json({"ok": True, "command": "disarm-video-guard", "result": result})


def cmd_check_login(page: BridgePage, _args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    print_json(
        {
            "ok": True,
            "command": "check-login",
            "currentUrl": safe_get_url(page),
            **state,
        }
    )


def cmd_list_courses(page: BridgePage, _args: argparse.Namespace) -> None:
    """课程列表 — 缓存优先 + frame-snapshot + 导航兜底。

    三级回退：缓存命中 → frame 快照 → 导航到课程列表页。
    """
    t0 = time.time()
    state = detect_page_state(page)

    # 1. 缓存命中
    from xxt.cache import get_cached as cached, set_cache as cache_set
    cached_courses = cached("courseList")
    if cached_courses:
        print_json(
            _make_response(
                ok=True,
                command="list-courses",
                state=state["page"],
                data={"source": "cache", "count": len(cached_courses), "courses": cached_courses},
                elapsed_ms=_now_ms(t0),
            )
        )
        return

    # 2. frame-snapshot from #frame_content (most reliable)
    try:
        snapshot = page.frame_snapshot("#frame_content")
        if snapshot and isinstance(snapshot, dict) and snapshot.get("courseItems"):
            courses = parse_course_list_from_frame(page, "#frame_content")
            if courses:
                cache_set("courseList", courses, source="frame_snapshot")
                print_json(
                    _make_response(
                        ok=True,
                        command="list-courses",
                        state=state["page"],
                        data={"source": "frame_snapshot", "count": len(courses), "courses": courses},
                        elapsed_ms=_now_ms(t0),
                    )
                )
                return
    except Exception:
        pass

    # 3. 当前页面解析
    if state["page"] == "space_wrapper":
        courses = parse_course_list_from_frame(page, selectors.SPACE_WRAPPER_FRAME)
        if courses:
            cache_set("courseList", courses, source="space_wrapper_frame")
            print_json(
                _make_response(
                    ok=True,
                    command="list-courses",
                    state=state["page"],
                    data={"source": "space_wrapper_frame", "count": len(courses), "courses": courses},
                    elapsed_ms=_now_ms(t0),
                )
            )
            return
    elif state["page"] == "course_list":
        courses = parse_course_list(page)
        if courses:
            cache_set("courseList", courses, source="top_document")
            print_json(
                _make_response(
                    ok=True,
                    command="list-courses",
                    state=state["page"],
                    data={"source": "top_document", "count": len(courses), "courses": courses},
                    elapsed_ms=_now_ms(t0),
                )
            )
            return

    # 4. 导航兜底
    if page.has_element(selectors.HOME_PERSON_SPACE_ENTRY):
        page.click_element(selectors.HOME_PERSON_SPACE_ENTRY)
    else:
        page.navigate("https://i.chaoxing.com")
    page.wait_for_load(10)
    time.sleep(1)

    nav_state = detect_page_state(page)
    if nav_state["page"] == "space_wrapper":
        if page.has_element(selectors.SPACE_WRAPPER_COURSE_LINK):
            page.click_element(selectors.SPACE_WRAPPER_COURSE_LINK)
        page.wait_for_load(10)
        time.sleep(1)

    final_state = detect_page_state(page)
    if final_state["page"] in ("course_list", "space_wrapper"):
        courses = (
            parse_course_list_from_frame(page, selectors.SPACE_WRAPPER_FRAME)
            if final_state["page"] == "space_wrapper"
            else parse_course_list(page)
        )
        if courses:
            cache_set("courseList", courses, source="navigation_fallback")
            print_json(
                _make_response(
                    ok=True,
                    command="list-courses",
                    state=final_state["page"],
                    data={"source": "navigation_fallback", "count": len(courses), "courses": courses},
                    elapsed_ms=_now_ms(t0),
                )
            )
            return

    print_json(
        _make_response(
            ok=False,
            command="list-courses",
            state=state["page"],
            error_code="COURSE_LIST_UNAVAILABLE",
            error_message="无法获取课程列表 — 请执行 where-am-i 确认当前状态",
            elapsed_ms=_now_ms(t0),
        )
    )


def cmd_list_courses_from_frame(page: BridgePage, args: argparse.Namespace) -> None:
    """直接从指定 iframe 抓取课程列表，不依赖页面状态。"""
    t0 = time.time()
    selector = args.selector
    state = detect_page_state(page)

    from xxt.cache import set_cache as cache_set
    try:
        courses = parse_course_list_from_frame(page, selector)
        if not courses:
            raise RuntimeError("iframe 中未找到课程列表")
        cache_set("courseList", courses, source="frame_snapshot")
        print_json(
            _make_response(
                ok=True,
                command="list-courses-from-frame",
                state=state["page"],
                data={"selector": selector, "count": len(courses), "courses": courses},
                elapsed_ms=_now_ms(t0),
            )
        )
    except Exception as exc:
        print_json(
            _make_response(
                ok=False,
                command="list-courses-from-frame",
                state=state["page"],
                error_code="FRAME_SNAPSHOT_FAILED",
                error_message=str(exc)[:200],
                elapsed_ms=_now_ms(t0),
            )
        )


def cmd_get_progress(page: BridgePage, args: argparse.Namespace) -> None:
    """获取课程进度 — 缓存优先 + runtime_state 融合。

    四级回退：缓存命中 → 当前页 DOM → 导航到章节页 → runtime_state 部分数据。
    """
    t0 = time.time()
    state = detect_page_state(page)
    rt = load_runtime_state()

    from xxt.cache import get_cached as cached, set_cache as cache_set, get_cached_course_params

    # 1. 缓存命中 — 直接返回上次进度
    cached_progress = cached("lastProgress")
    if cached_progress and isinstance(cached_progress, dict):
        print_json(
            _make_response(
                ok=True,
                command="get-progress",
                state=state["page"],
                data={**cached_progress, "source": "cache"},
                elapsed_ms=_now_ms(t0),
            )
        )
        return

    # 2. 已在 chapter_task 页 — 直接读 DOM
    if state["page"] == "chapter_task":
        wait_for_element(page, selectors.CHAPTER_PAGE_COURSETREE, timeout_s=8.0)
        chapter_outline = parse_chapter_outline(page)
        body_text = safe_get_element_text(page, selectors.CHAPTER_PAGE_PROGRESS_TEXT, retries=2, delay_s=0.2)
        progress = parse_progress_from_text(body_text)
        chapters = _build_chapter_list(chapter_outline, rt)
        completed_ids = rt.get("completed_chapters", [])
        data = {
            "source": "page_dom",
            "overallProgress": progress,
            "completedChapters": len(completed_ids),
            "totalChapters": chapter_outline.get("itemCount", 0),
            "totalVideosWatched": rt.get("total_videos_watched", 0),
            "blockedItems": rt.get("blocked_items", []),
            "chapters": chapters[:20],
        }
        cache_set("lastProgress", data, source="page_dom")
        print_json(
            _make_response(
                ok=True,
                command="get-progress",
                state=state["page"],
                data=data,
                elapsed_ms=_now_ms(t0),
            )
        )
        return

    # 3. 不在 chapter_task → 尝试导航
    params = get_cached_course_params()
    course_id = args.course_id or params.get("courseId") if params else None or rt.get("course_id")
    if course_id:
        clazz_id = params.get("clazzId") if params and params.get("clazzId") else rt.get("clazz_id")
        cpi = params.get("cpi") if params else rt.get("cpi")
        if all([course_id, clazz_id, cpi]):
            chapter_task_url = (
                "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse"
                f"?courseid={course_id}&clazzid={clazz_id}&cpi={cpi}&ut=s"
            )
            page.navigate(chapter_task_url)
            page.wait_for_load(10)
            time.sleep(2)
            nav_state = detect_page_state(page)
            if nav_state["page"] == "chapter_task":
                wait_for_element(page, selectors.CHAPTER_PAGE_COURSETREE, timeout_s=8.0)
                chapter_outline = parse_chapter_outline(page)
                body_text = safe_get_element_text(page, selectors.CHAPTER_PAGE_PROGRESS_TEXT, retries=2, delay_s=0.2)
                progress = parse_progress_from_text(body_text)
                chapters = _build_chapter_list(chapter_outline, rt)
                completed_ids = rt.get("completed_chapters", [])
                data = {
                    "source": "navigation",
                    "overallProgress": progress,
                    "completedChapters": len(completed_ids),
                    "totalChapters": chapter_outline.get("itemCount", 0),
                    "totalVideosWatched": rt.get("total_videos_watched", 0),
                    "blockedItems": rt.get("blocked_items", []),
                    "chapters": chapters[:20],
                }
                cache_set("lastProgress", data, source="navigation")
                print_json(
                    _make_response(
                        ok=True,
                        command="get-progress",
                        state=nav_state["page"],
                        data=data,
                        elapsed_ms=_now_ms(t0),
                    )
                )
                return

    # 4. runtime_state 部分数据兜底
    completed_ids = rt.get("completed_chapters", [])
    if completed_ids or rt.get("total_videos_watched"):
        data = {
            "source": "runtime_state",
            "completedChapters": len(completed_ids),
            "totalVideosWatched": rt.get("total_videos_watched", 0),
            "blockedItems": rt.get("blocked_items", []),
            "note": "未连接页面，仅返回 runtime state 缓存数据"
        }
        print_json(
            _make_response(
                ok=True,
                command="get-progress",
                state=state["page"],
                data=data,
                elapsed_ms=_now_ms(t0),
            )
        )
        return

    # 5. 完全无数据
    print_json(
        _make_response(
            ok=False,
            command="get-progress",
            state=state["page"],
            error_code="NO_PROGRESS_DATA",
            error_message="无进度数据，请先执行 where-am-i 确认状态，再执行 run-course 或导航到章节页",
            elapsed_ms=_now_ms(t0),
        )
    )


def _build_chapter_list(chapter_outline: dict[str, Any], rt: dict[str, Any]) -> list[dict[str, Any]]:
    chapters = []
    for item in chapter_outline.get("items", []):
        chapter_id = item.get("chapterId")
        chapters.append(
            {
                "chapterId": chapter_id,
                "title": item.get("title"),
                "orderLabel": item.get("orderLabel"),
                "unfinishedTaskPoints": item.get("unfinishedTaskPoints"),
                "completed": chapter_id in rt.get("completed_chapters", []),
            }
        )
    return chapters


def cmd_navigate(page: BridgePage, args: argparse.Namespace) -> None:
    page.navigate(args.url)
    page.wait_for_load(20)
    time.sleep(1)
    state = detect_page_state(page)
    print_json(
        {
            "ok": True,
            "command": "navigate",
            "url": args.url,
            "pageState": state,
            "currentUrl": safe_get_url(page),
        }
    )


def cmd_open_course(page: BridgePage, args: argparse.Namespace) -> None:
    # 如果提供了 --url，直接导航（向后兼容）
    if args.url:
        page.navigate(args.url)
        page.wait_for_load(20)
        time.sleep(1)
        state = detect_page_state(page)
        print_json(
            _make_response(
                ok=True,
                command="open-course",
                state=state["page"],
                data={"courseId": args.course_id, "url": args.url},
            )
        )
        return

    clazz_id = args.clazz_id or load_runtime_state().get("clazz_id")
    if not clazz_id:
        print_json(
            {
                "ok": False,
                "command": "open-course",
                "courseId": args.course_id,
                "reason": "缺少 clazz-id，请提供 --clazz-id 参数或先执行 run-course 缓存参数",
            }
        )
        return

    url = (
        "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/stu"
        f"?courseid={args.course_id}&clazzid={clazz_id}"
    )
    page.navigate(url)
    page.wait_for_load(20)
    time.sleep(1)
    state = detect_page_state(page)

    # 尝试从页面提取 cpi 并缓存到 runtime state
    cpi = None
    try:
        cpi = read_hidden_value(page, selectors.COURSE_PAGE_CPI) or read_hidden_value(page, "#curcpi")
        if cpi:
            merge_runtime_state(course_id=args.course_id, clazz_id=clazz_id, cpi=cpi)
    except Exception:
        pass

    print_json(
        {
            "ok": True,
            "command": "open-course",
            "courseId": args.course_id,
            "clazzId": clazz_id,
            "cpi": cpi,
            "url": url,
            "pageState": state,
        }
    )


def cmd_follow_iframe(page: BridgePage, args: argparse.Namespace) -> None:
    src = read_frame_src(page, args.selector)
    if not src:
        print_json(
            {
                "ok": False,
                "command": "follow-iframe",
                "selector": args.selector,
                "reason": "iframe src not found",
            }
        )
        return

    current_url = page.get_url() or ""
    target_url = src
    if src.startswith("/"):
        if "://" not in current_url:
            raise RuntimeError("当前 URL 无法解析相对 iframe 地址")
        origin = current_url.split("/", 3)
        target_url = f"{origin[0]}//{origin[2]}{src}"

    page.navigate(target_url)
    print_json(
        {
            "ok": True,
            "command": "follow-iframe",
            "selector": args.selector,
            "targetUrl": target_url,
        }
    )


@timed_command
def cmd_go_to_course_list(page: BridgePage, _args: argparse.Namespace) -> None:
    """一步获取课程列表 — 缓存优先 + 单次导航，1-12s 返回。

    与旧版的区别：不再串行两次 click+wait，直接导航到个人空间从 iframe 解析。
    """
    t0 = time.time()
    state = detect_page_state(page)

    from xxt.cache import get_cached as cached, set_cache as cache_set

    # 1. 缓存命中 — 最快路径
    cached_courses = cached("courseList")
    if cached_courses:
        print_json(
            _make_response(
                ok=True,
                command="go-to-course-list",
                state=state["page"],
                data={"source": "cache", "count": len(cached_courses), "courses": cached_courses},
                elapsed_ms=_now_ms(t0),
            )
        )
        return

    # 2. 已在 course_list / space_wrapper → 直接解析（含空列表）
    if state["page"] == "course_list":
        courses = parse_course_list(page)
        cache_set("courseList", courses, source="course_list_page")
        print_json(
            _make_response(
                ok=True,
                command="go-to-course-list",
                state=state["page"],
                data={"source": "course_list_page", "count": len(courses), "courses": courses},
                elapsed_ms=_now_ms(t0),
            )
        )
        return

    if state["page"] == "space_wrapper":
        courses = parse_course_list_from_frame(page, selectors.SPACE_WRAPPER_FRAME)
        cache_set("courseList", courses, source="space_wrapper_frame")
        print_json(
            _make_response(
                ok=True,
                command="go-to-course-list",
                state=state["page"],
                data={"source": "space_wrapper_frame", "count": len(courses), "courses": courses},
                elapsed_ms=_now_ms(t0),
            )
        )
        return

    # 3. 不在目标页 → 单次导航到个人空间
    if page.has_element(selectors.HOME_PERSON_SPACE_ENTRY):
        page.click_element(selectors.HOME_PERSON_SPACE_ENTRY)
    else:
        page.navigate("https://i.chaoxing.com")
    page.wait_for_load(10)
    time.sleep(1)

    nav_state = detect_page_state(page)
    if nav_state["page"] in ("space_wrapper", "course_list"):
        courses = (
            parse_course_list_from_frame(page, selectors.SPACE_WRAPPER_FRAME)
            if nav_state["page"] == "space_wrapper"
            else parse_course_list(page)
        )
        if courses:
            cache_set("courseList", courses, source="navigation")
            print_json(
                _make_response(
                    ok=True,
                    command="go-to-course-list",
                    state=nav_state["page"],
                    data={"source": "navigation", "count": len(courses), "courses": courses},
                    elapsed_ms=_now_ms(t0),
                )
            )
            return

    # 4. 失败 — 不返回 allowedActions，避免自引用循环
    print_json(
        _make_response(
            ok=False,
            command="go-to-course-list",
            state=nav_state["page"],
            error_code="COURSE_LIST_UNAVAILABLE",
            error_message="无法获取课程列表 — 请确认已登录学习通并执行 where-am-i",
            elapsed_ms=_now_ms(t0),
        )
    )


def cmd_open_course_by_id(page: BridgePage, args: argparse.Namespace) -> None:
    state = detect_page_state(page)
    if state["page"] == "space_wrapper":
        courses = parse_course_list_from_frame(page, selectors.SPACE_WRAPPER_FRAME)
    elif state["page"] == "course_list":
        courses = parse_course_list(page)
    else:
        print_json(
            {
                "ok": False,
                "command": "open-course-by-id",
                "reason": "当前页面不是课程列表页或课程外壳页",
                "pageState": state,
            }
        )
        return

    target = next((item for item in courses if item["courseId"] == args.course_id), None)
    if not target or not target.get("href"):
        print_json(
            {
                "ok": False,
                "command": "open-course-by-id",
                "courseId": args.course_id,
                "reason": "course not found",
            }
        )
        return

    page.navigate(target["href"])
    print_json(
        {
            "ok": True,
            "command": "open-course-by-id",
            "course": target,
        }
    )


def cmd_debug_tabs(page: BridgePage, _args: argparse.Namespace) -> None:
    print_json(
        {
            "ok": True,
            "command": "debug-tabs",
            "tabs": page.debug_tabs(),
        }
    )


def cmd_frame_snapshot(page: BridgePage, args: argparse.Namespace) -> None:
    print_json(
        {
            "ok": True,
            "command": "frame-snapshot",
            "snapshot": page.frame_snapshot(args.selector),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="XXT CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check-login")
    sub.add_parser("where-am-i")
    sub.add_parser("go-to-course-list")
    sub.add_parser("list-courses")
    sub.add_parser("list-courses-from-frame").add_argument("--selector", required=True)
    sub.add_parser("get-current-context")
    sub.add_parser("get-chapter-summary")
    sub.add_parser("list-chapters")
    sub.add_parser("inspect-task-page")
    sub.add_parser("inspect-video-tasks")
    sub.add_parser("inspect-video-runtime")
    sub.add_parser("try-init-video-player")
    sub.add_parser("get-video-playback-state")
    sub.add_parser("play-video-task")
    sub.add_parser("pause-video-task")
    sub.add_parser("arm-video-guard")
    sub.add_parser("disarm-video-guard")
    sub.add_parser("return-to-study-page")
    sub.add_parser("next-chapter")
    sub.add_parser("progress-guard")
    sub.add_parser("auto-advance-step")
    sub.add_parser("go-next-task-point")
    sub.add_parser("request-pause")
    sub.add_parser("get-loop-status")

    progress = sub.add_parser("get-progress")
    progress.add_argument("--course-id", default=None)

    sub.add_parser("navigate").add_argument("--url", required=True)

    open_course = sub.add_parser("open-course")
    open_course.add_argument("--course-id", required=True)
    open_course.add_argument("--clazz-id", default=None)
    open_course.add_argument("--url", default=None)

    follow_iframe = sub.add_parser("follow-iframe")
    follow_iframe.add_argument("--selector", required=True)

    open_course_by_id = sub.add_parser("open-course-by-id")
    open_course_by_id.add_argument("--course-id", required=True)

    open_chapter_by_id = sub.add_parser("open-chapter-by-id")
    open_chapter_by_id.add_argument("--chapter-id", required=True)

    set_video_rate_cmd = sub.add_parser("set-video-rate")
    set_video_rate_cmd.add_argument("--rate", type=float, required=True)

    mute_video_task_cmd = sub.add_parser("mute-video-task")
    mute_video_task_cmd.add_argument("--muted", action="store_true")

    sub.add_parser("debug-tabs")

    frame_snapshot = sub.add_parser("frame-snapshot")
    frame_snapshot.add_argument("--selector", required=True)

    run_course_cmd = sub.add_parser("run-course")
    run_course_cmd.add_argument("--course-id", required=True)
    run_course_cmd.add_argument("--clazz-id", required=True)
    run_course_cmd.add_argument("--cpi", required=True)
    run_course_cmd.add_argument("--enc", default=None)
    run_course_cmd.add_argument("--max-chapters", type=int, default=None)

    wait_video_cmd = sub.add_parser("wait-video-end")
    wait_video_cmd.add_argument("--timeout", type=float, default=1800)
    wait_video_cmd.add_argument("--interval", type=float, default=3.0)

    return parser


def _is_bridge_running(port: int = 9333, timeout: float = 0.3) -> bool:
    """快速探测 bridge server 是否已在监听。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def _ensure_bridge(port: int = 9333, startup_wait: float = 3.0) -> None:
    """确保 bridge server 在运行，未运行时自动启动。

    零配置原则：用户无需手动启动 bridge server。
    首次调用时 subprocess 后台拉起，后续调用检测到已运行则直接跳过。
    """
    if _is_bridge_running(port):
        return

    script_dir = Path(__file__).resolve().parent
    bridge_py = script_dir / "bridge_server.py"
    if not bridge_py.exists():
        print_json(_make_response(
            ok=False, command="_ensure_bridge",
            error_code="BRIDGE_NOT_FOUND",
            error_message=f"找不到 bridge_server.py: {bridge_py}",
        ))
        sys.exit(1)

    # 后台启动，不弹黑窗
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    subprocess.Popen([sys.executable, str(bridge_py), "--port", str(port)], **kwargs)

    # 等待就绪
    deadline = time.time() + startup_wait
    while time.time() < deadline:
        if _is_bridge_running(port):
            return
        time.sleep(0.15)

    print_json(_make_response(
        ok=False, command="_ensure_bridge",
        error_code="BRIDGE_STARTUP_TIMEOUT",
        error_message=f"Bridge server 启动超时 ({startup_wait}s) — 请手动执行 python scripts/bridge_server.py",
    ))
    sys.exit(1)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    _ensure_bridge()
    page = BridgePage()

    if args.command == "navigate":
        cmd_navigate(page, args)
    elif args.command == "check-login":
        cmd_check_login(page, args)
    elif args.command == "where-am-i":
        cmd_where_am_i(page, args)
    elif args.command == "go-to-course-list":
        cmd_go_to_course_list(page, args)
    elif args.command == "list-courses":
        cmd_list_courses(page, args)
    elif args.command == "list-courses-from-frame":
        cmd_list_courses_from_frame(page, args)
    elif args.command == "get-progress":
        cmd_get_progress(page, args)
    elif args.command == "open-course":
        cmd_open_course(page, args)
    elif args.command == "get-current-context":
        cmd_get_current_context(page, args)
    elif args.command == "get-chapter-summary":
        cmd_get_chapter_summary(page, args)
    elif args.command == "list-chapters":
        cmd_list_chapters(page, args)
    elif args.command == "inspect-task-page":
        cmd_inspect_task_page(page, args)
    elif args.command == "inspect-video-tasks":
        cmd_inspect_video_tasks(page, args)
    elif args.command == "inspect-video-runtime":
        cmd_inspect_video_runtime(page, args)
    elif args.command == "try-init-video-player":
        cmd_try_init_video_player(page, args)
    elif args.command == "get-video-playback-state":
        cmd_get_video_playback_state(page, args)
    elif args.command == "play-video-task":
        cmd_play_video_task(page, args)
    elif args.command == "pause-video-task":
        cmd_pause_video_task(page, args)
    elif args.command == "set-video-rate":
        cmd_set_video_rate(page, args)
    elif args.command == "mute-video-task":
        cmd_mute_video_task(page, args)
    elif args.command == "arm-video-guard":
        cmd_arm_video_guard(page, args)
    elif args.command == "disarm-video-guard":
        cmd_disarm_video_guard(page, args)
    elif args.command == "return-to-study-page":
        cmd_return_to_study_page(page, args)
    elif args.command == "next-chapter":
        cmd_next_chapter(page, args)
    elif args.command == "progress-guard":
        cmd_progress_guard(page, args)
    elif args.command == "auto-advance-step":
        cmd_auto_advance_step(page, args)
    elif args.command == "follow-iframe":
        cmd_follow_iframe(page, args)
    elif args.command == "open-course-by-id":
        cmd_open_course_by_id(page, args)
    elif args.command == "open-chapter-by-id":
        cmd_open_chapter_by_id(page, args)
    elif args.command == "debug-tabs":
        cmd_debug_tabs(page, args)
    elif args.command == "frame-snapshot":
        cmd_frame_snapshot(page, args)
    elif args.command == "wait-video-end":
        cmd_wait_video_end(page, args)
    elif args.command == "go-next-task-point":
        cmd_go_next_task_point(page, args)
    elif args.command == "request-pause":
        cmd_request_pause(page, args)
    elif args.command == "get-loop-status":
        cmd_get_loop_status(page, args)
    elif args.command == "run-course":
        cmd_run_course(page, args)


if __name__ == "__main__":
    main()
