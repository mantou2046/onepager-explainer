#!/usr/bin/env python3
"""prep_image.py —— 生图成品 → 单文件 HTML 可内嵌的 base64 图

「一页读懂」的硬指标落地件（design-tokens.md §4.3）：
  宽度封顶 = 页面显示宽 × 1.3（hero ≈1280px）；优先 WebP q≈78；单张 ≤50KB；
  base64 内嵌会再膨胀约 33%，按内嵌后算账；禁止原图直嵌。

用法：
  python prep_image.py raw.png --width 1280 --out ./img_out
  python prep_image.py raw.png --base64            # 直接打印 data URI
  python prep_image.py raw.png --snippet           # 生成 figure 片段文件

产物（写到 --out 目录）：
  <name>.webp              压好的成品图
  <name>.webp.b64.txt      纯 base64 文本（备用）
  <name>.figure.html       可直接粘进页面的 figure 片段（含 figcaption / alt 占位）

退出码：0 正常；2 成品超体积目标（仍已产出，需人工决定）；1 出错。
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import sys

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("[x] 需要 Pillow：pip install -U pillow", file=sys.stderr)
    raise SystemExit(1)

TARGET_KB = 50.0
B64_GROWTH = 1.333  # base64 相对二进制的体积膨胀系数


def human_kb(n: float) -> str:
    return f"{n:.0f} KB" if n >= 1 else f"{n * 1024:.0f} B"


def prep(src: str, width: int, quality: int, fmt: str, out_dir: str,
         allow_upscale: bool = False) -> tuple[str, bytes, dict]:
    im = Image.open(src)
    src_w, src_h = im.size

    # 只在需要时缩小；除非显式允许，不做放大（放大只会糊 + 涨体积）
    if width and src_w > width:
        ratio = width / src_w
        im = im.resize((width, max(1, round(src_h * ratio))), Image.LANCZOS)
    elif width and src_w < width and not allow_upscale:
        print(f"[!] 原图宽 {src_w} < 目标 {width}，不放大（要放大加 --allow-upscale）")

    buf = io.BytesIO()
    if fmt == "webp":
        im.save(buf, "WEBP", quality=quality, method=6)
        ext = "webp"
    else:  # jpg：不支持透明，先合到白底
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        im.save(buf, "JPEG", quality=quality, progressive=True, subsampling=2)
        ext = "jpg"

    data = buf.getvalue()
    out_w, out_h = im.size
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    out_path = os.path.join(out_dir, f"{stem}.{ext}")
    with open(out_path, "wb") as fh:
        fh.write(data)

    # 自检：产物能被重新打开且尺寸对得上
    with Image.open(out_path) as chk:
        assert chk.size == (out_w, out_h), "产物尺寸异常"

    b64 = base64.b64encode(data)
    b64_kb = len(b64) / 1024
    bin_kb = len(data) / 1024
    info = {
        "src": (src_w, src_h),
        "out": (out_w, out_h),
        "bin_kb": bin_kb,
        "b64_kb": b64_kb,
        "out_path": out_path,
        "ext": ext,
    }
    print(f"    原图  {src_w}×{src_h}  {human_kb(os.path.getsize(src) / 1024)}")
    print(f"    成品  {out_w}×{out_h}  {human_kb(bin_kb)}  ({fmt} q{quality}) → {out_path}")
    print(f"    内嵌  base64 {human_kb(b64_kb)}（×{B64_GROWTH} 膨胀已计入）")
    if b64_kb > TARGET_KB:
        print(f"[!] 内嵌后 {b64_kb:.0f} KB > 目标 {TARGET_KB:.0f} KB —— 先降宽（−20%）或降质量（−8）再试")
    else:
        print(f"[ok] 内嵌后 {b64_kb:.0f} KB ≤ 目标 {TARGET_KB:.0f} KB")
    return out_path, data, info


def figure_snippet(data: bytes, ext: str, out_dir: str, stem: str,
                   alt: str, caption: str) -> str:
    mime = "image/webp" if ext == "webp" else "image/jpeg"
    uri = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
    html = (
        '<figure class="hero-fig">\n'
        f'  <img src="{uri}"\n'
        f'       alt="{alt}" loading="lazy" decoding="async">\n'
        f'  <figcaption>{caption}</figcaption>\n'
        "</figure>\n"
    )
    path = os.path.join(out_dir, f"{stem}.figure.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"    figure 片段 → {path}（{len(html) / 1024:.0f} KB，含 base64）")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="生图成品 → 单文件 HTML 可内嵌 base64 图")
    ap.add_argument("src", help="原始生成图（png/jpg/webp…）")
    ap.add_argument("--width", type=int, default=1280, help="目标宽度（显示宽×1.3；hero 默认 1280）")
    ap.add_argument("--quality", type=int, default=78, help="WebP 质量，默认 78（JPG 建议 72–80）")
    ap.add_argument("--format", choices=["webp", "jpg"], default="webp", help="成品格式，默认 webp")
    ap.add_argument("--out", default="./img_out", help="产物目录，默认 ./img_out")
    ap.add_argument("--allow-upscale", action="store_true", help="允许把小图放大到目标宽")
    ap.add_argument("--base64", action="store_true", help="把 data URI 打印到 stdout")
    ap.add_argument("--snippet", action="store_true", help="生成 figure 片段文件")
    ap.add_argument("--alt", default="主题主视觉插画", help="img alt 文案（画面内容摘要）")
    ap.add_argument("--caption", default="图注：写明画面元素 ↔ 概念的映射", help="figcaption 文案")
    a = ap.parse_args()

    if not os.path.isfile(a.src):
        print(f"[x] 找不到源图：{a.src}", file=sys.stderr)
        return 1
    print(f"[*] 处理 {a.src}")
    out_path, data, info = prep(a.src, a.width, a.quality, a.format, a.out, a.allow_upscale)

    stem = os.path.splitext(os.path.basename(out_path))[0]
    b64_path = os.path.join(a.out, f"{stem}.b64.txt")
    with open(b64_path, "w", encoding="utf-8") as fh:
        fh.write(base64.b64encode(data).decode("ascii"))
    print(f"    base64 文本 → {b64_path}")

    if a.base64:
        mime = "image/webp" if info["ext"] == "webp" else "image/jpeg"
        sys.stdout.write(f"data:{mime};base64," + base64.b64encode(data).decode("ascii") + "\n")
    if a.snippet:
        figure_snippet(data, info["ext"], a.out, stem, a.alt, a.caption)

    return 2 if info["b64_kb"] > TARGET_KB else 0


if __name__ == "__main__":
    raise SystemExit(main())
