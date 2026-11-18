#!/usr/bin/env bash
# refresh-vendor.sh — 从 UI UX Pro Max 母本刷新 onepager 内嵌子集快照
# 用法: ./refresh-vendor.sh [母本包根目录]
#   母本包根 = 含 skills/ui-ux-pro-max/ 与 LICENSE 的目录
#   默认: ~/ui-ux-pro-max-skill（上游仓库克隆目录）
set -euo pipefail

# 防污染：调用 vendor 里的 Python 一律禁写字节码，否则每次冒烟都会在
# vendor/ui-ux-pro-max/scripts/ 下生成 __pycache__，把母本快照污染成"脏快照"
# （打包时又得手工清）。两个都要：环境变量管子进程，-B 管当前解释器。
export PYTHONDONTWRITEBYTECODE=1

PKG="${1:-$HOME/ui-ux-pro-max-skill}"
INNER="$PKG/skills/ui-ux-pro-max"
HERE="$(cd "$(dirname "$0")" && pwd)"
DST="$HERE/ui-ux-pro-max"

[ -d "$INNER/scripts" ] || { echo "FAIL: 母本不存在或结构不对: $INNER"; exit 1; }

for f in search.py core.py design_system.py reasoning_contract.py; do
  cp "$INNER/scripts/$f" "$DST/scripts/$f"
done
for f in colors charts styles typography ux-guidelines; do
  cp "$INNER/data/$f.csv" "$DST/data/$f.csv"
done
cp "$PKG/LICENSE" "$DST/LICENSE"

TODAY="$(date +%F)"
sed -i "s/^- 快照日期：.*/- 快照日期：$TODAY/" "$DST/VENDOR.md"

echo "== 冒烟测试（5 域） =="
S="$DST/scripts/search.py"
python3 -B "$S" "education learning" --domain color -n 1 >/dev/null && echo "color OK"
python3 -B "$S" "trend comparison" --domain chart -n 1 >/dev/null && echo "chart OK"
python3 -B "$S" "health wellness" --domain style -n 1 >/dev/null && echo "style OK"
python3 -B "$S" "editorial serif" --domain typography -n 1 >/dev/null && echo "typography OK"
python3 -B "$S" "text wrapping overflow" --domain ux -n 1 >/dev/null && echo "ux OK"
echo "刷新完成：快照日期 $TODAY，来源 $PKG"
