from __future__ import annotations

import json
from typing import Any


class BridgePage:
    DEFAULT_TIMEOUT = 10  # seconds — short timeout avoids OpenClaw SIGKILL

    def __init__(self, bridge_url: str = "ws://localhost:9333") -> None:
        self._bridge_url = bridge_url
        self._timeout = self.DEFAULT_TIMEOUT

    def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        import websockets.sync.client as ws_client

        msg: dict[str, Any] = {"role": "cli", "method": method}
        if params:
            msg["params"] = params

        with ws_client.connect(self._bridge_url, max_size=20 * 1024 * 1024) as ws:
            ws.send(json.dumps(msg, ensure_ascii=False))
            raw = ws.recv(timeout=self._timeout)

        resp = json.loads(raw)
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return resp.get("result")

    def navigate(self, url: str) -> None:
        self._call("navigate", {"url": url})

    def wait_for_load(self, timeout: float = 30.0) -> None:
        self._call("wait_for_load", {"timeout": int(timeout * 1000)})

    def click_element(self, selector: str) -> None:
        self._call("click_element", {"selector": selector})

    def input_text(self, selector: str, text: str) -> None:
        self._call("input_text", {"selector": selector, "text": text})

    def evaluate(self, expression: str) -> Any:
        return self._call("evaluate", {"expression": expression})

    def has_element(self, selector: str) -> bool:
        return bool(self._call("has_element", {"selector": selector}))

    def get_element_text(self, selector: str) -> str | None:
        return self._call("get_element_text", {"selector": selector})

    def get_element_attribute(self, selector: str, attr: str) -> str | None:
        return self._call("get_element_attribute", {"selector": selector, "attr": attr})

    def get_url(self) -> str | None:
        return self._call("get_url")

    def debug_tabs(self) -> Any:
        return self._call("debug_tabs")

    def frame_snapshot(self, selector: str) -> Any:
        return self._call("frame_snapshot", {"selector": selector})

    def frame_evaluate(self, selector: str, expression: str) -> Any:
        return self._call("frame_evaluate", {"selector": selector, "expression": expression})

    def query_elements(self, selector: str, limit: int = 20, attrs: list[str] | None = None) -> Any:
        return self._call(
            "query_elements",
            {"selector": selector, "limit": limit, "attrs": attrs or []},
        )

    def run_course(self, course_id: str, clazz_id: str, cpi: str = "") -> Any:
        """触发 MAIN world 内自循环刷课, 立即返回"""
        return self._call("run_course", {"courseId": course_id, "clazzId": clazz_id, "cpi": cpi})

    def request_pause(self) -> None:
        """请求暂停刷课"""
        self._call("request_pause")

    def get_study_status(self) -> Any:
        """获取刷课状态 (active/courseId/url)"""
        return self._call("get_study_status")
