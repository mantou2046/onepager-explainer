# -*- coding: utf-8 -*-
"""从 HTML 里读出「步骤数组」并归一化 —— 打印副本静态生成用。

为什么要自己解析：这些页面的步骤数据写在 JS 字面量里（QSTEPS / STEPS / ST /
steps），而 `const`/`let` 声明不进 window，运行时脚本读不到 → 打印只剩当前一步。
所以在构建期（Python）把它解析出来，直接生成静态打印副本，不依赖运行时。
"""
from __future__ import annotations

import json
import re

ARRAY_NAMES = ("QSTEPS", "STEPS", "STEPS_DATA", "STEP_DATA", "ST", "steps")


def _unescape(raw: str) -> str:
    out = []
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            n = raw[i + 1]
            mapping = {"'": "'", '"': '"', "n": "\n", "t": "\t", "\\": "\\"}
            out.append(mapping.get(n, "\\" + n))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def js_literal_to_obj(lit: str):
    """JS 数组/对象字面量 → Python 对象（容错单引号、裸键、尾逗号）。"""
    out = []
    i, n = 0, len(lit)
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
            s = _unescape("".join(buf))
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
    text = "".join(out)
    text = re.sub(r",(\s*[\]}])", r"\1", text)
    return json.loads(text)


RE_JOIN = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\s*\.join\(\s*(['\"])(.*?)\2\s*\)", re.S)


def collapse_join(lit: str) -> str:
    """[ 'a', 'b' ].join('\\n') → 一个字符串字面量。

    实测 Helm / K8s 进阶 的 QSTEPS 里每步 term 都是这个写法，纯字面量解析读不了。
    """

    def rep(m):
        inner, _q, sep = m.group(1), m.group(2), m.group(3)
        try:
            arr = js_literal_to_obj("[" + inner + "]")
        except Exception:
            return m.group(0)
        if not all(isinstance(x, str) for x in arr):
            return m.group(0)
        joined = _unescape(sep).join(arr)
        esc = (
            joined.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        return "'" + esc + "'"

    prev = None
    while prev != lit:
        prev = lit
        lit = RE_JOIN.sub(rep, lit)
    return lit


def find_array(src: str):
    """找第一个能配平且能解析的步骤数组。

    返回 dict(name, keyword, steps, start, end)；没有则 None。
    keyword ∈ {var, let, const, window}，用来判断运行时能否拿到。
    """
    for name in ARRAY_NAMES:
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
                obj = js_literal_to_obj(collapse_join(src[i:end]))
            except Exception:
                continue
            if isinstance(obj, list) and len(obj) >= 2:
                kw = m.group(1) or ("window" if m.group(0).startswith("window.") else "global")
                return {"name": name, "keyword": kw, "steps": obj, "start": m.start(), "end": end}
    return None


def _as_text(v) -> str:
    """把字段值统一成文本：列表按行拼（实测「机器学习」页 body 是字符串数组）。"""
    if isinstance(v, (list, tuple)):
        return "\n".join(_as_text(x) for x in v)
    return str(v) if v is not None else ""


TITLE_KEYS = ("t", "title", "name", "h")
BODY_KEYS = ("say", "body", "b", "d", "desc")
# 纯标识符字段，不属于正文（实测 K8s 六概念页用 k/t/m/r，k 是锚点 id）
ID_KEYS = ("term", "terms", "k", "key", "id", "cls", "class", "icon", "type", "href")


# 附加字段的中文标签：这些是「一步里的另一层信息」，不能丢也不能混进正文。
# ⚠️ 实测「机器学习」页的 demo（此刻演示里）就是被漏掉的——打印出来那一段整块没了。
EXTRA_LABELS = {
    "demo": "此刻演示里",
    "m": "以为",
    "r": "其实",
    "do": "做",
    "done": "算过",
    "plan": "计划",
}
# 纯坐标 / 数值字段，不是内容
SKIP_EXTRA = ("x", "y", "z", "c", "vis", "w", "h")


def step_fields(item):
    """归一化成 (标题, 正文, 术语行列表, 附加字段 [(标签, 文本)])。

    正文键不止 say/body：实测有 b / d / desc。另外有些步骤没有统一正文字段，
    而是 do / done / plan 几个并列字段（MLflow 系列、MLOps 导论），还有
    demo（此刻演示里，机器学习页）——这些都要单独成行保留，不能拼成一坨，
    更不能丢。
    """
    if isinstance(item, (list, tuple)):
        return (
            _as_text(item[0]) if item else "",
            _as_text(item[1]) if len(item) > 1 else "",
            [],
            [],
        )
    if isinstance(item, dict):
        title = ""
        for k in TITLE_KEYS:
            if item.get(k):
                title = _as_text(item[k])
                break
        body = ""
        for k in BODY_KEYS:
            if item.get(k):
                body = _as_text(item[k])
                break
        term = item.get("term") or item.get("terms") or []
        if isinstance(term, str):
            term = [term]
        term = [_as_text(x) for x in term if _as_text(x).strip()]
        extras = []
        for k, v in item.items():
            if k in TITLE_KEYS or k in ID_KEYS or k in BODY_KEYS or k in ("term", "terms"):
                continue
            if k in SKIP_EXTRA:
                continue
            txt = _as_text(v).strip()
            if txt:
                extras.append((EXTRA_LABELS.get(k, k), txt))
        return title, body, term, extras
    return _as_text(item), "", "", ""
