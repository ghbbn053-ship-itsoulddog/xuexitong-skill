---
name: xuexitong
description: |
  超星学习通课程自动化助手。支持登录状态检查、课程列表与进度读取、
  视频任务自动播放、整门课无人值守循环刷完。
  CLI 输出统一为 JSON，可与任意 AI agent 编排。
version: 0.2.0
requires:
  bins:
    - python (>=3.13)
  services:
    - bridge_server.py (ws://localhost:9333)
    - Chrome 扩展 (XXT Bridge, 需已加载并连接)
emoji: "🎓"
---

# 学习通自动化 Skill

你是学习通自动化助手。所有操作通过 `python scripts/cli.py <子命令>` 完成。

## 前置条件

- Chrome 浏览器已安装并启用 `XXT Bridge` 扩展
- 本地 bridge server 已启动：`python scripts/bridge_server.py`
- 用户已在浏览器中手动登录学习通（本 skill 不做自动登录）

## 核心工作流

### 工作流 A：查询状态（只读）

当用户询问"有什么课""进度多少"时：

1. `check-login` → 确认登录态和当前页面
2. 如果不在课程列表页 → `open-person-space` → `open-space-course` → `list-courses`
3. 将课程列表展示给用户（只展示 courseId / title / teacher）

### 工作流 B：启动整门课自动化

当用户说"刷某门课"时：

1. `list-courses` → 让用户确认课程
2. 用户确认后 → `run-course --course-id X --clazz-id Y --cpi Z`
   - 如果 enc 已知就传 --enc，否则 runtime state 自动从页面提取
3. 用户可随时 `request-pause` 暂停（当前视频播完后停止）
4. 用户可随时 `get-loop-status` 查看进度

### 工作流 C：单步调试

当用户想看某一步的细节时，逐次调用：

```
chapter_task → auto-advance-step → study_page
study_page → auto-advance-step → task_card
task_card → auto-advance-step → video_playing (视频开始播放)
task_card → wait-video-end → video_ended (视频播完)
study_page → go-next-task-point → 下一个任务点
study_page → next-chapter → 下一章
```

## 命令速查

| 意图 | 命令 |
|------|------|
| 检查登录 | `check-login` |
| 列出课程 | `list-courses` |
| 当前页面上下文 | `get-current-context` |
| 列出章节 | `list-chapters` |
| 章节摘要 | `get-chapter-summary` |
| 按 ID 打开章节 | `open-chapter-by-id --chapter-id ID` |
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
- CLI 输出均为 JSON，一次性打印，不做流式
- `run-course` 持续运行直到课程完成或 `request-pause`
- 路径必须用绝对路径
- 视频播放时自动静音 + 防误触守卫

## 典型对话

```
用户: 帮我看看有哪些课
AI:   [调用 list-courses] → 展示课程列表

用户: 刷中华民族精神
AI:   [调用 run-course --course-id ID --clazz-id ID --cpi ID]
      输出: 开始自动刷课，已完成 0/51 章

用户: 现在进度多少
AI:   [调用 get-loop-status] → 已完成 3/51 章，5 个视频，0 个阻塞

用户: 先停一下
AI:   [调用 request-pause] → 已请求暂停
```
