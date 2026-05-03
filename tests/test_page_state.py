from xxt.page_state import detect_page_state


class FakePage:
    def __init__(self, present=None, text=None, url=None):
        self.present = present or set()
        self.text = text or {}
        self.url = url

    def has_element(self, selector: str) -> bool:
        return selector in self.present

    def get_element_text(self, selector: str):
        return self.text.get(selector)

    def get_url(self):
        return self.url


def test_detect_login_page():
    page = FakePage(present={"#uunnmm"})
    state = detect_page_state(page)
    assert state["page"] == "login"
    assert state["loggedIn"] is False


def test_detect_space_wrapper_page():
    page = FakePage(
        present={"#frame_content", "#zne_kc_icon"},
        text={".personalInfor .personalName": "张靖"},
    )
    state = detect_page_state(page)
    assert state["page"] == "space_wrapper"
    assert state["loggedIn"] is True
    assert state["userName"] == "张靖"


def test_detect_course_detail_page():
    page = FakePage(present={"#courseid", "#frame_content-zj"})
    state = detect_page_state(page)
    assert state["page"] == "course_detail"


def test_detect_chapter_task_page():
    page = FakePage(present={"body", "#coursetree, .chapter_body"})
    state = detect_page_state(page)
    assert state["page"] == "chapter_task"


def test_detect_chapter_task_page_from_url():
    page = FakePage(url="https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid=1")
    state = detect_page_state(page)
    assert state["page"] == "chapter_task"


def test_detect_study_page_from_url():
    page = FakePage(url="https://mooc1.chaoxing.com/mycourse/studentstudy?chapterId=1")
    state = detect_page_state(page)
    assert state["page"] == "study_page"


def test_detect_task_card_page_from_url():
    page = FakePage(url="https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?courseid=1")
    state = detect_page_state(page)
    assert state["page"] == "task_card"


def test_detect_video_attachment_page_from_url():
    page = FakePage(url="https://mooc1.chaoxing.com/ananas/modules/video/index.html?v=1")
    state = detect_page_state(page)
    assert state["page"] == "video_attachment"
