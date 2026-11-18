#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""print_check.py —— 一页纸「打印完整性」实测门禁

不是读代码判对错，而是真打 PDF 再抽字断言：宽表最右列 / 折叠区正文 / 讲解器末步
是否真的进了纸面。overflow-x:auto 的容器在 Chrome 打印时只打当前可见那一截，
不报错、不提示——只有真打一份才看得见。

用法（在技能根目录下跑，或在任意目录用绝对路径调）：
    python scripts/print_check.py 页面.html
    python scripts/print_check.py 页面.html --theme light --keep --json

退出码：0 全过 / 1 有 FAIL / 2 环境缺失（找不到 Chrome 或 pdftotext）

依赖：本机 Chrome（或 Edge）+ poppler 的 pdftotext。纯标准库，无第三方包。
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]
PDFTOTEXT_CANDIDATES = [
    r"C:\tools\poppler\Library\bin\pdftotext.exe",
    "/usr/bin/pdftotext",
    "/usr/local/bin/pdftotext",
    "/opt/homebrew/bin/pdftotext",
]

TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)


# ---------------------------------------------------------------- 工具
def find_exe(env_key: str, candidates: list[str], names: list[str]) -> str | None:
    p = os.environ.get(env_key)
    if p and Path(p).exists():
        return p
    for c in candidates:
        if Path(c).exists():
            return c
    for n in names:
        w = shutil.which(n)
        if w:
            return w
    return None


def norm(s: str) -> str:
    """HTML 源码侧归一化：去标签、反转义、抹掉所有空白（中文跨行会被 pdftotext 折断）。"""
    s = TAG_RE.sub(" ", s)
    s = html_mod.unescape(s)
    return re.sub(r"\s+", "", s)


def norm_pdf(s: str) -> str:
    """PDF 抽字侧归一化：只反转义 + 抹空白，**绝不剥标签**。

    ⚠️ 不能复用 norm()：PDF 正文里天然含 `<`（如 `<1.15.0`、`helm show chart <chart>`），
    TAG_RE 的 `<[^>]+>` 会把从 `<` 到下一个 `>` 之间的正文整段删掉。实测 Helm 页
    被删 4433 字（正好吞掉哨兵所在的整块命令速查表）→ 内容明明印在纸上却判「缺失」。
    """
    s = html_mod.unescape(s)
    return re.sub(r"\s+", "", s)


def brace_block(text: str, start: int) -> str:
    """从 start 处的 '{' 起做花括号配对，返回块内文本（含外层括号）。"""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def print_blocks(css: str) -> list[str]:
    """取出所有 @media print 块（含嵌套），逐个返回。"""
    out = []
    for m in re.finditer(r"@media[^{]*\bprint\b[^{]*\{", css):
        out.append(brace_block(css, m.end() - 1))
    return out


# ---------------------------------------------------------------- 静态审计
def static_audit(src: str) -> list[dict]:
    css = "\n".join(m.group(0) for m in re.finditer(r"<style\b[^>]*>(.*?)</style>", src, re.S | re.I))
    blocks = print_blocks(css)
    pb = "\n".join(blocks)
    pbc = re.sub(r"\s+", "", pb)  # 去空白便于子串匹配
    body_html = SCRIPT_STYLE_RE.sub("", src)

    def item(name, ok, hint):
        return {"name": name, "ok": bool(ok), "hint": "" if ok else hint}

    res = []
    res.append(item("@media print 存在", bool(blocks), "整页没有打印样式块，深色用户打出来是废纸"))

    # P2 不只看 @page 的形状：只验「有 size 字样」的话，写 size:Letter 同样能过（假绿）。
    # 真验 size:A4 与 margin:13mm —— 版心尺寸与页边距直接决定行宽与页脚位置。
    page_m = re.search(r"@page[^{]*\{([^}]*)\}", css, re.I)
    page_decl = page_m.group(1) if page_m else ""
    has_a4 = bool(re.search(r"(?:^|[;{\s])size\s*:\s*A4\b", page_decl, re.I))
    has_margin13 = bool(re.search(r"(?:^|[;{\s])margin\s*:\s*13mm\b", page_decl, re.I))
    has_page = has_a4 and has_margin13
    if not page_m:
        page_hint = "缺 @page{size:A4;margin:13mm} → 纸张与边距全靠浏览器默认，版心不可控"
    elif not has_a4:
        page_hint = "@page 有 size 但不是 A4（size:Letter 这类也能过形状关）→ 纸张尺寸不受控，版心随之漂移"
    elif not has_margin13:
        page_hint = "@page 缺 margin:13mm → 页边距靠浏览器默认，版心宽度与页脚位置都不对"
    else:
        page_hint = ""
    res.append(item("@page 纸张与页边距", has_page, page_hint))

    res.append(
        item(
            "打印回浅色 · 特异性够",
            "html[data-theme" in pbc,
            "打印覆盖只写了 :root；深色变量挂在 html[data-theme=dark] 上会压过它 → 必须写 :root,html[data-theme=dark]",
        )
    )

    has_scroll_container = bool(
        re.search(r'class="[^"]*\b(tblwrap|scrollx)\b', body_html) or re.search(r"<pre\b", body_html, re.I)
    )
    res.append(
        item(
            "横滚容器打印解除",
            (not has_scroll_container) or ("overflow:visible" in pbc),
            "页面有 .tblwrap/.scrollx/pre 但打印段没写 overflow:visible → 超出版心的列/代码被静默裁掉",
        )
    )

    res.append(
        item(
            "表格撑满版心",
            (not has_scroll_container) or ("table{width:100%!important}" in pbc or "table{width:100%" in pbc),
            "打印段缺 table{width:100%!important} → 宽表仍按屏宽排版、右侧越界",
        )
    )

    # 光写 width:100% 压不住 min-width（实测：min-width:1400px 的宽表照旧被裁）
    res.append(
        item(
            "表格解除 min-width 撑宽",
            (not has_scroll_container)
            or re.search(r"table\{[^}]*min-width:\s*(0|auto)", pbc) is not None,
            "打印段缺 table{min-width:0!important} → width:100% 压不住 min-width:1400px 这类撑宽，右列照样被裁",
        )
    )

    res.append(
        item(
            "代码块换行",
            (not re.search(r"<pre\b", body_html, re.I)) or ("white-space:pre-wrap" in pbc),
            "有 <pre> 但打印段没写 white-space:pre-wrap → 不换行的长代码右侧被裁",
        )
    )

    # P8 原先用四个写死整串匹配、且无门控：页面里根本没有图也判负，选择器换个顺序就误判。
    # 改为「按选择器逐条解析」+「页面确实有 <svg>/<img> 才判」：
    # 逐条看打印段里写了 max-width:100% 的规则覆盖了哪些图形标签，只有页面实际出现的
    # svg / img 全被覆盖才算过。这样 figure svg 这类后代选择器、img,svg 这类换序、
    # 只写 canvas 却漏了 svg 的写法，都能判对。
    present_gfx = {t for t in ("svg", "img") if re.search(rf"<{t}\b", body_html, re.I)}
    covered_gfx = set()
    for sel, decls in re.findall(r"([^{}]+)\{([^{}]*)\}", pb):
        if not re.search(r"max-width\s*:\s*100%", decls, re.I):
            continue
        for one in sel.split(","):
            for t in ("svg", "img", "canvas"):
                if re.search(rf"\b{t}\b", one, re.I):
                    covered_gfx.add(t)
    res.append(
        item(
            "图形不超宽",
            (not present_gfx) or present_gfx <= covered_gfx,
            "打印段缺 svg,img,canvas{max-width:100%!important;height:auto!important} → 宽 SVG / 流程图被裁",
        )
    )

    res.append(
        item(
            "语义染底不被省墨吞掉",
            "print-color-adjust:exact" in pbc,
            "缺 print-color-adjust:exact → 浏览器省墨模式吞掉语义色染底，图例与状态色全白",
        )
    )

    big_avoid = re.search(r"[^{}]*\b(table|\.tblwrap|\.scrollx)\b[^{}]*\{[^}]*break-inside:\s*avoid", pb, re.I)
    res.append(
        item(
            "大容器不做整块避断",
            not big_avoid,
            "装宽表/长清单的大容器或 table 本身写了 break-inside:avoid → 挤出整页空白或溢出裁切；只有小卡片该 avoid",
        )
    )

    res.append(
        item(
            "长表跨页重复表头",
            ("table-header-group" in pbc) or not re.search(r"<table\b", body_html, re.I),
            "长表缺 thead{display:table-header-group} → 跨页后每页没有表头，第二页起看不懂列",
        )
    )

    has_details = bool(re.search(r"<details\b", body_html, re.I))
    has_expand = ("data-print-expand" in src) or ("print-only" in src) or ("beforeprint" in src)
    res.append(
        item(
            "折叠/分页内容打印可展开",
            (not has_details) or has_expand,
            "有 <details> 但没 data-print-expand / .print-only / beforeprint → 打印只打默认关合状态，折叠区正文全丢",
        )
    )

    if re.search(r"<summary\b[^>]*>[^<]*(答案|解析|查看)", body_html, re.I) and "data-print-keep-closed" not in src:
        res.append(
            {
                "name": "自测答案区不被展开",
                "ok": False,
                "warn": True,
                "hint": "有「答案/解析」折叠区却没加 data-print-keep-closed → 打印会把答案一并泄出",
            }
        )
    return res


# ---------------------------------------------------------------- 步骤数组
_STEP_ARRAYS = ("QSTEPS", "STEPS", "STEPS_DATA", "STEP_DATA", "ST", "steps")


def _unescape_js(raw: str) -> str:
    out, i = [], 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            out.append({"'": "'", '"': '"', "n": "\n", "t": "\t", "\\": "\\"}.get(raw[i + 1], "\\" + raw[i + 1]))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _js_literal_to_obj(lit: str):
    """JS 字面量 → Python 对象（容错单引号、裸键、尾逗号）。

    自包含实现，不依赖库外模块 —— 门禁脚本必须能单独拷走就跑。
    """
    out, i, n = [], 0, len(lit)
    while i < n:
        c = lit[i]
        if c in "\"'`":
            q = c
            i += 1
            buf = []
            while i < n:
                ch = lit[i]
                if ch == "\\" and i + 1 < n:
                    buf.append(lit[i : i + 2])
                    i += 2
                    continue
                if ch == q:
                    i += 1
                    break
                buf.append(ch)
                i += 1
            s = _unescape_js("".join(buf))
            s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
            out.append('"' + s + '"')
            continue
        if c.isalpha() or c in "_$":
            j = i
            while j < n and (lit[j].isalnum() or lit[j] in "_$"):
                j += 1
            word = lit[i:j]
            k = j
            while k < n and lit[k] in " \t\r\n":
                k += 1
            if k < n and lit[k] == ":" and word not in ("true", "false", "null"):
                out.append('"' + word + '"')
            else:
                out.append(word)
            i = j
            continue
        out.append(c)
        i += 1
    return json.loads(re.sub(r",(\s*[\]}])", r"\1", "".join(out)))


_RE_JOIN = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\s*\.join\(\s*(['\"])(.*?)\2\s*\)", re.S)


def _collapse_join(lit: str) -> str:
    """[ 'a', 'b' ].join('\\n') → 单个字符串（Helm / K8s 进阶 的 term 就是这个写法）。"""

    def rep(m):
        try:
            arr = _js_literal_to_obj("[" + m.group(1) + "]")
        except Exception:
            return m.group(0)
        if not all(isinstance(x, str) for x in arr):
            return m.group(0)
        joined = _unescape_js(m.group(3)).join(arr)
        esc = joined.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\t", "\\t")
        return "'" + esc + "'"

    prev = None
    while prev != lit:
        prev = lit
        lit = _RE_JOIN.sub(rep, lit)
    return lit


def _find_steps(src: str):
    """找页面里的步骤数组，返回 {name, keyword, steps}；没有则 None。"""
    for name in _STEP_ARRAYS:
        pat = re.compile(r"(?:\b(var|let|const)\s+|window\.)?" + r"\b" + name + r"\s*=\s*\[")
        for m in pat.finditer(src):
            i = m.end() - 1
            depth = 0
            end = None
            for k in range(i, len(src)):
                ch = src[k]
                if ch in "[{":
                    depth += 1
                elif ch in "]}":
                    depth -= 1
                    if depth == 0:
                        end = k + 1
                        break
            if end is None:
                continue
            try:
                obj = _js_literal_to_obj(_collapse_join(src[i:end]))
            except Exception:
                continue
            if isinstance(obj, list) and len(obj) >= 2:
                kw = m.group(1) or ("window" if m.group(0).startswith("window.") else "global")
                return {"name": name, "keyword": kw, "steps": obj}
    return None


def _as_text(v) -> str:
    if isinstance(v, (list, tuple)):
        return "\n".join(_as_text(x) for x in v)
    return str(v) if v is not None else ""


_TITLE_KEYS = ("t", "title", "name", "h")
_BODY_KEYS = ("say", "body", "b", "d", "desc")
_ID_KEYS = ("term", "terms", "k", "key", "id", "cls", "class", "icon", "type", "href")


def _step_extra_text(item) -> str:
    """取一步的附加字段文本（demo 此刻演示里 / 以为 / 其实 / do / done / plan）。"""
    if not isinstance(item, dict):
        return ""
    out = []
    for k, v in item.items():
        if k in _TITLE_KEYS or k in _ID_KEYS or k in _BODY_KEYS:
            continue
        if k in ("term", "terms", "x", "y", "z", "c", "vis", "w", "h"):
            continue
        t = _as_text(v).strip()
        if t:
            out.append(t)
    return "\n".join(out)


def _step_text(item) -> tuple[str, str]:
    """取一步的 (标题, 正文)。

    支持 [标题, 正文] 与 {t/say} 两种写法；正文键实测有 say / body / b / d / desc，
    还有整步用 do / done / plan 几个并列字段的（MLOps 导论页）—— 都没有时
    把除标题/术语外的其余字段按顺序拼起来，别让哨兵退化成只有标题。
    """
    if isinstance(item, (list, tuple)):
        return (_as_text(item[0]) if item else ""), (_as_text(item[1]) if len(item) > 1 else "")
    if isinstance(item, dict):
        title = ""
        for k in _TITLE_KEYS:
            if item.get(k):
                title = _as_text(item[k])
                break
        body = ""
        for k in _BODY_KEYS:
            if item.get(k):
                body = _as_text(item[k])
                break
        # 附加字段（demo 此刻演示里 / 以为 / 其实 / do / done / plan）也算这一步的内容：
        # 不纳入哨兵就查不出它们被漏掉（实测机器学习页「此刻演示里」整段没印）。
        extras = [
            _as_text(v)
            for k, v in item.items()
            if k not in _TITLE_KEYS
            and k not in _ID_KEYS
            and k not in _BODY_KEYS
            and k not in ("term", "terms", "x", "y", "z", "c", "vis", "w", "h")
            and _as_text(v).strip()
        ]
        body = "\n".join([body] + extras) if body else "\n".join(extras)
        return title, body
    return _as_text(item), ""


# ---------------------------------------------------------------- 哨兵抽取
def sentinels(src: str) -> list[dict]:
    """从源码里找「打印时最容易丢」的几处文字，作为 PDF 抽字断言的目标。"""
    out = []
    body = SCRIPT_STYLE_RE.sub("", src)

    # ① 宽表最右列：取列数最多的那张表的最后一个表头（＋末行末格，仅在页面里唯一时加）
    tables = re.findall(r"<table\b.*?</table>", body, re.S | re.I)
    best, best_cols, best_html = None, 0, ""
    for t in tables:
        ths = re.findall(r"<th\b[^>]*>(.*?)</th>", t, re.S | re.I)
        if len(ths) > best_cols:
            best, best_cols, best_html = ths, len(ths), t
    if best and best_cols >= 3:
        text = norm(best[-1])
        if len(text) >= 2:
            out.append({"kind": "宽表最右列", "text": text, "strict": True})
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", best_html, re.S | re.I)
        if rows:
            tds = re.findall(r"<td\b[^>]*>(.*?)</td>", rows[-1], re.S | re.I)
            cell = norm(tds[-1]) if tds else ""
            body_text = norm(body)
            if len(cell) >= 4 and body_text.count(cell) == 1:
                out.append({"kind": "宽表末行末格", "text": cell, "strict": True})

    # ② 折叠区正文：<details> 里 summary 之后的内容
    for m in re.finditer(r"<details\b([^>]*)>(.*?)</details>", body, re.S | re.I):
        attrs, inner = m.group(1), m.group(2)
        if "data-print-keep-closed" in attrs:
            continue
        body_part = re.sub(r"<summary\b[^>]*>.*?</summary>", " ", inner, flags=re.S | re.I)
        text = norm(body_part)
        if len(text) >= 8:
            out.append({"kind": "折叠区正文", "text": text[:24], "strict": True})
            break

    # ③ 讲解器 / 步骤切换器：最后一步的内容（默认只渲染当前步，最容易整段丢）
    # ⚠️ 数组名不止 QSTEPS：实测有 STEPS / steps / ST 四种，且 const 声明的不进 window，
    #    运行时展开脚本读不到 → 只认 QSTEPS 会让这类页面整段丢内容还判「通过」。
    arr = _find_steps(src)
    if arr:
        steps = arr["steps"]
        title, say = _step_text(steps[-1])
        text = norm(say or title)
        if len(text) >= 6:
            out.append(
                {
                    "kind": "讲解器末步",
                    "text": text[:20],
                    "strict": True,
                    "note": f"数组 {arr['name']}（{arr['keyword']}）共 {len(steps)} 步，只断言末步",
                }
            )
        # 附加字段单独断言：「此刻演示里」「以为/其实」这类段落是独立数据，
        # 只断言正文的话它们整块丢了也查不出来（实测机器学习页就是这样漏的）。
        extra = norm(_step_extra_text(steps[-1]))
        if len(extra) >= 8:
            out.append(
                {
                    "kind": "讲解器附加",
                    "text": extra[:20],
                    "strict": True,
                    "note": "末步的附加字段（demo / 以为 / do 等）",
                }
            )
    return out


# ---------------------------------------------------------------- 真打 PDF
def make_harness_copy(src: str, theme: str, dst: Path) -> None:
    harness = (
        "\n<script>/* print-check harness: 强制主题，验打印覆盖特异性 */\n"
        "(function(){var t=%s;function f(){if(t){document.documentElement.setAttribute('data-theme',t);}}\n"
        "f();addEventListener('load',f);addEventListener('beforeprint',f);})();\n"
        "</script>\n" % json.dumps(theme)
    )
    idx = src.lower().rfind("</body>")
    out = (src[:idx] + harness + src[idx:]) if idx != -1 else (src + harness)
    dst.write_text(out, encoding="utf-8")


def print_pdf(chrome: str, page: Path, pdf: Path) -> None:
    profile = Path(tempfile.mkdtemp(prefix="pc_profile_"))
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=12000",
        "--run-all-compositor-stages-before-draw",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf}",
        page.as_uri(),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    # ⚠️ Windows 上 chrome.exe 会先返回、PDF 稍后才落盘 —— 必须轮询等，不能查一次就判失败
    deadline = time.time() + 90
    last = -1
    while time.time() < deadline:
        if pdf.exists():
            size = pdf.stat().st_size
            if size > 2000 and size == last:
                return
            last = size
        time.sleep(0.3)
    if not pdf.exists() or pdf.stat().st_size < 2000:
        raise RuntimeError(f"Chrome 打印失败（stdout/stderr 见下）\n{r.stdout[-800:]}\n{r.stderr[-800:]}")


def pdf_text(pdftotext: str, pdf: Path) -> str:
    r = subprocess.run([pdftotext, "-enc", "UTF-8", str(pdf), "-"], capture_output=True, timeout=120)
    return r.stdout.decode("utf-8", "ignore")


RE_WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)"[^>]*>(.*?)</word>', re.S)


def pdf_word_pages(pdftotext: str, pdf: Path) -> list[list[tuple[float, float, float, str]]]:
    """用 -bbox-layout 取每页的词及其坐标：(xMin, yMin, xMax, text)。"""
    r = subprocess.run(
        [pdftotext, "-enc", "UTF-8", "-bbox-layout", str(pdf), "-"], capture_output=True, timeout=180
    )
    xml = r.stdout.decode("utf-8", "ignore")
    pages = []
    for pg in re.split(r"<page\b", xml)[1:]:
        pages.append(
            [
                (float(m.group(1)), float(m.group(2)), float(m.group(3)), m.group(4))
                for m in RE_WORD.finditer(pg)
            ]
        )
    return pages


def _sort_by_line(ws, tol: float = 2.0):
    """按 (视觉行, 列内 x) 排序。

    ⚠️ 不能直接 round(y,1) 排序：同一行的词 y 会有 0.2~0.4 的抖动
    （实测「处」y=207.9、「secret」y=207.7），四舍五入后行内顺序被打乱，
    拼出来的句子变成「几 secret 处要对齐」。必须按容差聚行。
    """
    lines: list[list] = []  # [y_ref, [words]]
    for w in sorted(ws, key=lambda t: (t[1], t[0])):
        for ln in lines:
            if abs(ln[0] - w[1]) <= tol:
                ln[1].append(w)
                break
        else:
            lines.append([w[1], [w]])
    out = []
    for _y, items in lines:
        items.sort(key=lambda t: t[0])
        out.extend(items)
    return out


def column_text(ws, seed, tol_x: float = 20.0, gap: float = 12.0) -> str:
    """取 seed 所在的「栏」文本：以左边缘锚定，逐行向右扩张。

    折行的格子每一行都从同一个 x 起头（实测「像门卫指路：本人」/「不在这儿，去这个」
    /「新地址找」三行 xMin 全是 206.1）。所以用 xMin 对锚比用「整行连续片段」更稳：
    后者会把左侧邻列的尾巴（如「307」「认」）一起圈进来，把哨兵插断。

    逐行向右扩张（字距 <= gap）是为了接住同一行里被空格切开的后续词。
    """
    lines: list[list] = []  # [y_ref, [words]]
    for w in sorted(ws, key=lambda t: (t[1], t[0])):
        for ln in lines:
            if abs(ln[0] - w[1]) <= 2.0:
                ln[1].append(w)
                break
        else:
            lines.append([w[1], [w]])
    out: list[str] = []
    for y, items in lines:
        items.sort(key=lambda t: t[0])
        anchor = None
        for w in items:
            if abs(w[0] - seed[0]) <= tol_x:
                anchor = w
                break
        if anchor is None:
            continue
        i = items.index(anchor)
        j = i
        while j + 1 < len(items) and items[j + 1][0] - items[j][2] <= gap:
            j += 1
        out.append("".join(t[3] for t in items[i : j + 1]))
    return "".join(out)


def band_text(ws, seed, tol_x: float = 20.0, gap: float = 12.0) -> str:
    """取 seed 词所在的「列带」文本：同列跨行拼接，不掺邻列。

    做法：先在 seed 那一视觉行上，按字距（<= gap）向左右扩张出一个连续片段，
    该片段就是这一格/这一栏的实际宽度；再把全页 xMin 落在
    [片段左-20, 片段右+20] 的词按 (行, x) 排序拼起来。

    这样「一格内容折成两行」不会被左侧邻列挤到中间，而邻列内容也进不来。
    """
    line = sorted([w for w in ws if abs(w[1] - seed[1]) <= 2.0], key=lambda t: t[0])
    if not line:
        return ""
    try:
        i = line.index(seed)
    except ValueError:
        i = 0
    lo = hi = i
    while lo > 0 and line[lo][0] - line[lo - 1][2] <= gap:
        lo -= 1
    while hi < len(line) - 1 and line[hi + 1][0] - line[hi][2] <= gap:
        hi += 1
    x0, x1 = line[lo][0], line[hi][2]
    picked = [w for w in ws if (x0 - tol_x) <= w[0] <= (x1 + tol_x)]
    return "".join(t[3] for t in _sort_by_line(picked))


def found_in_pdf(target: str, flat: str, pages) -> bool:
    """哨兵是否真的印在纸上。

    先查阅读顺序全文（覆盖绝大多数情况）；未命中再用「列带」视图复查 ——
    后者只收集 PDF 里**实际存在**的词，所以内容真丢时照样判失败，
    修正的只是「折行后被邻列插断」导致的抽取顺序假失败。
    """
    if target in flat:
        return True
    if not pages:
        return False
    for ws in pages:
        for n in (4, 3, 2):
            head = target[:n]
            if len(head) < 2:
                continue
            for w in ws:
                if head in w[3] and (target in column_text(ws, w) or target in band_text(ws, w)):
                    return True
    return False


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="一页纸打印完整性实测")
    ap.add_argument("html", help="待测 HTML 路径")
    ap.add_argument("--theme", choices=["dark", "light", "both"], default="both", help="打印时的主题（默认两套都打）")
    ap.add_argument("--keep", action="store_true", help="保留 PDF 与临时副本，便于人工看")
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告")
    ap.add_argument("--static-only", action="store_true", help="只跑静态审计，不真打 PDF")
    ap.add_argument(
        "--fix",
        action="store_true",
        help="先跑 patch_print_baseline.py 自动补齐打印基线，再复测（一条命令到位）",
    )
    args = ap.parse_args()

    page = Path(args.html).resolve()
    if not page.exists():
        print(f"文件不存在：{page}", file=sys.stderr)
        return 2

    # --fix：先自动补齐（移动端断点限定 screen、按审计缺口注入 CSS、
    # 折叠区/标签页/步骤切换器的展开与全量副本、筛选行展开），再照常复测。
    if args.fix:
        patcher = Path(__file__).resolve().parent / "patch_print_baseline.py"
        if not patcher.exists():
            print(f"[--fix] 找不到 {patcher.name}，跳过自动补齐", file=sys.stderr)
        else:
            print(f"[--fix] 先跑 {patcher.name} …")
            r = subprocess.run([sys.executable, str(patcher), str(page)], capture_output=True, text=True)
            for line in (r.stdout or "").strip().splitlines():
                print("  " + line)
            if r.returncode != 0:
                print("[--fix] 自动补齐失败：\n" + (r.stderr or ""), file=sys.stderr)
            print("[--fix] 补齐完成，开始复测\n")

    src = page.read_text(encoding="utf-8", errors="ignore")

    stat = static_audit(src)
    sent = sentinels(src)

    report = {"page": str(page), "static": stat, "sentinels": sent, "prints": [], "env": {}}
    chrome = find_exe("CHROME_PATH", CHROME_CANDIDATES, ["chrome", "google-chrome", "chromium", "msedge"])
    pdftotext = find_exe("PDFTOTEXT_PATH", PDFTOTEXT_CANDIDATES, ["pdftotext"])
    report["env"] = {"chrome": chrome or "", "pdftotext": pdftotext or ""}

    dynamic_ok = True
    if not args.static_only:
        if not chrome or not pdftotext:
            print("[环境缺失] 找不到 Chrome 或 pdftotext → 无法真打 PDF（装 poppler 或设 CHROME_PATH / PDFTOTEXT_PATH）", file=sys.stderr)
            dynamic_ok = None
        else:
            themes = ["dark", "light"] if args.theme == "both" else [args.theme]
            workdir = Path(tempfile.mkdtemp(prefix="pc_run_"))
            for theme in themes:
                copy = workdir / f"{page.stem}.{theme}.html"
                pdf = workdir / f"{page.stem}.{theme}.pdf"
                make_harness_copy(src, theme, copy)
                try:
                    print_pdf(chrome, copy, pdf)
                except Exception as e:  # noqa: BLE001
                    report["prints"].append({"theme": theme, "error": str(e)})
                    dynamic_ok = False
                    continue
                txt = norm_pdf(pdf_text(pdftotext, pdf))
                try:
                    pages = pdf_word_pages(pdftotext, pdf)
                except Exception:  # noqa: BLE001  坐标视图拿不到不该让门禁崩
                    pages = []
                hits = []
                for s in sent:
                    hits.append({**s, "found": found_in_pdf(s["text"], txt, pages)})
                report["prints"].append(
                    {"theme": theme, "pdf": str(pdf), "chars": len(txt), "hits": hits}
                )
                if any(not h["found"] and h.get("strict") for h in hits):
                    dynamic_ok = False
                if not args.keep:
                    pass  # 保留临时目录，最后统一清
            if args.keep:
                print(f"[保留] PDF 与副本在：{workdir}")
            else:
                shutil.rmtree(workdir, ignore_errors=True)

    # ------------------------------------------------------------ 输出
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        fails = [s for s in stat if not s["ok"] and not s.get("warn")]
        warns = [s for s in stat if not s["ok"] and s.get("warn")]
        print(f"\n[打印实测] {page.name}")
        print(f"静态审计：{len(stat)} 项 → 通过 {len(stat) - len(fails) - len(warns)} / 失败 {len(fails)} / 待人工 {len(warns)}")
        for s in fails:
            print(f"  ✗ {s['name']}：{s['hint']}")
        for s in warns:
            print(f"  ! {s['name']}：{s['hint']}")
        if report["prints"]:
            print(f"真打 PDF：{len(report['prints'])} 份（主题 {'/'.join(p['theme'] for p in report['prints'])}）")
            for p in report["prints"]:
                if p.get("error"):
                    print(f"  [{p['theme']}] 打印失败：{p['error'].splitlines()[0]}")
                    continue
                bad = [h for h in p["hits"] if not h["found"]]
                print(f"  [{p['theme']}] 抽字 {p['chars']} 字，哨兵 {len(p['hits'])} 处 → 缺 {len(bad)} 处")
                for h in p["hits"]:
                    mark = "✓" if h["found"] else "✗"
                    print(f"    {mark} {h['kind']}「{h['text']}」")
        if dynamic_ok is None:
            verdict = "未验（环境缺失，不算通过）"
        else:
            verdict = "通过" if (not fails and dynamic_ok) else "不过"
        print(f"结论：打印基线{verdict}\n")

    bad_static = any(not s["ok"] and not s.get("warn") for s in stat)
    # 退出码 0 通过 / 1 不过 / 2 环境缺失。环境缺失绝不许返回 0——
    # 旧逻辑用 `dynamic_ok is not False` 判，None（找不到 Chrome/pdftotext）时为真，
    # 「静态全过 + 环境没装」实际返回 0，是假绿（2026-10-31 修）。
    if dynamic_ok is None:
        return 2
    return 0 if (not bad_static and dynamic_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
