from __future__ import annotations

from typing import Any, Protocol

from . import selectors


class PageLike(Protocol):
    def has_element(self, selector: str) -> bool: ...
    def get_element_text(self, selector: str): ...
    def get_url(self) -> str | None: ...


def _safe_get_url(page: PageLike) -> str | None:
    try:
        return page.get_url()
    except Exception:
        return None


def detect_page_state(page: PageLike) -> dict[str, Any]:
    url = _safe_get_url(page) or ""

    if "/ananas/modules/video/index.html" in url:
        return {
            "page": "video_attachment",
            "loggedIn": True,
            "canEnterSpace": True,
        }

    if "/mooc-ans/knowledge/cards" in url:
        return {
            "page": "task_card",
            "loggedIn": True,
            "canEnterSpace": True,
        }

    if "/mycourse/studentstudy" in url:
        return {
            "page": "study_page",
            "loggedIn": True,
            "canEnterSpace": True,
        }

    if "/mooc2-ans/mycourse/studentcourse" in url:
        return {
            "page": "chapter_task",
            "loggedIn": True,
            "canEnterSpace": True,
        }

    if "/mooc2-ans/mycourse/stu" in url:
        return {
            "page": "course_detail",
            "loggedIn": True,
            "canEnterSpace": True,
        }

    try:
        if page.has_element(selectors.LOGIN_USER_INPUT) or page.has_element(selectors.LOGIN_PASSWORD_INPUT):
            return {
                "page": "login",
                "loggedIn": False,
                "canEnterSpace": False,
            }
    except Exception:
        pass

    try:
        if page.has_element(selectors.SPACE_WRAPPER_FRAME) and page.has_element(selectors.SPACE_WRAPPER_COURSE_LINK):
            return {
                "page": "space_wrapper",
                "loggedIn": True,
                "canEnterSpace": True,
                "userName": page.get_element_text(selectors.SPACE_WRAPPER_USER_NAME),
            }
    except Exception:
        pass

    try:
        if page.has_element(selectors.COURSE_LIST_ROOT) and page.has_element(selectors.COURSE_LIST_ITEM):
            return {
                "page": "course_list",
                "loggedIn": True,
                "canEnterSpace": True,
            }
    except Exception:
        pass

    try:
        if page.has_element(selectors.CHAPTER_PAGE_BODY) and page.has_element(selectors.CHAPTER_PAGE_COURSETREE):
            return {
                "page": "chapter_task",
                "loggedIn": True,
                "canEnterSpace": True,
            }
    except Exception:
        pass

    try:
        if page.has_element(selectors.COURSE_PAGE_COURSE_ID) and page.has_element(selectors.COURSE_PAGE_CHAPTER_IFRAME):
            return {
                "page": "course_detail",
                "loggedIn": True,
                "canEnterSpace": True,
            }
    except Exception:
        pass

    try:
        if page.has_element(selectors.SPACE_SITE_NAME):
            return {
                "page": "personal_space",
                "loggedIn": True,
                "canEnterSpace": True,
                "siteName": page.get_element_text(selectors.SPACE_SITE_NAME),
            }
    except Exception:
        pass

    try:
        if page.has_element(selectors.HOME_USER_NAME):
            prompt = page.get_element_text(selectors.HOME_NO_PERMISSION_PROMPT)
            return {
                "page": "home_after_login",
                "loggedIn": True,
                "canEnterSpace": page.has_element(selectors.HOME_PERSON_SPACE_ENTRY),
                "prompt": prompt,
                "userName": page.get_element_text(selectors.HOME_USER_NAME),
            }
    except Exception:
        pass

    return {
        "page": "unknown",
        "loggedIn": False,
        "canEnterSpace": False,
    }
