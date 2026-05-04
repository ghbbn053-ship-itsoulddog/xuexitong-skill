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

**快查询走缓存，慢任务走后台。** 不要每次调用都导航浏览器。

- `list-courses` / `get-progress` 优先读本地缓存（`cache.json`），TTL 内命中直接返回
- `where-am-i` 纯 DOM 检测，0 导航，返回当前状态 + 可执行动作
- `run-course` 是唯一的长任务，其他命令都应在 1-3s 内返回

## 第二步：验证运行环境

拿到路径后，执行一次 `where-am-i` 确认 bridge server 连通且浏览器已登录学习通。
如果失败 → 提示用户："请确保已启动 bridge server 并在 Chrome 中登录学习通"

## 核心工作流（缓存优先，减少导航）

### 工作流 A：查看课程列表

当用户询问"有什么课"时：

1. `list-courses` → 三级回退（缓存 → frame 快照 → 导航），缓存命中时 < 200ms
2. 将课程列表展示给用户（courseId / clazzId / cpi / title / teacher）
3. 如果 `list-courses` 失败 → `list-courses-from-frame --selector "#frame_content"`

### 工作流 B：启动整门课自动化

当用户说"刷某门课"时：

1. `list-courses` → 获取课程列表（含 courseId / clazzId / cpi）
2. 用户确认课程
3. `where-am-i` → 确认当前页面状态
4. `run-course --course-id X --clazz-id Y --cpi Z`

> 💡 `list-courses` 已返回 `clazzId` 和 `cpi`（如有），直接传参即可。
> 💡 如果缺少 `cpi`，先 `open-course --course-id X --clazz-id Y`（自动缓存 cpi）。

### 工作流 C：查看进度

当用户问"进度多少"时：

1. 如果 `run-course` 正在运行 → `get-loop-status`
2. 否则 → `get-progress --course-id X`（缓存优先，TTL 30s）

### 工作流 D：单步调试

当用户想看某一步的细节时，逐次调用：

```
chapter_task → auto-advance-step → study_page
study_page → auto-advance-step → task_card
task_card → auto-advance-step → video_playing
task_card → wait-video-end → video_ended
study_page → go-next-task-point → 下一个任务点
study_page → next-chapter → 下一章
```

## 页面状态 → 可用命令

**每次不确定当前状态时，先执行 `where-am-i` 获取 `allowedActions`。**

| 状态 | 可用命令 |
|------|---------|
| `course_detail` | `list-chapters`, `get-progress`, `run-course`, `open-course`, `where-am-i` |
| `chapter_task` | `list-chapters`, `get-chapter-summary`, `get-progress`, `open-chapter-by-id`, `auto-advance-step`, `run-course`, `where-am-i` |
| `study_page` | `auto-advance-step`, `go-next-task-point`, `next-chapter`, `return-to-study-page`, `where-am-i` |
| `task_card` | `inspect-task-page`, `inspect-video-tasks`, `play-video-task`, `pause-video-task`, `set-video-rate`, `mute-video-task`, `where-am-i` |
| `video_attachment` | `get-video-playback-state`, `play-video-task`, `pause-video-task`, `set-video-rate`, `where-am-i` |
| `space_wrapper` | `go-to-course-list`, `list-courses`, `list-courses-from-frame`, `where-am-i` |
| `course_list` | `go-to-course-list`, `list-courses`, `open-course-by-id`, `where-am-i` |

## 命令速查

| 意图 | 子命令与参数 |
|------|------------|
| **当前状态+可执行动作** | `where-am-i` |
| 检查登录 | `check-login` |
| **课程列表（缓存优先）** | `list-courses` |
| **从 iframe 抓课程列表** | `list-courses-from-frame --selector "#frame_content"` |
| 一步到课程列表页 | `go-to-course-list` |
| **课程实时进度（缓存优先）** | `get-progress [--course-id ID]` |
| 当前页面上下文（详细） | `get-current-context` |
| 列出章节 | `list-chapters` |
| 章节摘要 | `get-chapter-summary` |
| 打开课程 | `open-course --course-id X [--clazz-id Y] [--url URL]` |
| 按 ID 打开章节 | `open-chapter-by-id --chapter-id ID` |
| 通用页面导航 | `navigate --url URL` |
| 查看任务页 | `inspect-task-page` |
| 查看视频任务 | `inspect-video-tasks` |
| 视频播放状态 | `get-video-playback-state` |
| 播放视频 | `play-video-task` |
| 暂停视频 | `pause-video-task` |
| 设定倍速 | `set-video-rate --rate 2.0` |
| 静音 | `mute-video-task --muted` |
| 防误触守卫 | `arm-video-guard` / `disarm-video-guard` |
| 单步自动推进 | `auto-advance-step` |
| 等待视频播完 | `wait-video-end [--timeout 1800]` |
| 下一任务点 | `go-next-task-point` |
| 下一章节 | `next-chapter` |
| 返回学习页 | `return-to-study-page` |
| **整门课全自动** | `run-course --course-id X --clazz-id Y --cpi Z [--enc E]` |
| 查看循环状态 | `get-loop-status` |
| 请求暂停 | `request-pause` |

## 约束

- 复用用户浏览器登录态，不做自动登录
- 作业/测验自动跳过，记录到 `blockedItems`
- CLI 输出均为 JSON，一次性打印
- `run-course` 持续运行直到课程完成或 `request-pause`
- 路径必须使用绝对路径（先按第一步找到项目根目录）
- 视频播放时自动静音 + 防误触守卫
- 跨平台：Linux/Mac 用正斜杠 `/`，Windows 用反斜杠 `\\`

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
