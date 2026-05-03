# 页面映射

## 1. 登录页

- URL: `https://v8.chaoxing.com/`
- 用户名输入框: `#uunnmm`
- 密码输入框: `#pwd`
- 登录按钮: `#login`
- 扫码 iframe: `#iframe`
- 验证码层: `#captcha`

## 2. 登录后首页

- 用户头像: `.school-header .user-photo img`
- 用户名: `.school-header .user-mes h3`
- 个人空间入口提示: `#showPrompt a[href*='i.chaoxing.com']`

## 3. 个人空间

- 单位名: `#siteName`
- 用户头像: `.nav .user img.icon-head`
- 左侧课程菜单: `#first2444618`

## 4. 个人空间课程外壳页

- 用户名: `.personalInfor .personalName`
- 左侧课程入口: `#zne_kc_icon`
- 实际课程内容 iframe: `#frame_content`
- 当前默认课程页 URL 由 `#frame_content.src` 提供

## 5. 课程详情页

- 课程 ID: `#courseid`
- 班级 ID: `#clazzid`
- `cpi`: `#cpi`
- 章节 iframe: `#frame_content-zj`
- 章节页 tab: `a[title="章节"]`

## 6. 章节任务页

- 页面主体: `#body-content`
- 当前课程 ID: `#curCourseId`
- 当前章节 ID: `#curChapterId`
- 当前班级 ID: `#curClazzId`
- 任务卡 iframe: `#iframe[info='card']`
- 章节树: `#coursetree`
- 学习状态: `#_studystate`
- 当前章节名: `.posCatalog_active .posCatalog_name`
- 已完成标记: `.icon_Completed`
- 待完成任务点标记: `.catalog_points_yi`

## 已知流程

1. 先登录
2. 登录后首页点击“点击这里进个人空间”
3. 进入个人空间课程外壳页
4. 通过 `#frame_content` 进入实际课程页
5. 课程页通过 `#frame_content-zj` 进入章节树
6. 章节页通过 `#iframe[info='card']` 承载具体任务卡
