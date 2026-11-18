# VENDOR — UI UX Pro Max 子集快照（onepager 内嵌）

本目录是上游技能 **UI UX Pro Max** 的一个**只读子集快照**，内嵌于 onepager-explainer 技能内，
供「设计增强」第 0 步查询自引用，不再依赖外部技能是否安装。

## 出处

- 上游：nextlevelbuilder/ui-ux-pro-max-skill，v2.15.0，commit d14efff（MIT，见同目录 LICENSE）
- 母本（完整精简版）：本地安装的上游技能目录（见 ../refresh-vendor.sh 的参数）
- 快照日期：2026-10-24

## 子集范围

- scripts/：search.py、core.py、design_system.py、reasoning_contract.py（与母本原样一致，不改一行）
- data/：仅 onepager 用到的 5 个域——colors / charts / styles / typography / ux-guidelines
- **可用域只有这 5 个**。其余域（products、icons、landing、motion、app-interface、google-fonts、react-performance）与
  22 个技术栈文件未内嵌，查了会报文件缺失——那是预期行为，需要那些能力时用母本（独立安装的上游技能）。

## 纪律

- 本目录**只读**：不许直接改这里的任何文件（改了会在下次刷新时被覆盖，且会让快照与母本悄悄分叉）。
- 要改行为：先改母本，再跑刷新脚本同步过来。
- **防字节码污染**：调用本目录的 `scripts/*.py` 一律带 `PYTHONDONTWRITEBYTECODE=1` 与 `python3 -B`
  （`refresh-vendor.sh` 已在顶部 `export`，冒烟也全用 `python3 -B`）。否则每跑一次就在
  `scripts/` 下多一个 `__pycache__`，快照变脏、打包还得手工清。

## 刷新（上游/母本更新时）

运行同级目录的 `../refresh-vendor.sh`（可带参数指定母本包根目录，参数即母本包根目录；
把本机 ui-ux-pro-max 的安装目录作为参数传入即可）。
脚本会：按上面清单整表覆盖拷贝 → 更新本文件的快照日期 → 跑 5 个域的冒烟查询，全过才算刷新成功。
刷新后记得：onepager 的 SKILL.md 若引用了具体数据结论（如某色板数值），需一并复核；
分享出去的旧拷贝不会自动更新，需重新分发技能文件夹。
