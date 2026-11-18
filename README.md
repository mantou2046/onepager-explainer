# onepager-explainer · 一页读懂

把任何主题做成**一页讲清楚**的单文件 HTML 解释页的 Agent Skill：给你的 AI 编程助手装上这套规范，它产出的不再是「一段 markdown 回答」，而是一张能互动、能打印、能离线分发的解释页。

![卡门线 · 一页读懂（科普场景）](docs/assets/karman.png)

## 产出长什么样

固定五屏叙事：**① 是什么 → ② 结构/原理 → ③ 动手演示 → ④ 分步讲解 → ⑤ 速查与带走**。解释、科普、介绍、学习四类场景共用同一套工艺。`examples/` 里有三个完整成品，下载后双击即可打开：

| 示例 | 场景 | 看点 |
| --- | --- | --- |
| [卡门线 · 一页读懂](examples/卡门线%20·%20一页读懂.html) | 科普 | AI 生成主视觉、上升之旅场景动画、双滑杆真实公式演示 |
| [LoRA · 一页读懂](examples/LoRA%20·%20一页读懂.html) | 学习 | 数据包双路汇合动画演「冻结基座 + 外挂适配器」、r 滑杆实时算账 |
| [BM25 · 一页读懂](examples/BM25%20·%20一页读懂.html) | 学习 | 可交互打分演示、讲解器同视口迷你场景 |

![LoRA · 一页读懂（学习场景）](docs/assets/lora.png)

## 五个硬承诺（与同类技能的差别在这里）

1. **真零依赖**：产出是单个 HTML 文件，CSS/JS/图片/字体全内嵌，无任何外链——可改名、可邮件、可离线打开。
2. **打印基线**：一页纸要能真打印。宽表不裁、折叠内容全展开、讲解器全步印出，交付前跑 `print_check` 真打一份 PDF 抽字断言，退出码 0 才算过——打印丢内容是静默的，只读代码判「没问题」不算数。
3. **数值化设计门禁**：字阶只用 6 档（12.5/14/16/19/24/32）；明暗双主题的文字对比度**算出来** ≥ 4.5:1，不达标只许同色相调明度；语义色一概念一色、全页贯穿。
4. **场景动画演机制本身**：有生活场景的主题必须带场景动画——角色/物件沿流程移动、状态随环节变化，演的是「谁把什么交给谁、在哪一步变样」，不是装饰飘动；讲解器切步时，同视口的迷你场景同步推进。
5. **白话密度**：科普/介绍页只留读懂目标句必需的术语，定义先行、生活比方在前；速查表第三列「白话备注」逐行必填，不许写成「作用」列的同义重复。

此外还有：主视觉生图优先（SVG 保底）、版式变体层（每页选一组连贯气质，不套同一个模子）、截图评分闭环（8 项量表，均分 ≥8 才交付）、可选 Edge-TTS 配音内嵌分支（按讲解步分段内嵌，默认关闭）。

## 口令：一句话唤起

装好后不用记命令、不用配参数——对 Agent 说一句口令就触发：

> **一页纸 + 要解释的对象**

> 一页纸 勾股定理
> 一页纸 BM25
> 一页纸讲讲卡门线

说得随意些也行：「用一页读懂给我讲讲 X」「做个页面科普一下 X」「把这套流程做成一页介绍页」——都按同一套规范出页（触发词写在 `SKILL.md` 的 description 里，Agent 读到即调用）。

## 快速开始

```bash
git clone https://github.com/mantou2046/onepager-explainer.git
cp -r onepager-explainer ~/.claude/skills/onepager-explainer
```

适用于任何读取 `SKILL.md` 的 Agent 环境（Claude Code、Muse、WorkBuddy 等；其他 Agent 把目录放进它的技能/规则目录即可）。装好后对 Agent 说一句口令即可，最简式就是「一页纸 勾股定理」。

## 脚本依赖（按需）

页面生成本身零依赖；`scripts/` 里的质检与加工脚本按需安装：

| 脚本 | 用途 | 依赖 |
| --- | --- | --- |
| `print_check.py` / `print_check_pc.py` | 打印完整性实测（无头版 / Windows Chrome 版，二选一） | playwright 或 Chrome/Edge + poppler |
| `patch_print_baseline.py` | 打印基线自动补齐（被 print_check --fix 调用） | — |
| `text_check.mjs` | 中文排版与断行实测（行长/孤字/数字拆行） | Node ≥ 22 + Chrome/Edge |
| `dom_smoke.js` | 页面交互冒烟断言 | Node + jsdom（`npm i`） |
| `prep_image.py` | 主视觉图片缩宽、压 WebP、产出内嵌片段 | pillow |
| `gen_tts.py` + `embed_audio.py` | 配音分支：讲稿合成 + 分段内嵌 | edge-tts |

## 目录结构

```
├── SKILL.md            主规范：定位、工作流、硬规则、已知坑、增订附录
├── references/
│   ├── design-tokens.md  视觉系统、五屏结构、讲解器锚点契约、打印标准件
│   ├── qa-gates.md       四层质量门禁 checklist
│   ├── script-spec.md    配音讲稿写作规范
│   └── motion-library.md 动效选配词汇库与场景匹配表
├── scripts/            质检与加工脚本（见上表）
├── vendor/ui-ux-pro-max/ 设计令牌查询子集快照（上游 MIT，见其 VENDOR.md）
└── examples/           三个完整成品页
```

## 来历与实证

这套规范不是设计出来的，是**打出来的**：2026 年 10 月起在真实学习与科普任务里连续生产 40 多个题目（LLMOps 系列、自然科普、生活常识、古文），SKILL.md 里的每条硬规则几乎都对应一次真实翻车——「已知坑」一节就是事故账：讲解器锚点写错会静默失效、打印会静默裁掉右半张表、生图里的文字必错……演进节点见 [CHANGELOG.md](CHANGELOG.md)。

## 致谢

- 设计令牌查询：[UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)（MIT，`vendor/` 内为 5 域子集快照）
- 质感工艺借鉴：[Motionsites-AI/claude-skill](https://github.com/Motionsites-AI/claude-skill)、[huashu-motion](https://github.com/alchaincyf/huashu-motion)、Motion Prompt 效果索引（出处见 `references/motion-library.md`）

## License

MIT（`vendor/ui-ux-pro-max/` 部分为上游自身的 MIT License，见其目录内 LICENSE）。
