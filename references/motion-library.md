# motion-library.md —— 动效选配词汇库（2026-11-09 入包）

> 用途：执行方按场景主动选配动效时查的标准词汇与匹配表。来源四路：Motion Prompt（showheyohtaki/motion-prompt，192 个效果，MIT 系开源画廊）、HTML-in-Canvas（2026-11-06 收入武器库）、huashu-motion 运动语言（alchaincyf/huashu-motion v0.1.1）、MotionSites 融合项（已在 SKILL.md 正文，不在此重复）。交付说明点名动效时用本库的标准名（中文名 + 英文名）。

## 1. 一页纸场景匹配子集（先查这张表）

| 页面场景 | 选配效果（标准名） | 用法要点 |
| --- | --- | --- |
| 流程 / 机制演示（数据包、订单、请求沿环节走） | 沿路径运动 + 节点停留（自创组合，词汇近 Motion trail #014 / Line draw #004） | 对象走真实连线、在关键节点停一拍再出发；连接线加虚线流光示方向；到达触发状态变化（计数、浮签、变色） |
| 关键数字、账本、计数器 | 数字递增 Count-up #007 | 1–1.5s 滚到目标值、末尾减速（缓出）；金额带小数位对齐，滚动中格式不跳 |
| 多卡 / 多步入场 | 交错动画 Stagger #002 | 间隔 80–120ms 依次入场；单元素 300–400ms、位移 ≤12px（守动效档红线） |
| 图表线条、路径揭示 | 线条描绘 Line draw #004 | stroke-dashoffset 驱动，1–1.5s 画完；打印态直接终态 |
| 标题 / 段落入场 | 遮罩显现 Mask reveal #005 / 滚动淡入 Fade-in on scroll #074 | 一页纸内位移压到 ≤12px，不采落地页的 30px 大位移 |
| 长页阅读 | 滚动进度条 Scroll progress bar #079 | 顶部 3–4px、强调色、随滚动实时宽度；打印隐藏 |
| 重点词强调 | 荧光笔标记 Highlighter #080 | 入视口时色带从左向右画出，0.6–0.8s；一页 ≤3 处 |
| 指针 / 仪表落点 | 过冲回弹 Overshoot #010 | 超出约 10% 再回稳；只给指示件，不给正文 |
| 卡片悬停（落地页 / 非一页纸） | 悬停抬升 Hover lift #081 / 磁吸按钮 Magnetic button #084 / 涟漪 Ripple #085 | 一页纸内克制使用；落地页可放开 |
| 代码 / 命令逐字呈现 | 打字机 Typewriter #006 | 每字约 50ms、末尾光标；只给短串，长代码直接整段显 |
| 讲解视频 / 发布片（走 huashu-motion） | mechanism / data-story / kinetic-type（见 §4） | 页面内不直接套用，只借运动语言思路 |

## 2. HTML-in-Canvas（2026-11-06 收入武器库）

- 是什么：Chrome 157+ 的实验能力，把 HTML 元素画进 Canvas 纹理，可做文字扭曲、放大镜、液态变形等普通 DOM 做不到的演出。官方已核实默认开启，仅 Chromium 系可用。
- 用在哪：**落地页 / 产品 hero** 的签名点演出（文字扭曲、放大镜扫过、波形字）。做落地页时可主动用。
- 守界：① 必须留降级——非 Chromium 打开时回落普通 DOM 呈现，不许白屏；② **一页纸不引入**（零依赖与跨浏览器红线）；③ 不拿它承载正文信息，只做演出层。

## 3. Motion Prompt 全索引（192 个 · 编号即画廊编号）

画廊：https://showheyohtaki.github.io/motion-prompt/ ；仓库：https://github.com/showheyohtaki/motion-prompt 。用法：看到对眼的效果记编号，按「名称 + 时长 / 幅度 / 对象」描述即可精确复刻。

### 动态图形 motion（24 个）

#001 弹性入场 Pop-in · #002 交错动画 Stagger · #003 放射爆发 Burst · #004 线条描绘 Line draw · #005 遮罩显现 Mask reveal · #006 打字机效果 Typewriter · #007 数字递增 Count-up · #008 动态排版 Kinetic typography · #009 缓动 Easing · #010 过冲回弹 Overshoot · #011 挤压与拉伸 Squash & stretch · #012 形状变形 Shape morph · #013 液态动效 Liquid motion · #014 运动拖尾 Motion trail · #015 粒子效果 Particles · #016 视差 Parallax · #017 遮罩转场 Mask transition · #018 图形转场 Shape transition · #019 液态转场 Liquid transition · #020 穿越缩放 Zoom through · #021 翻转 Flip · #022 扫光 Light sweep · #023 故障效果 Glitch · #024 冲击震动 Impact shake

### 镜头 camera（24 个）

#025 水平摇镜头 Pan · #026 垂直摇镜头 Tilt · #027 推镜头 Dolly in · #028 变焦推近 Zoom in · #029 跟拍 Tracking shot · #030 环绕镜头 Orbit (Arc shot) · #031 升镜头 Crane up · #032 滑动变焦 Dolly zoom (Vertigo) · #033 焦点转移 Rack focus · #034 手持镜头 Handheld · #035 FPV 穿越机镜头 FPV drone shot · #036 荷兰角 Dutch angle · #037 慢动作 Slow motion · #038 速度渐变 Speed ramp · #039 延时摄影 Time-lapse · #040 定格 Freeze frame · #041 跳切 Jump cut · #042 匹配剪辑 Match cut · #043 甩镜头转场 Whip pan · #044 交叉溶解 Cross dissolve · #045 划像转场 Wipe · #046 突切 Smash cut · #047 J 型剪辑 J-cut · #048 L 型剪辑 L-cut

### 镜头二 camera2（24 个）

#169 垂直升降镜头 Pedestal · #170 横滚镜头 Barrel roll · #171 移动延时 Hyperlapse · #172 长镜头 Long take · #173 斯坦尼康 Steadicam · #174 背后跟拍 Follow shot · #175 固定镜头 Locked-off shot · #176 穿越镜头 Fly-through · #177 低角度镜头 Low angle · #178 高角度镜头 High angle · #179 POV 镜头 POV shot · #180 过肩镜头 Over-the-shoulder · #181 鸟瞰镜头 Bird's-eye view · #182 深焦镜头 Deep focus · #183 定场镜头 Establishing shot · #184 大特写 Extreme close-up · #185 插入镜头 Insert shot · #186 变形剪切 Morph cut · #187 淡出到黑场 Fade to black · #188 圈出 Iris out · #189 切出镜头 Cutaway · #190 交叉剪辑 Cross-cutting · #191 子弹时间 Bullet time · #192 蒙太奇 Montage

### 落地页 lp（24 个）

#073 视差滚动 Parallax scrolling · #074 滚动淡入 Fade-in on scroll · #075 吸顶页头 Sticky header · #076 滚动固定 Pinning · #077 横向滚动 Horizontal scroll · #078 滚动吸附 Scroll snap · #079 滚动进度条 Scroll progress bar · #080 荧光笔标记动画 Highlighter animation · #081 悬停抬升 Hover lift · #082 悬停图片放大 Image zoom on hover · #083 光标跟随 Cursor follower · #084 磁吸按钮 Magnetic button · #085 涟漪效果 Ripple effect · #086 下划线动画 Underline animation · #087 前后对比滑块 Before/after slider · #088 离站挽留弹窗 Exit-intent popup · #089 预加载画面 Preloader · #090 懒加载 Lazy loading · #091 无限滚动 Infinite scroll · #092 页面转场 Page transition · #093 平滑滚动 Smooth scroll · #094 跑马灯 Marquee · #095 动态渐变 Animated gradient · #096 悬浮动画 Floating animation

### 落地页二 lp2（24 个）

#145 滚动时间轴 Timeline on scroll · #146 滚动文字显现 Scroll text reveal · #147 堆叠卡片 Stacking cards · #148 滚动切换背景色 Background color change on scroll · #149 滚动隐藏页头 Hide-on-scroll header · #150 滚动监听 Scrollspy · #151 回到顶部按钮 Back-to-top button · #152 滚动放大 Zoom on scroll · #153 3D 倾斜 3D tilt on hover · #154 聚光灯悬停 Spotlight hover · #155 悬停切换图片 Image swap on hover · #156 悬停文字翻滚 Text roll on hover · #157 悬停图片预览 Hover image reveal · #158 浮动标签 Floating label · #159 实时校验 Inline validation · #160 加载按钮 Loading button · #161 视图过渡 View transition (shared element) · #162 灯箱 Lightbox · #163 图片热点 Hotspots · #164 倒计时 Countdown timer · #165 动态形状分隔线 Animated shape divider · #166 点赞动画 Like button animation · #167 向下滚动提示 Scroll-down cue · #168 背景视频 Background video

### UI 组件 ui（24 个）

#049 模态对话框 Modal dialog · #050 抽屉面板 Drawer (Off-canvas) · #051 底部面板 Bottom sheet · #052 折叠面板 Accordion · #053 下拉选择框 Dropdown (select) · #054 文字提示 Tooltip · #055 气泡卡片 Popover · #056 轻提示 Toast notification · #057 标签页 Tabs · #058 轮播图 Carousel · #059 开关 Toggle switch · #060 分段控制器 Segmented control · #061 筛选标签 Filter chips · #062 范围滑块 Range slider · #063 步进器 Stepper (+/−) · #064 分页 Pagination · #065 汉堡菜单 Hamburger menu · #066 面包屑导航 Breadcrumbs · #067 巨型菜单 Mega menu · #068 步骤指示器 Step indicator · #069 骨架屏 Skeleton screen · #070 加载转圈 Spinner · #071 徽标 Badge · #072 空状态 Empty state

### 动态图形二 motion2（24 个）

#121 预备动作 Anticipation · #122 跟随动作 Follow-through · #123 弹跳 Bounce · #124 随机抖动 Wiggle · #125 脉冲动画 Pulse · #126 运动路径 Motion path · #127 往返循环 Ping-pong loop · #128 定格动画风格 Stop-motion style · #129 文字乱码效果 Text scramble · #130 波浪文字 Wave text · #131 路径文字 Text on a path · #132 可变字体动画 Variable font animation · #133 文字遮罩 Text mask · #134 中继器 Repeater · #135 万花筒 Kaleidoscope · #136 线条抖动 Line boil · #137 推入转场 Push transition · #138 百叶窗转场 Blinds transition · #139 立方体转场 Cube transition · #140 翻页转场 Page curl · #141 像素化转场 Pixelate · #142 玻璃碎裂 Shatter · #143 爆炸图 Exploded view · #144 分屏 Split screen

### 摄影风格 photo（24 个）

#097 逆光 Backlighting · #098 轮廓光 Rim light · #099 剪影 Silhouette · #100 分割光 Split lighting · #101 伦勃朗光 Rembrandt lighting · #102 蝴蝶光 Butterfly lighting · #103 黄金时刻 Golden hour · #104 蓝调时刻 Blue hour · #105 散景 Bokeh · #106 移轴效果 Tilt-shift · #107 长曝光 Long exposure · #108 追随拍摄 Panning shot · #109 镜头眩光 Lens flare · #110 鱼眼镜头 Fisheye lens · #111 色差 Chromatic aberration · #112 暗角 Vignette · #113 高调 High-key · #114 低调 Low-key · #115 黑白 Black and white · #116 双色调 Duotone · #117 青橙色调 Teal and orange · #118 胶片颗粒 Film grain · #119 漏光 Light leak · #120 双重曝光 Double exposure

## 4. huashu-motion 运动语言索引（视频向，借思路不借物料）

huashu-motion（alchaincyf/huashu-motion v0.1.1，MIT）是「一支片子 = 一个 index.html + GSAP」的动效视频技能（需要时另行安装）。其 20 种运动语言里，与解释页 / 演示最贴的是：

- **mechanism**（机制）：把系统怎么运转演出来——一页纸场景动画的思路源头
- **data-story**（数据故事）：数字与图表随叙事推进生长、累加
- **kinetic-type**（动态排版）：文字随含义缩放、移动、对齐节拍
- **system-diagram**（系统图）：节点与连线逐个点亮、流向推进
- **continuous-morph**（连续变形）：一形平滑变另一形，适合「改之前 → 改之后」
- 其余 15 种备查：3d-object、art-styles、card-montage、character、cursor-demo、editorial-collage、flat-world、generative-field、hand-drawn、liquid-glass、modular-grid、photo-led、retro-digital、showreel、talking-head

## 5. 守界汇总

- 一页纸内：动效档红线不破（300–400ms / ≤12px / 三兜底 / 打印终态）；大效果（视差滚动 #073、滚动固定 #076、横向滚动 #077、全屏类）只许落地页 / 网页项目。
- 选配后在交付说明里点名：用了哪几个（标准名）、落在哪一屏、为什么。
