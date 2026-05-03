from __future__ import annotations

import argparse
import json
import time
from typing import Any

from xxt.bridge import BridgePage
from xxt.page_state import detect_page_state
from xxt import selectors
from cli import (
    inspect_task_page,
    inspect_video_runtime,
    inspect_video_tasks,
    parse_chapter_outline,
    read_frame_src,
    safe_get_element_attribute,
    safe_get_url,
    try_init_video_player,
)


# ⚠️ 使用前改为你自己的真实课程 URL
DEFAULT_CHAPTER_TASK_URL = (
    "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse"
    "?courseid=YOUR_COURSE_ID&clazzid=YOUR_CLAZZ_ID&cpi=YOUR_CPI&ut=s"
    "&t=REPLACE_WITH_TIMESTAMP&stuenc=REPLACE_WITH_STUENC"
)


def build_absolute_url(current_url: str, src: str) -> str:
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if src.startswith("/"):
        origin = current_url.split("/", 3)
        return f"{origin[0]}//{origin[2]}{src}"
    return src


def run_eval(chapter_task_url: str, chapter_id: str | None) -> dict[str, Any]:
    page = BridgePage()
    report: dict[str, Any] = {
        "startedAt": int(time.time()),
        "input": {
            "chapterTaskUrl": chapter_task_url,
            "chapterId": chapter_id,
        },
        "steps": [],
        "checks": {},
    }

    def add_step(name: str, **payload: Any) -> None:
        report["steps"].append({"step": name, **payload})

    page.navigate(chapter_task_url)
    page.wait_for_load(20)
    chapter_state = detect_page_state(page)
    add_step("chapter_task_loaded", pageState=chapter_state, url=safe_get_url(page))

    chapter_outline = parse_chapter_outline(page)
    selected = None
    if chapter_id:
        selected = next((item for item in chapter_outline["items"] if item["chapterId"] == chapter_id), None)
    elif chapter_outline["items"]:
        selected = chapter_outline["items"][0]

    add_step(
        "chapter_outline",
        itemCount=chapter_outline["itemCount"],
        unitCount=chapter_outline["unitCount"],
        firstItems=chapter_outline["items"][:5],
        selectedChapter=selected,
    )

    if not selected or not selected.get("domId"):
        raise RuntimeError("未能选出可测试章节")

    page.click_element(f"#{selected['domId']}")
    page.wait_for_load(20)
    study_state = detect_page_state(page)
    study_url = safe_get_url(page)
    study_context = {
        "courseId": safe_get_element_attribute(page, selectors.CHAPTER_PAGE_COURSE_ID, "value"),
        "clazzId": safe_get_element_attribute(page, selectors.CHAPTER_PAGE_CLASS_ID, "value"),
        "chapterId": safe_get_element_attribute(page, selectors.CHAPTER_PAGE_CHAPTER_ID, "value"),
        "activeNodeName": page.get_element_text(selectors.CHAPTER_PAGE_ACTIVE_NODE),
        "cardIframeSrc": read_frame_src(page, selectors.CHAPTER_PAGE_CARD_IFRAME),
    }
    add_step("study_page_loaded", pageState=study_state, url=study_url, context=study_context)

    card_src = study_context["cardIframeSrc"]
    if not card_src:
        raise RuntimeError("学习页未找到任务卡 iframe")

    page.navigate(build_absolute_url(study_url or "", card_src))
    page.wait_for_load(20)
    task_card_state = detect_page_state(page)
    task_card_url = safe_get_url(page)
    task_page = inspect_task_page(page)
    video_tasks = inspect_video_tasks(page)
    add_step(
        "task_card_loaded",
        pageState=task_card_state,
        url=task_card_url,
        taskPage=task_page,
        videoTasks=video_tasks,
    )

    video_runtime = inspect_video_runtime(page)
    add_step("video_runtime", runtime=video_runtime)

    playback_result = try_init_video_player(page)
    add_step("video_playback_attempt", result=playback_result)

    before = ((playback_result or {}).get("before") or {})
    after = ((playback_result or {}).get("after") or {})
    before_time = before.get("playerCurrentTime") or before.get("domCurrentTime") or 0
    after_time = after.get("playerCurrentTime") or after.get("domCurrentTime") or 0
    paused_after = after.get("playerPaused")
    if paused_after is None:
        paused_after = after.get("domPaused")

    report["checks"] = {
        "chapterTaskDetected": chapter_state.get("page") == "chapter_task",
        "chapterListParsed": chapter_outline["itemCount"] > 0,
        "studyPageOpened": study_state.get("page") == "study_page",
        "taskCardOpened": task_card_state.get("page") == "task_card",
        "videoTaskDetected": video_tasks.get("videoTaskCount", 0) > 0,
        "videoRuntimeAccessible": bool(video_runtime.get("accessible")),
        "videoDomFound": len(video_runtime.get("videoElements", [])) > 0,
        "videoPlayerFound": bool((video_runtime.get("globals") or {}).get("videojsPlayerKeys")),
        "videoPlaybackAdvanced": after_time > before_time,
        "videoPlayingAfterAttempt": paused_after is False,
    }
    report["summary"] = {
        "selectedChapter": selected,
        "beforeTime": before_time,
        "afterTime": after_time,
        "timeAdvancedBy": after_time - before_time,
    }
    report["finishedAt"] = int(time.time())
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an end-to-end smoke evaluation")
    parser.add_argument("--chapter-task-url", default=DEFAULT_CHAPTER_TASK_URL)
    parser.add_argument("--chapter-id", default=None)
    args = parser.parse_args()

    report = run_eval(args.chapter_task_url, args.chapter_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
