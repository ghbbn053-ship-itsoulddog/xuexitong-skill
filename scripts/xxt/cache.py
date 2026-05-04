"""缓存层 — 加速重复查询，减少浏览器 DOM 读次数。

每条缓存带 updatedAt / source / ttl，查询先读缓存，过期后按需刷新。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

CACHE_FILE = Path(__file__).resolve().parent.parent / ".cache.json"

DEFAULT_TTL: dict[str, int] = {
    "courseList": 300,       # 5 min
    "courseParams": 600,     # 10 min
    "lastProgress": 30,      # 30 sec — 进度变化快
    "lastPageState": 60,     # 1 min
}


def _load_cache() -> dict[str, Any]:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CACHE_FILE)


def get_cached(key: str) -> Any | None:
    """读缓存，TTL 内返回 data，过期或不存在返回 None。"""
    cache = _load_cache()
    entry = cache.get(key)
    if not entry or not isinstance(entry, dict):
        return None
    ttl = entry.get("ttl", DEFAULT_TTL.get(key, 300))
    updated_at = entry.get("updatedAt", 0)
    if time.time() - updated_at > ttl:
        return None
    return entry.get("data")


def set_cache(key: str, data: Any, source: str = "unknown", ttl: int | None = None) -> None:
    """写缓存。"""
    cache = _load_cache()
    cache[key] = {
        "data": data,
        "updatedAt": time.time(),
        "source": source,
        "ttl": ttl if ttl is not None else DEFAULT_TTL.get(key, 300),
    }
    _save_cache(cache)


def invalidate_cache(key: str) -> None:
    """失效指定缓存键。"""
    cache = _load_cache()
    cache.pop(key, None)
    _save_cache(cache)


def get_cached_course_params() -> dict[str, Any] | None:
    """快捷方法：获取缓存的课程参数。"""
    return get_cached("courseParams")
