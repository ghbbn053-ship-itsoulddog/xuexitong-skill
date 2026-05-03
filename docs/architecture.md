# 架构说明

当前项目沿用 `xiaohongshu` skill 的通用模型，但缩成最小实现：

1. OpenClaw 通过 `SKILL.md` 路由到 `python scripts/cli.py`
2. CLI 通过 WebSocket 调用 `scripts/bridge_server.py`
3. `bridge_server.py` 把命令转发给 Chrome 扩展
4. 扩展在学习站页面中执行 DOM 或 JS 操作

## 当前文件职责

- `extension/manifest.json`
  Chrome 扩展声明
- `extension/background.js`
  扩展与本地 bridge 的长连接、命令分发
- `extension/content.js`
  基础 DOM 操作
- `scripts/bridge_server.py`
  CLI 和扩展之间的本地转发层
- `scripts/cli.py`
  Skill 的统一命令入口
- `scripts/xxt/bridge.py`
  Python 侧页面操作封装

## 下一步

下一阶段需要接入真实站点信息：

- 登录后首页 URL
- 课程列表页 URL
- 课程详情页 URL
- 课程卡片选择器
- 章节树/任务点选择器
- 进度字段结构
