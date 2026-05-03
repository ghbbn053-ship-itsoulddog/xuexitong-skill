from scripts.cli import read_frame_src


class FakePage:
    def __init__(self, attrs=None):
        self.attrs = attrs or {}

    def get_element_attribute(self, selector: str, attr: str):
        return self.attrs.get((selector, attr))


def test_read_frame_src_returns_src_attribute():
    page = FakePage({("#frame_content", "src"): "https://example.com/course"})
    assert read_frame_src(page, "#frame_content") == "https://example.com/course"
