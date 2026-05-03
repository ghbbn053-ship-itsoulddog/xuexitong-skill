from scripts.cli import parse_chapter_item_id, parse_task_points, parse_task_points_from_item


def test_parse_chapter_item_id_extracts_numeric_id():
    assert parse_chapter_item_id("cur1118917598") == "1118917598"


def test_parse_chapter_item_id_returns_none_for_invalid_value():
    assert parse_chapter_item_id("chapter-1") is None


def test_parse_task_points_extracts_pending_points():
    assert parse_task_points("22个待完成任务点") == 22


def test_parse_task_points_returns_none_when_missing():
    assert parse_task_points("已完成") is None


def test_parse_task_points_from_item_prefers_hover_text():
    item = {
        "taskText": "22个待完成任务点",
        "hoverTaskText": "2个待完成任务点",
        "pointsText": "2",
        "knowledgeJobCount": "2",
    }
    assert parse_task_points_from_item(item) == 2


def test_parse_task_points_from_item_falls_back_to_hidden_count():
    item = {
        "taskText": None,
        "hoverTaskText": None,
        "knowledgeJobCount": "3",
    }
    assert parse_task_points_from_item(item) == 3
