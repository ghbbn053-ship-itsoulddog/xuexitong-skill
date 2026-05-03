# xuexitong

超星学习通课程自动化助手，基于 OpenClaw skill + Chrome 扩展 + 本地 bridge server 四层架构。

支持 27 条 CLI 命令，覆盖登录检查、课程列表、章节导航、视频播放控制、整门课无人值守全自动刷完。

## 架构

```
用户 → OpenClaw (SKILL.md) → CLI (cli.py) → Bridge Server (ws://localhost:9333) → Chrome 扩展 → 学习通页面
```

## 快速开始

### 1. 安装依赖

```bash
pip install websockets
```

### 2. 加载 Chrome 扩展

1. Chrome 地址栏输入 `chrome://extensions/`
2. 开启「开发者模式」
3. 点击「加载已解压的扩展」→ 选择 `extension/` 目录

### 3. 启动 bridge server

```bash
python scripts/bridge_server.py
```

### 4. 手动登录学习通

浏览器打开 https://mooc1.chaoxing.com 并登录，之后所有操作由 agent 接管。

### 5. 加载 skill 到 OpenClaw

将 `SKILL.md` 放入你的 OpenClaw skills 目录。

## 目录

```text
xuexitong/
├── SKILL.md          # OpenClaw skill 定义（给 AI 看的说明书）
├── extension/        # Chrome 扩展 (XXT Bridge)
│   ├── background.js
│   ├── content.js
│   └── manifest.json
├── scripts/          # Python CLI 桥梁
│   ├── cli.py        # 27 条命令的统一入口
│   ├── bridge_server.py  # WebSocket 服务端
│   └── xxt/          # 页面逻辑库
│       ├── bridge.py
│       ├── page_state.py
│       └── selectors.py
├── tests/            # 单元测试
└── docs/             # 架构 & 页面文档
```

## 典型对话

```
用户: 帮我看看有哪些课
AI:   你目前有 18 门课：xxx、xxx...

用户: 刷中华民族精神
AI:   开始自动刷「中华民族精神」，共 51 节 98 个任务点
      [后台 run-course 持续运行，遇视频自动播放，遇作业自动跳过]

用户: 现在进度多少
AI:   已完成 12/51 章，23 个视频，跳过 3 个测验

用户: 先停一下
AI:   已请求暂停，当前视频播完即停
```

## ⚠️ 免责声明

- 本项目**仅供学习研究**使用，严禁用于任何商业用途。
- 使用者应自行承担使用本工具所产生的一切后果，开发者不对任何因使用本项目导致的账号封禁、数据丢失或法律纠纷负责。
- 本项目不提供任何形式的自动登录、绕过验证或非法访问功能，所有操作依赖用户自行登录的合法会话。
- 使用本工具前，请确认你已阅读并理解所在平台的使用协议。

## ⭐

如果这个项目帮到了你，给个 Star 支持一下吧——

[![Star](https://img.shields.io/github/stars/ghbbn053-ship-itsoulddog/xuexitong-skill?style=social)](https://github.com/ghbbn053-ship-itsoulddog/xuexitong-skill)
