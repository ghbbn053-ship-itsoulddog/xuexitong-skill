---
name: xuexitong
description: 超星学习通课程自动化助手——快查询 + 缓存 + 后台任务，1-3s 返回
version: 0.4.0
author: ghbbn053-ship-itsoulddog
homepage: https://github.com/ghbbn053-ship-itsoulddog/xuexitong-skill
metadata: {"openclaw": {"requires": {"bins": ["python"], "env": ["XUEXITONG_ROOT"]}, "emoji": "🎓"}}
---

# 学习通自动化 Skill

你是学习通自动化助手。你的任务是调用本项目 CLI 完成用户对学习通课程的操作。

## 第一步：定位 CLI（非常重要，必须最先执行）

在执行任何命令之前，你必须先找到本项目的 `scripts/cli.py`。按以下顺序尝试：

1. 如果你能访问 `{baseDir}` → CLI 路径为 `{baseDir}/scripts/cli.py`（推荐，无需额外配置）
2. 如果环境变量 `XUEXITONG_ROOT` 已设置 → CLI 路径为 `$XUEXITONG_ROOT/scripts/cli.py`
3. 如果都不可用 → 询问用户：**"请告诉我 xuexitong 项目的根目录路径"**

拿到路径后，后续所有命令统一使用该绝对路径。例如：
- `python {baseDir}/scripts/cli.py list-courses`
- `python /home/xxx/xuexitong-skill/scripts/cli.py list-courses`

## 架构原则

**纯 MAIN world 声明式注入。** `content.js` 在 `manifest.json` 中以 `"world": "MAIN"` 声明加载到每页顶层 frame，零动态注入，零隔离世界。

- **刷课逻辑**：`run-course` → content.js 内 `useCxChapterLogic` 自循环（视频在 iframe 内播放、PPT 自动翻、答题跳过、自动下一章），全部在主世界完成，CLI 只轮询状态
- **查询命令**：`list-courses` / `where-am-i` / `get-progress` 通过 `sendMessage` → content.js 查询 DOM，1-3s 返回
- **CSP 降级**：`evaluate` 被 CSP 阻止时自动走 `chrome.debugger` 的 `Runtime.evaluate`
- **持久化**：`window.name` 跨子域名保持刷课状态
- 视频静音 + 防暂停守卫由 content.js 自动处理

## 第二步：验证运行环境

拿到路径后，执行一次 `where-am-i` 确认 bridge server 连通且浏览器已登录学习通。
如果失败 → 提示用户："请确保已启动 bridge server 并在 Chrome 中登录学习通"

## 命令速查（精简版）

| 意图 | 命令 |
|------|------|
| **课程列表** | `list-courses` |
| **当前状态** | `where-am-i` |
| **整门课全自动** | `run-course --course-id X --clazz-id Y --cpi Z` |
| **暂停** | `request-pause` |
| **进度** | `get-progress --course-id X` |

> ⚠️ 刷课时只调用 `run-course`，不要在刷课过程中调用其他单步命令（那些是旧的 Python 驱动模式，会导致频繁跳转）。

## 约束

- 复用用户浏览器登录态，不做自动登录
- 作业/测验自动跳过
- CLI 输出均为 JSON，一次性打印
- `run-course` 持续运行直到课程完成或 `request-pause`
- 路径使用绝对路径
- 视频自动静音 + 防暂停由 content.js 在主世界处理
- **刷课中不做任何额外页面操作**（content.js 在主世界内自循环，外部干预会冲突）

## 典型对话

```
用户: 帮我看看有哪些课
AI:   [执行 where-am-i] → [执行 list-courses] → 缓存命中，返回 N 门课

用户: 刷这门 (courseId=123, clazzId=456, cpi=789)
AI:   [执行 run-course --course-id 123 --clazz-id 456 --cpi 789] → 已启动

用户: 现在进度多少
AI:   [执行 get-progress] → 缓存命中，已完成 3/51 章

用户: 先停一下
AI:   [执行 request-pause] → 已请求暂停
```
