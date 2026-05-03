"""已知页面选择器。

这些选择器来自你提供的 HTML，后续拿到课程列表页后再继续补充。
"""

LOGIN_USER_INPUT = "#uunnmm"
LOGIN_PASSWORD_INPUT = "#pwd"
LOGIN_BUTTON = "#login"
LOGIN_TAB_ITEMS = ".login-area .tab li"
LOGIN_QR_IFRAME = "#iframe"
LOGIN_CAPTCHA = "#captcha"

HOME_USER_NAME = ".school-header .user-mes h3"
HOME_PERSON_PHOTO = ".school-header .user-photo img"
HOME_PERSON_SPACE_ENTRY = "#showPrompt a[href*='i.chaoxing.com']"
HOME_NO_PERMISSION_PROMPT = "#showPrompt"

SPACE_SITE_NAME = "#siteName"
SPACE_USER_ICON = ".nav .user img.icon-head"
SPACE_COURSE_MENU = "#first2444618"
SPACE_WRAPPER_COURSE_LINK = "#zne_kc_icon"
SPACE_WRAPPER_FRAME = "#frame_content"
SPACE_WRAPPER_USER_NAME = ".personalInfor .personalName"

COURSE_LIST_ROOT = "#courseList"
COURSE_LIST_ITEM = "#courseList li.course"
COURSE_LIST_LINK = "a.color1"
COURSE_LIST_NAME = ".course-name"
COURSE_LIST_TEACHER = ".line2"

COURSE_PAGE_COURSE_ID = "#courseid"
COURSE_PAGE_CLASS_ID = "#clazzid"
COURSE_PAGE_CPI = "#cpi"
COURSE_PAGE_CHAPTER_IFRAME = "#frame_content-zj"
COURSE_PAGE_SECTION_TAB = 'a[title="章节"]'

CHAPTER_PAGE_BODY = "body"
CHAPTER_PAGE_COURSE_ID = "#curCourseId, #courseId"
CHAPTER_PAGE_CLASS_ID = "#curClazzId, #clazzId"
CHAPTER_PAGE_CHAPTER_ID = "#curChapterId, #chapterId"
CHAPTER_PAGE_CARD_IFRAME = "#iframe[info='card']"
CHAPTER_PAGE_COURSETREE = "#coursetree, .chapter_body"
CHAPTER_PAGE_STUDYSTATE = "#_studystate"
CHAPTER_PAGE_ACTIVE_NODE = ".posCatalog_active .posCatalog_name, .chapter_item.active .catalog_name, .chapter_item.curr .catalog_name"
CHAPTER_PAGE_NODE_NAME = ".posCatalog_name"
CHAPTER_PAGE_COMPLETED = ".icon_Completed"
CHAPTER_PAGE_UNFINISHED = ".catalog_points_yi"
CHAPTER_PAGE_NEXT = ".nextChapter"
CHAPTER_PAGE_PROGRESS_TEXT = ".chapter_head, body"
CHAPTER_PAGE_SEARCH_INPUT = "#searchChapterListByName"
CHAPTER_PAGE_LIST_COUNTER = "#countListSearchChapter"
