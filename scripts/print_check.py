#!/usr/bin/env python3
"""一页纸打印完整性实测脚本（print_check.py）

把技能自检清单里「打印实测过」一条封装成可执行断言，退出码 0 = 过、1 = 不过。
思路与 Windows 版 2026-10-30 的封装一致，并吸收其多断言的一处：
除原三哨兵外，增断言「宽表末行末格」，防长表纵向跨页时尾行被吞。

做法：在最不利状态下真打一份 PDF 再抽字断言——
  · 深色主题（localStorage 预置 theme=dark，验打印强制浅色的特异度）
  · 不做任何交互（讲解器停第 1 步、折叠区未打开、筛选不在全部、横滚在最左）
两段检查：
  A. 静态审计 12 项（只读源码，对照技能「打印标准件」，与技能正本自检句
     所写「脚本做静态审计 12 项」对齐）：@page A4 / 边距 13mm /
     print-color-adjust / 打印块存在 / 深色覆盖特异度 / 横滚解除 /
     宽表 min-width 归零（条件项） / 单元格断行 / pre 换行 / 图形限宽 /
     长表重复表头 / 状态展开机制。不适用的项记 N/A 不判负，判负即整体不过。
  B. PDF 实测断言：纸张为 A4（pdfinfo）；宽表最右列列名与末行末格出现在
     PDF 文本里（自动提取：列数最多那张表的首行末格、末行末格）；
     --expect 传入的每处文本（如讲解器最后一步标题、折叠区内关键词）都在。
文本比对按单元格文本块逐块断言（去空白后包含判断）：pdftotext 会把表格
单元格交错抽出，整格字符串往往对不上，逐块断言才稳；被裁掉的列整块消失，
照样能抓住。

用法：
  python3 print_check.py 页面.html [--expect "最后一步标题"] [--expect "折叠关键词"]
                           [--light] [--keep-pdf 目录]
依赖：python3 + playwright（自带 chromium）、poppler 的
pdftotext / pdfinfo。若所在环境的 Chromium 无法输出 PDF，改用 Playwright 自带 Chromium。
"""
import argparse
import html
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path


class TableCollector(HTMLParser):
    """Collect tables as rows of cell texts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("th", "td") and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self._cell is not None:
            # Keep the cell as a list of text chunks: pdftotext interleaves
            # table cells, so a whole-cell string rarely survives extraction
            # verbatim; assertions run per chunk instead.
            chunks = [" ".join(part.split()) for part in self._cell]
            self._row.append([c for c in chunks if c])
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


def norm(text: str) -> str:
    return re.sub(r"\s+", "", html.unescape(text or ""))


def extract_print_css(source: str) -> str:
    """Concatenate all @media print blocks (brace-balanced)."""
    out = []
    for m in re.finditer(r"@media[^{]*print[^{]*\{", source):
        depth, i = 1, m.end()
        while i < len(source) and depth:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
            i += 1
        out.append(source[m.end():i - 1])
    return "\n".join(out)


def static_audits(source: str):
    """12 static audits from the skill's 打印标准件. Returns (status, label,
    detail) with status pass/fail/na; 'na' = page lacks the feature the rule
    guards, so the rule cannot bite. Any 'fail' fails the whole check."""
    pcss = extract_print_css(source)
    has_table = "<table" in source
    has_tblwrap = "tblwrap" in source or "scrollx" in source
    page_m = re.search(r"@page\s*\{([^}]*)\}", source, re.I)
    page_rule = page_m.group(1) if page_m else ""
    checks = []

    def add(cond, label, detail="", applicable=True):
        if not applicable:
            checks.append(("na", label, "页面无此特征，不适用"))
        else:
            checks.append(("pass" if cond else "fail", label, "" if cond else detail))

    add(bool(page_m) and re.search(r"size\s*:\s*A4", page_rule, re.I) is not None,
        "S1 @page size:A4", "@page 缺失或未写 size:A4")
    add(bool(page_m) and "13mm" in page_rule,
        "S2 @page 边距 13mm", "@page 未写 margin:13mm")
    add("print-color-adjust" in source and "exact" in source,
        "S3 print-color-adjust:exact", "缺 print-color-adjust:exact，省墨会吞语义染底")
    add(bool(pcss), "S4 @media print 块存在", "整页没有打印样式块")
    add('html[data-theme="dark"]' in pcss or "html[data-theme='dark']" in pcss,
        "S5 打印覆盖含深色选择器（特异度）", "打印覆盖只有 :root，深色页会印出深底",
        applicable="data-theme" in source)
    add("overflow:visible" in pcss and ("tblwrap" in pcss or "scrollx" in pcss),
        "S6 横滚容器打印解除 overflow", "打印段没点名 .tblwrap/.scrollx 并置 overflow:visible",
        applicable=has_tblwrap)
    screen_minw = [int(v) for v in re.findall(r"min-width\s*:\s*(\d+)px",
                                              source.replace(pcss, ""))]
    add("min-width:0" in pcss.replace(" ", ""),
        "S7 宽表 min-width 打印归零", "页面给宽表设了 min-width，打印段没 min-width:0，右列出不了纸",
        applicable=any(v >= 600 for v in screen_minw))
    add("overflow-wrap" in pcss,
        "S8 单元格打印可断行 overflow-wrap", "打印段缺 th,td overflow-wrap，长串会撑宽",
        applicable=has_table)
    add("pre-wrap" in pcss,
        "S9 pre/code 打印换行 pre-wrap", "打印段缺 white-space:pre-wrap，长代码行会被裁",
        applicable="<pre" in source)
    add(bool(re.search(r"(svg|img|canvas)[^{]*\{[^}]*max-width\s*:\s*100%", pcss)),
        "S10 svg/img 打印限宽 max-width:100%", "打印段没给 svg/img/canvas 限宽",
        applicable="<svg" in source or "<img" in source)
    add("table-header-group" in pcss,
        "S11 长表跨页重复表头 thead", "打印段缺 thead{display:table-header-group}",
        applicable=has_table)
    add(("data-print-expand" in source and "beforeprint" in source)
        or "print-only" in source,
        "S12 状态展开机制在位", "有状态内容却没展开机制：data-print-expand 须配 beforeprint 脚本，或备 .print-only 静态版",
        applicable="data-print-expand" in source or "<details" in source)
    return checks


def pick_sentinels(source: str):
    """Return (rightmost header cell chunks, last-row last-cell chunks)."""
    parser = TableCollector()
    parser.feed(source)
    candidates = [t for t in parser.tables if len(t) >= 1 and len(t[0]) >= 2]
    if not candidates:
        return None, None
    table = max(candidates, key=lambda t: (len(t[0]), len(t)))
    return table[0][-1], table[-1][-1]


def chunks_present(chunks, haystack: str) -> bool:
    """Assert per text run: split each token into CJK / Latin-digit runs.

    pdftotext can split even a single cell's CJK and Latin runs apart and
    interleave neighbouring cells between them (fixture实测：同一格的
    「最右列哨兵RIGHTCOL」被抽成「最右列哨兵…列七…RIGHTCOL」), so matching
    must be run-level. A clipped column loses all its runs, so this still
    catches the failure the check exists for.
    """
    parts = chunks if isinstance(chunks, list) else [chunks]
    runs = []
    for part in parts:
        for token in part.split():
            runs.extend(re.findall(r"[A-Za-z0-9]+|[^\sA-Za-z0-9]+", token))
    return all(norm(run) in haystack for run in runs if len(norm(run)) >= 2)


def static_audit(src: str) -> list:
    """PC 兼容门禁接口（2026-10-31 对齐移植）：patch_print_baseline.py 动态
    加载本文件的 static_audit() 做判定，条目名与 PC 版逐字一致（其
    ITEM_TO_RULE 按名映射补丁规则），避免两处判定漂移。逻辑照 PC 版，
    只修一处：P2「@page 纸张与页边距」真验 size:A4 与 margin:13mm 的值
    （PC 版只验形状，写 Letter 也能过——已列入给 WB 的回补单）。
    返回 [{'name': str, 'ok': bool, 'hint': str, 可选 'warn': True}]。
    本文件 CLI 自身的判定仍走上面的 static_audits()（更严的那套）。"""
    css = "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", src, re.S | re.I))
    pb = extract_print_css(css)
    pbc = re.sub(r"\s+", "", pb)
    body_html = re.sub(r"<(script|style)\b.*?</\1>", "", src, flags=re.S | re.I)

    def item(name, ok, hint):
        return {"name": name, "ok": bool(ok), "hint": "" if ok else hint}

    res = [item("@media print 存在", bool(pb), "整页没有打印样式块，深色用户打出来是废纸")]

    page_m = re.search(r"@page[^{]*\{([^}]*)\}", css, re.I)
    page_ok = (
        bool(page_m)
        and re.search(r"size\s*:\s*A4", page_m.group(1), re.I) is not None
        and "13mm" in page_m.group(1)
    )
    res.append(item("@page 纸张与页边距", page_ok,
                    "缺 @page{size:A4;margin:13mm} → 纸张与边距全靠浏览器默认，版心不可控"))

    res.append(item("打印回浅色 · 特异性够", "html[data-theme" in pbc,
                    "打印覆盖只写了 :root；深色变量挂在 html[data-theme=dark] 上会压过它"))

    has_scroll = bool(re.search(r'class="[^"]*\b(tblwrap|scrollx)\b', body_html)
                      or re.search(r"<pre\b", body_html, re.I))
    res.append(item("横滚容器打印解除", (not has_scroll) or ("overflow:visible" in pbc),
                    "页面有 .tblwrap/.scrollx/pre 但打印段没写 overflow:visible → 超出版心的列/代码被静默裁掉"))
    res.append(item("表格撑满版心",
                    (not has_scroll) or ("table{width:100%!important}" in pbc or "table{width:100%" in pbc),
                    "打印段缺 table{width:100%!important} → 宽表仍按屏宽排版、右侧越界"))
    res.append(item("表格解除 min-width 撑宽",
                    (not has_scroll) or re.search(r"table\{[^}]*min-width:\s*(0|auto)", pbc) is not None,
                    "打印段缺 table{min-width:0!important} → width:100% 压不住 min-width 撑宽，右列照样被裁"))
    res.append(item("代码块换行",
                    (not re.search(r"<pre\b", body_html, re.I)) or ("white-space:pre-wrap" in pbc),
                    "有 <pre> 但打印段没写 white-space:pre-wrap → 长代码右侧被裁"))
    res.append(item("图形不超宽",
                    "svg,img,canvas{max-width:100%!important" in pbc or "svg,img,canvas{max-width:100%" in pbc
                    or "svg,img{max-width:100%!important" in pbc or "svg,img{max-width:100%" in pbc,
                    "打印段缺 svg,img,canvas{max-width:100%!important} → 宽 SVG / 流程图被裁"))
    res.append(item("语义染底不被省墨吞掉", "print-color-adjust:exact" in pbc,
                    "缺 print-color-adjust:exact → 省墨模式吞掉语义色染底"))

    big_avoid = re.search(r"[^{}]*\b(table|\.tblwrap|\.scrollx)\b[^{}]*\{[^}]*break-inside:\s*avoid", pb, re.I)
    res.append(item("大容器不做整块避断", not big_avoid,
                    "大容器或 table 写了 break-inside:avoid → 挤出整页空白或溢出裁切"))
    res.append(item("长表跨页重复表头",
                    ("table-header-group" in pbc) or not re.search(r"<table\b", body_html, re.I),
                    "长表缺 thead{display:table-header-group} → 跨页后没有表头"))
    has_details = bool(re.search(r"<details\b", body_html, re.I))
    has_expand = ("data-print-expand" in src) or ("print-only" in src) or ("beforeprint" in src)
    res.append(item("折叠/分页内容打印可展开", (not has_details) or has_expand,
                    "有 <details> 但没 data-print-expand / .print-only / beforeprint → 折叠区正文全丢"))
    if re.search(r"<summary\b[^>]*>[^<]*(答案|解析|查看)", body_html, re.I) and "data-print-keep-closed" not in src:
        res.append({"name": "自测答案区不被展开", "ok": False, "warn": True,
                    "hint": "有「答案/解析」折叠区却没加 data-print-keep-closed → 打印会把答案一并泄出"})
    return res


def render_pdf(page_path: Path, pdf_path: Path, dark: bool):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context()
        if dark:
            context.add_init_script(
                "try{localStorage.setItem('theme','dark')}catch(e){}"
            )
        page = context.new_page()
        page.goto(page_path.resolve().as_uri())
        page.wait_for_timeout(400)
        page.pdf(path=str(pdf_path), prefer_css_page_size=True, print_background=True)
        browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="一页纸打印完整性实测（退出码 0=过）")
    ap.add_argument("page", help="待测单文件 HTML")
    ap.add_argument("--expect", action="append", default=[],
                    help="额外哨兵文本（可多次）：讲解器最后一步标题、折叠区关键词等")
    ap.add_argument("--light", action="store_true",
                    help="不预置深色主题（默认以深色最不利状态打印）")
    ap.add_argument("--keep-pdf", metavar="DIR", help="把打出的 PDF 留到该目录")
    args = ap.parse_args()

    page_path = Path(args.page)
    if not page_path.exists():
        print(f"✗ 文件不存在：{page_path}")
        return 1
    source = page_path.read_text(encoding="utf-8", errors="ignore")

    print("── 静态审计（12 项，对照技能「打印标准件」）──")
    static_fail = False
    for status, label, detail in static_audits(source):
        mark = {"pass": "✓", "fail": "✗", "na": "–"}[status]
        print(f"{mark} {label}" + (f" — {detail}" if status != "pass" and detail else ""))
        static_fail = static_fail or status == "fail"

    results = []  # dynamic (PDF) checks: (ok, label, detail)

    # auto sentinels from widest table
    rightmost, last_cell = pick_sentinels(source)

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "print_check.pdf"
        try:
            render_pdf(page_path, pdf_path, dark=not args.light)
        except Exception as exc:  # noqa: BLE001
            print(f"✗ 打印失败：{exc}")
            return 1
        if args.keep_pdf:
            keep_dir = Path(args.keep_pdf)
            keep_dir.mkdir(parents=True, exist_ok=True)
            kept = keep_dir / (page_path.stem + ".pdf")
            kept.write_bytes(pdf_path.read_bytes())
            print(f"（PDF 已留存：{kept}）")

        info = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True,
                              text=True).stdout
        m = re.search(r"Page size:\s*(.+)", info)
        size_line = m.group(1).strip() if m else ""
        ok = "A4" in size_line or (
            "595" in size_line and "842" in size_line.replace(".89", "")
        )
        results.append((ok, "PDF 纸张为 A4", f"pdfinfo: {size_line}"))

        text = subprocess.run(["pdftotext", str(pdf_path), "-"], capture_output=True,
                              text=True).stdout
        haystack = norm(text)

        checks = []
        if rightmost:
            checks.append(("宽表最右列列名", rightmost))
        if last_cell:
            checks.append(("宽表末行末格", last_cell))
        # Auto: folded <details> body — first non-keep-closed one (PC ③).
        # Manual --expect for these was a false-pass pit (forget to pass =
        # silently unchecked), so extraction is automatic since 2026-10-31.
        body_html = re.sub(r"<(script|style)\b.*?</\1>", " ", source, flags=re.S | re.I)
        for m in re.finditer(r"<details\b([^>]*)>(.*?)</details>", body_html, re.S | re.I):
            if "data-print-keep-closed" in m.group(1):
                continue
            inner = re.sub(r"<summary\b[^>]*>.*?</summary>", " ", m.group(2), flags=re.S | re.I)
            text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inner)).split())
            if len(text) >= 8:
                checks.append(("折叠区正文（自动）", [text[:24]]))
            break
        # Auto: stepper last step + its extra fields, parsed by jslit (PC ④⑤).
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import jslit

            arr = jslit.find_array(source)
        except Exception:
            arr = None
        if arr:
            _title, _body, _terms, _extras = jslit.step_fields(arr["steps"][-1])
            text = " ".join((_body or _title).split())
            if len(text) >= 6:
                checks.append(("讲解器末步（自动）", [text[:20]]))
            extra_text = " ".join(t for _lbl, t in _extras if t)
            if len(extra_text) >= 8:
                checks.append(("讲解器附加字段（自动）", [extra_text[:20]]))
        for extra in args.expect:
            checks.append(("--expect 哨兵", [extra]))
        if not checks:
            results.append((False, "哨兵断言", "页面无可用宽表、也未传 --expect"))
        for label, chunks in checks:
            ok = chunks_present(chunks, haystack)
            shown = " ".join(chunks)
            results.append((ok, f"{label}「{shown}」",
                            "" if ok else "PDF 文本里找不到（疑被裁掉/未展开）"))

    print("── PDF 实测 ──")
    dyn_ok = True
    for ok, label, detail in results:
        print(("✓" if ok else "✗") + f" {label}" + (f" — {detail}" if detail and not ok else ""))
        dyn_ok = dyn_ok and ok
    all_ok = dyn_ok and not static_fail
    print("打印实测：" + ("PASS" if all_ok else "FAIL"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
