#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给一页纸页面补齐打印基线（按审计缺口最小注入，不动屏幕端）。

背景（2026-10-30 实测）：一页纸目录 24 页全量体检，发现三类同根因缺陷——
  ① 移动端断点污染打印：@media(max-width:XXXpx) 在打印时同样命中
     （A4 纵向版心约 695px < 所有这些阈值），命中后布局塌成单列、
     表格卡片化 → 同样几行数据吃掉近一页纸，纸全浪费在空白上。
  ② 深色覆盖特异性不够：打印段只写 :root{...}，而深色变量挂在
     html[data-theme=dark] / [data-theme=dark] 上 → 深色用户打印出
     「白纸 + 深色块」。
  ③ 打印基线缺失：无 @page、无 min-width:0、无横滚解除、无表头重复、
     折叠区默认关合（正文整段丢）、讲解器只渲染当前步（其余步整段丢）。

【设计：审计驱动 + 最小注入】
早期版本给每页叠一整块「通用标准件」，实测在已手工精调过的页面上
会把页面自己的规则覆盖掉（K8s 六概念页哨兵从 3/3 掉到 2/3，
原因：通用块的 table-layout / 白话解释列宽分配与页面精调值冲突，
长标识符 stabilizationWindowSeconds 被折断 → 抽字串不连续）。

所以改成：先跑 print_check.py 的 static_audit 拿到每页真实缺口，
再只注入「缺的那几条」。已有打印块不重建、不覆盖，页面级精调保留。

注入位置的讲究：所有页的深色变量块都排在打印块之前（实测 24/24），
所以打印覆盖只需写 :root,html[data-theme=dark] —— 后出现的同特异性
规则会赢过前面的深色块，不必把 5 种深色写法全列上。

幂等：靠标记注释判断（CSS_MARK / JS_MARK），重复跑不重复注入。

用法：
    python patch_print_baseline.py <html...>
    python patch_print_baseline.py --dir "<页面目录>"
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jslit import find_array, js_literal_to_obj, step_fields  # noqa: E402

# 门禁脚本路径：审计逻辑以它为准，避免两处判定漂移
# 门禁脚本与本文件同目录（技能自带），不写死绝对路径
GATE = Path(__file__).resolve().parent / "print_check.py"

CSS_MARK = "/* 打印基线补丁 · print-fix:2026-10-30 */"
# JS 版本号：v1 = 折叠区展开 + 讲解器副本；v2 = 追加标签页面板展开（expandHidden）
# v3 = 讲解器副本改为「已有静态内容就不覆盖」（静态副本在构建期生成，见 build_static_print）
# 版本号进标记注释 → 脚本能认出「已注入的是旧版」，整块替换而不是跳过。
JS_VER = "2026-10-30.10"
JS_MARK_PREFIX = "/* 打印状态脚本 · print-state:"
JS_MARK = JS_MARK_PREFIX + JS_VER + " */"
RE_JS_MARK = re.compile(r"/\* 打印状态脚本 · print-state:[^*]*\*/")

# 静态打印副本的标记（构建期从页面自己的步骤数组生成，不依赖运行时）
STATIC_MARK = "<!-- 打印副本 · 由页面步骤数据静态生成 · print-static:2026-10-30 -->"
RE_STATIC_BLOCK = re.compile(
    r"\n?<!-- 打印副本 · 由页面步骤数据静态生成 · print-static:2026-10-30 -->\n.*?<!-- /print-static -->\n?",
    re.S,
)

# ① 移动端断点 → 加 screen。prefers-color-scheme / print / screen 一律不动。
RE_MOBILE = re.compile(r"@media(?!\s*screen)(?!\s*print)(?!\s*\(prefers)[^{]*?\(\s*max-width\s*:\s*\d+\s*px\s*\)")

# 各条补丁规则：key = 门禁失败项名（与 print_check.static_audit 的 item name 对齐）
# 每条规则独立、幂等、自带 !important → 叠加到已有打印块后不产生副作用。
RULES: dict[str, str] = {
    # @page 纸张与页边距
    "page": "@page{size:A4;margin:13mm}",
    # 打印回浅色 · 特异性够
    # 深色变量块都排在打印块前（实测 24/24），这里同时列 html[data-theme=dark]
    # 与 html[data-theme="dark"] 两种写法，覆盖写法不一的页面。
    "dark": (
        ':root,html[data-theme=dark],html[data-theme="dark"]{'
        "--bg:#fff;--card:#fff;--paper:#fff;--ink:#111;--mut:#555;--muted:#555;--line:#ccc;"
        "--code:#f4f4f4;--codeink:#222;--acc:#8a4b08;--acc2:#8a4b08;"
        "--bad:#b91c1c;--good:#0a7f58;--warnbg:#fff7dd;--badbg:#ffecec;--okbg:#e6f7e6}"
    ),
    # 横滚容器打印解除
    # max-width 取 none 是 2026-10-31 的定版（封顶交给 table 自身的
    # max-width:100%!important）——写 100% 的话容器仍被版心宽度封住，
    # 宽表解除了 overflow 却还是被容器裁掉右列。design-tokens §7 标准件同此值。
    "scroll": (
        ".tblwrap,.scrollx,.twrap,.dgwrap,.tscroll,.term,.track,.eq,.formula,.steps,.stepper,"
        "pre{overflow:visible!important;max-height:none!important;max-width:none!important}"
    ),
    # 表格撑满版心 + 解除 min-width 撑宽（两条合并成一条，min-width:0 不能省）
    "table": (
        "table{width:100%!important;min-width:0!important;max-width:100%!important;"
        "display:table!important;table-layout:auto!important}"
    ),
    # 代码块换行
    "code": "pre,code{white-space:pre-wrap!important;word-break:break-all}",
    # 图形不超宽
    "svg": "svg,img,canvas{max-width:100%!important;height:auto!important}",
    # 语义染底不被省墨吞掉
    "color": "*{-webkit-print-color-adjust:exact;print-color-adjust:exact}",
    # 长表跨页重复表头
    "thead": "thead{display:table-header-group!important}tbody{display:table-row-group!important}",
    # 表头允许换行 + 单元格按内容自适应列宽
    # 症状：th{white-space:nowrap} 让「英文全称」这类长表头不换行、抢走大量列宽，
    # 末列（说明）被压窄 → 20 字中文折成两行 → pdftotext 按视觉行抽字时
    # 末列文字被邻列内容插断（实测「服务器推送事 | 流式输出用的单向通道… | 件常走它」）。
    # 修法：打印时 th 也允许换行 + 表格回到 auto 布局让长列自然占宽。
    "cell": "th{white-space:normal!important}th,td{overflow-wrap:anywhere}",
    # 大容器不做整块避断（只压 table / 横滚容器，不动小卡片的 avoid）
    "break": (
        "table,.tblwrap,.scrollx,.twrap,.dgwrap,.tscroll{break-inside:auto!important}"
        ".card,.demo,.kcard,.q,.stat,.motif,.takeaway,.panel,.stage,.acard,.stagebox,figure"
        "{break-inside:avoid}"
    ),
}

# 失败项 → 补丁 key 的映射（门禁 item name → RULES key；值可以是 str 或 list）
# ⚠️ "cell"（th 允许换行 + 单元格 overflow-wrap）以前只定义在 RULES 里、没接进本表，
#    等于永远选不中——恰是大表头压窄末列的正解。2026-10-31 接上：
#    凡表格类失败项一律连带补 cell，另留一个独立触发项供手工/后续门禁点名。
ITEM_TO_RULE = {
    "@page 纸张与页边距": "page",
    "打印回浅色 · 特异性够": "dark",
    "横滚容器打印解除": "scroll",
    "表格撑满版心": ["table", "cell"],
    "表格解除 min-width 撑宽": ["table", "cell"],
    "表头压窄末列": "cell",
    "代码块换行": "code",
    "图形不超宽": "svg",
    "语义染底不被省墨吞掉": "color",
    "长表跨页重复表头": "thead",
    "大容器不做整块避断": "break",
}

# 打印状态脚本：折叠区展开 + 讲解器全量副本
PRINT_STATE_JS = JS_MARK + r"""
<script>
(function(){
  var STEPS_KEYS=['QSTEPS','STEPS','steps'];

  /* ---- ① 折叠区打印前展开（details 默认关合 → 正文整段丢） ---- */
  var saved=[];
  function expandDetails(){
    saved=[];
    var ds=document.querySelectorAll('details:not([open]):not([data-print-keep-closed])');
    for(var i=0;i<ds.length;i++){
      saved.push(ds[i]);
      ds[i].setAttribute('open','');
    }
  }
  function restoreDetails(){
    for(var i=0;i<saved.length;i++){ saved[i].removeAttribute('open'); }
    saved=[];
  }

  /* ---- ①-b 标签页面板全展开（tabpanel 默认 hidden → 打印只剩第一个面板） ----
     症状：页面用 role=tabpanel 组织多个章节，非当前面板带 hidden 属性。
     打印时 hidden 的面板不渲染 → 整页 87% 内容丢失（实测 Helm 页
     源文 8507 字，PDF 只抽出 1141 字，且 PDF 末尾出现裸注释文字）。
     hidden 是「属性」，CSS 的 display 压不住它（[hidden] 属 UA 样式），
     只能由脚本在打印前摘掉属性，打印后再还原。 */
  var hiddenSaved=[];
  function expandHidden(){
    hiddenSaved=[];
    var hs=document.querySelectorAll('[hidden]');
    for(var i=0;i<hs.length;i++){
      var el=hs[i];
      /* 只处理 tabpanel 与折叠容器：脚本开关/工具条类 hidden 不该被打印 */
      var tag=(el.tagName||'').toLowerCase();
      var isPanel=(el.getAttribute('role')==='tabpanel')
        || /^(section|div|article|main)$/.test(tag);
      if(!isPanel) continue;
      hiddenSaved.push(el);
      el.removeAttribute('hidden');
    }
  }
  function restoreHidden(){
    for(var i=0;i<hiddenSaved.length;i++){ hiddenSaved[i].setAttribute('hidden',''); }
    hiddenSaved=[];
  }

  /* ---- ①-c 藏掉「当前那一步」的活容器 ----
     症状：流程讲解是「点一个按钮换一段」，DOM 里只有当前步；构建期已把全量步骤
     生成成静态副本，若活容器还显示着，打印就会把当前步重复一遍。
     各页写内容的写法五花八门（$('#x').innerHTML / sBody.querySelector('h3').textContent…），
     静态认不出容器 id，所以改成运行时按正文匹配：构建期把步骤数据以 JSON 写进
     #printStepData，这里找出「只包含某一步正文、且长度与之相当」的那个元素藏掉。 */
  var stepHidden=[];
  function normTxt(s){ return String(s==null?'':s).replace(/<[^>]*>/g,'').replace(/\s+/g,''); }
  function hideLiveStep(){
    stepHidden=[];
    var node=document.getElementById('printStepData');
    if(!node) return;
    var data;
    try{ data=JSON.parse(node.textContent||'[]'); }catch(e){ return; }
    if(!data.length) return;
    var sigs=[];
    for(var i=0;i<data.length;i++){
      sigs.push({t:normTxt(data[i].t), b:normTxt(data[i].b), m:normTxt(data[i].m)});
    }
    var els=document.querySelectorAll('div,section,article,p');
    var cand=[];
    for(var j=0;j<els.length;j++){
      var el=els[j];
      if(el.closest && el.closest('.print-only')) continue;
      if(el.closest && el.closest('.steps,.stepbtns,.stepBtns')) continue;
      var txt=normTxt(el.textContent);
      if(!txt) continue;
      for(var k=0;k<sigs.length;k++){
        var sg=sigs[k];
        var hasBody=(sg.b.length>=8 && txt.indexOf(sg.b)>=0) || (sg.m.length>=8 && txt.indexOf(sg.m)>=0);
        /* 活容器通常「标题 + 内容」同时出现；只含内容的多半是更内层的段落，
           只含标题的多半是标题元素本身 —— 都不足以判定整块。 */
        var hasTitle=(sg.t.length>=4 && txt.indexOf(sg.t)>=0);
        if(hasBody && hasTitle && txt.length<=((sg.b.length+sg.m.length+sg.t.length)*2+300)){
          cand.push(el);
          break;
        }
      }
    }
    /* 第二遍：按「精确等值」找散件。
       实测有的页面把当前步拆成 <h3>标题</h3> + <pre>命令行</pre> 两个独立元素，
       共同祖先大到没法整体隐藏（整节 4000+ 字），只能逐个精确匹配。 */
    var pieces=document.querySelectorAll('h1,h2,h3,h4,h5,pre,code,blockquote,li,p,div,span,td');
    for(var q=0;q<pieces.length;q++){
      var pe=pieces[q];
      if(pe.closest && pe.closest('.print-only')) continue;
      if(pe.closest && pe.closest('.steps,.stepbtns,.stepBtns')) continue;
      var pt=normTxt(pe.textContent);
      if(pt.length<4) continue;
      for(var r=0;r<sigs.length;r++){
        var s2=sigs[r];
        if((s2.t.length>=4 && pt===s2.t) || (s2.b.length>=8 && pt===s2.b) || (s2.m.length>=8 && pt===s2.m)){
          /* 别只藏这个内层元素：它往往在一个带边框的面板里，藏了内层会留下一个空框
             （实测机器学习页右边就是个空红框）。往上找到步骤面板整体藏。 */
          /* ⚠️ 不能把 [role="tabpanel"] 写进选择器：Helm / K8s 进阶 的整个 section
             就是 role="tabpanel"，会连副本一起藏掉（实测这两页因此掉档）。 */
          var panel=pe.closest('#stepbody,#stepDesc,#q-say,#stepVis,.stepbody');
          var victim=panel||pe;
          /* 防连坐：要藏的元素里若装着打印副本，先把副本搬到它后面（兄弟位置）
             ——实测马桶页副本被插进 .stepbody 内，stepbody 一藏副本也跟着消失。 */
          if(victim.querySelector){
            var po=victim.querySelector('.print-only');
            if(po && victim.parentNode){
              victim.parentNode.insertBefore(po, victim.nextSibling);
            }
          }
          if(stepHidden.indexOf(victim)<0){ stepHidden.push(victim); victim.classList.add('print-hide'); }
          break;
        }
      }
    }
    /* 只留最内层：外层祖先同样满足条件，藏祖先会把整节带走 */
    for(var a=0;a<cand.length;a++){
      var inner=false;
      for(var b=0;b<cand.length;b++){
        if(a!==b && cand[a]!==cand[b] && cand[a].contains(cand[b])){ inner=true; break; }
      }
      if(!inner){ stepHidden.push(cand[a]); cand[a].classList.add('print-hide'); }
    }
  }
  function restoreLiveStep(){
    for(var i=0;i<stepHidden.length;i++){ stepHidden[i].classList.remove('print-hide'); }
    stepHidden=[];
  }

  /* ---- ② 讲解器全量副本：讲解器只把当前步渲染进 DOM，其余步不在 DOM 里 →
     展开脚本无能为力。改为从同一份数据数组渲染静态全量版，
     数据同源 → 两份文案不会漂移。 ---- */
  function findSteps(){
    for(var i=0;i<STEPS_KEYS.length;i++){
      var v=window[STEPS_KEYS[i]];
      if(Array.isArray(v)&&v.length>=2){
        var first=v[0];
        if(first&&typeof first==='object'&&('say' in first||'t' in first)) return v;
      }
    }
    return null;
  }
  function esc(s){
    return String(s==null?'':s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }
  function buildPrintSteps(){
    var host=document.getElementById('printSteps');
    if(!host) return;
    /* 构建期已生成静态副本 → 不覆盖（const/let 声明的数组运行时也读不到，
       那种页面靠 Python 侧解析生成，见 patch_print_baseline.py 的 build_static_print） */
    if(host.innerHTML.replace(/\s+/g,'')) return;
    var arr=findSteps();
    if(!arr){ host.innerHTML=''; return; }
    var html='';
    for(var i=0;i<arr.length;i++){
      var s=arr[i]||{};
      var title=s.t||s.title||('第 '+(i+1)+' 步');
      var term=s.term;
      var say=s.say||s.body||'';
      html+='<div class="pstep"><h3>'+(i+1)+'. '+esc(title)+'</h3>';
      if(term){ html+='<div class="pt">'+esc(Array.isArray(term)?term.join('  |  '):term)+'</div>'; }
      if(say){ html+='<div class="ps">'+say+'</div>'; }
      html+='</div>';
    }
    host.innerHTML=html;
  }

  /* 打印副本容器：紧跟讲解器区域插入，屏幕隐藏、打印显示 */
  function ensureHost(){
    if(document.getElementById('printSteps')) return;
    var anchor=document.getElementById('q-box')||document.getElementById('q-say')
      ||document.querySelector('.stepbody')||document.querySelector('#pipe');
    var d=document.createElement('div');
    d.id='printSteps';
    d.className='print-only';
    d.setAttribute('aria-hidden','true');
    if(anchor&&anchor.parentNode){
      anchor.parentNode.insertBefore(d,anchor.nextSibling);
    }else if(document.body){
      document.body.appendChild(d);
    }
  }

  function expandAll(){ expandDetails(); expandHidden(); hideLiveStep(); buildPrintSteps(); }
  function restoreAll(){ restoreDetails(); restoreHidden(); restoreLiveStep(); }

  ensureHost();
  buildPrintSteps();
  addEventListener('beforeprint',expandAll);
  addEventListener('afterprint',restoreAll);
})();
</script>
"""

# 打印副本容器的兜底 HTML（脚本注入失败时的静态占位，不影响 JS 注入）
PRINT_STEPS_DIV = (
    '<!-- 打印副本：讲解器全量步骤（屏幕隐藏、打印显示）。内容由 print-state 脚本从同一份数据渲染 -->\n'
    '<div class="print-only" id="printSteps"></div>'
)

# 打印副本的显隐：屏幕隐藏 + 打印显示，两向都要写。
# ⚠️ 只写打印端 display:block 是回归 bug（实测踩过）：.print-only 在屏幕上
# 没有 display:none，脚本 ensureHost() 一建容器、buildPrintSteps() 一填内容，
# 屏幕端就多出一整块重复的讲解副本。
PRINT_ONLY_MARK = "/* 打印副本显隐 · print-only:2026-10-30 */"
PRINT_ONLY_CSS = (
    PRINT_ONLY_MARK
    + "\n.print-only{display:none!important}\n"
    + "@media print{.print-only{display:block!important}.print-hide{display:none!important}}\n"
)
# 旧版注入的「只有打印端」规则（缺屏幕端隐藏），需清理后换成双向版
RE_LEGACY_PRINT_ONLY = re.compile(
    r"\n?/\* 打印基线补丁 · print-fix:2026-10-30 \*/\n@media print\{\.print-only\{display:block!important\}\}\n"
)


def load_gate():
    """动态加载门禁脚本，审计判定以它为准。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("print_check_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def audit(src: str, gate) -> tuple[list[str], list[str]]:
    """返回 (失败项名列表, 警告项名列表)。"""
    stat = gate.static_audit(src)
    fails = [s["name"] for s in stat if not s["ok"] and not s.get("warn")]
    warns = [s["name"] for s in stat if not s["ok"] and s.get("warn")]
    return fails, warns


def build_patch_css(fails: list[str]) -> str:
    """按缺口挑规则拼 CSS 补丁。"""
    keys: list[str] = []
    for name in fails:
        k = ITEM_TO_RULE.get(name)
        if not k:
            continue
        # 映射值可以是单个 key，也可以是一组（如表格类 → ["table", "cell"]）
        for one in ([k] if isinstance(k, str) else k):
            if one not in keys:
                keys.append(one)

    # 「@media print 存在」失败 = 整页没有打印块 → 需要完整基线，不是逐条补
    if "@media print 存在" in fails:
        keys = ["page", "dark", "scroll", "table", "cell", "code", "svg", "color", "thead", "break"]

    if not keys:
        return ""
    body = "\n  ".join(RULES[k] for k in keys)
    return CSS_MARK + "\n@media print{\n  " + body + "\n}\n"


def has_hidden_panels(src: str) -> bool:
    """页里是否有带 hidden 属性的面板容器（tabpanel 等）。

    只认 hidden 属性本身，不认 aria-hidden（后者是给读屏器的语义标注，
    元素本身照常渲染，不该被打印脚本动）。
    """
    body = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", src, flags=re.S | re.I)
    for m in re.finditer(r"<([a-zA-Z0-9]+)([^>]*)>", body):
        tag, attrs = m.group(1).lower(), m.group(2)
        if not re.search(r"(^|\s)hidden(\s|=|$|>)", attrs):
            continue
        # 只认面板容器：button / input 这类交互控件上的 hidden 不展开
        if tag in ("button", "input", "select", "textarea", "option"):
            continue
        if tag in ("section", "div", "article", "main", "aside", "nav"):
            return True
    return False


def build_patch_js(src: str) -> str:
    """按页面的结构特征判断是否需要打印状态脚本。

    ⚠️ 判据必须看「结构」，不能看门禁的 has_expand（它认 print-only 字符串，
    而我们自己注入的 .print-only CSS 正好含这个词 → 会自证「不需要」，把旧脚本
    删掉却不补新的，实测踩过）。三类需求：
      ① <details> 折叠区 → 打印前展开
      ② 带 hidden 的面板容器 → 打印前摘属性（tabpanel 只出第一个面板）
      ③ QSTEPS/STEPS 讲解器数据 → 渲染全量副本（只把当前步放进了 DOM）
    """
    body = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", src, flags=re.S | re.I)
    need = []

    has_details = False
    for m in re.finditer(r"<details\b([^>]*)>", body, re.I):
        if "data-print-keep-closed" not in m.group(1):
            has_details = True
            break
    if has_details:
        need.append("details")

    if has_hidden_panels(src):
        need.append("tabpanel")

    has_steps = re.search(r"\b(QSTEPS|STEPS)\s*=\s*\[", src) is not None
    has_static_copy = re.search(r'<(div|section)\b[^>]*(id="printSteps"|class="[^"]*print-only)', body, re.I) is not None
    if has_steps and not has_static_copy:
        need.append("steps")
    # 构建期生成了步骤副本 → 必须注入脚本，打印时靠它把「当前那一步」的活容器藏掉
    if 'id="printStepData"' in src:
        need.append("livehide")

    if not need:
        return ""
    # 页面自带 beforeprint 处理（如主诉页手工精调过的打印块）→ 不重复注入，
    # 除非它缺 tabpanel 展开（自带脚本不会处理 hidden 属性）。
    if "beforeprint" in src and "tabpanel" not in need and "livehide" not in need:
        return ""
    return PRINT_STATE_JS


def strip_old_js(src: str) -> str:
    """移除任一版本的打印状态脚本块（标记注释 → 其后的 </script>）。"""
    m = RE_JS_MARK.search(src)
    if not m:
        return src
    i = m.start()
    j = src.lower().find("</script>", m.end())
    if j == -1:
        return src[:i]
    return src[:i] + src[j + len("</script>") :]


RE_INLINE = re.compile(r"</?(?:b|strong|i|em|code|br|span|a|sup|sub)\b[^>]*>", re.I)


def _esc(s: str) -> str:
    """转义尖括号，但保留作者写的内联标签（正文里有 <b>测试损失</b> 这类）。"""
    s = str(s)
    out, last = [], 0
    for m in RE_INLINE.finditer(s):
        out.append(html_mod.escape(s[last : m.start()], quote=False))
        out.append(m.group(0))
        last = m.end()
    out.append(html_mod.escape(s[last:], quote=False))
    return "".join(out)


def extract_nodes(src: str) -> list[tuple[str, str]]:
    """读「点一个节点显示一段说明」的数据：按钮标签 + ND 字典正文。

    这类页面的结构是 <button class="node" data-k="web">标签</button> 配
    ND={web:"...", ...}，点哪个就把哪段写进 #nodeDesc —— 打印只剩默认那一个。
    """
    m = re.search(r"\bND\s*=\s*\{", src)
    if not m:
        return []
    i = m.end() - 1
    depth = 0
    end = None
    for k in range(i, len(src)):
        ch = src[k]
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                end = k + 1
                break
    if end is None:
        return []
    try:
        nd = js_literal_to_obj(src[i:end])
    except Exception:
        return []
    if not isinstance(nd, dict):
        return []

    labels: dict[str, str] = {}
    for bm in re.finditer(r"<button\b[^>]*data-k=\"([^\"]+)\"[^>]*>(.*?)</button>", src, re.S | re.I):
        labels[bm.group(1)] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", bm.group(2))).strip()
    return [(labels.get(k, k), str(v)) for k, v in nd.items()]



def _has_filled_copy(src: str, elem_id: str) -> bool:
    """页面里是否已有**填了内容**的打印副本容器。

    ⚠️ 只判 id 存在不够：实测 K8s 六概念页写着 <div id="printSteps"></div>，
    空壳一个、内容靠运行时填（且填不全）→ 必须当成没有，由构建期补。
    """
    m = re.search(r'<div\b[^>]*\bid="' + re.escape(elem_id) + r'"[^>]*>(.*?)</div>', src, re.S | re.I)
    return bool(m and m.group(1).strip())

def _element_end(src: str, start: int, tag: str) -> int:
    """从某个开标签的起点，找到同名标签的配对结束位置（含闭合标签）。"""
    depth = 0
    for m in re.finditer(r"<(/?)" + tag + r"\b[^>]*?(/?)>", src[start:], re.I):
        close, selfclose = m.group(1) == "/", m.group(2) == "/"
        if selfclose:
            continue
        depth += -1 if close else 1
        if depth == 0:
            return start + m.end()
    return -1


def _find_steps_container(src: str):
    """找步骤区的容器，返回 (起点, 标签名)。

    ⚠️ 优先取最外层 .stepper：有的页打印 CSS 直接 `.stepper{display:none!important}`
    （K8s 六概念页就是），副本若插在里面的 .stepbtns 之后会被一起藏掉 ——
    实测该页 6 步内容在纸面上一个字都没有。
    """
    for pat in (
        r'id="pipe\b"',                       # 讲解器契约的步骤胶囊容器（design-tokens §5）
        r'class="[^"]*\bplayer\b[^"]*"',      # 左按钮右面板的双栏外壳（机器学习页）
        r'class="[^"]*\bstepper\b[^"]*"',
        r'class="[^"]*\b(?:steps|stepbtns|stepBtns)\b[^"]*"',
    ):
        # ⚠️ 步骤列表可能是 <ol>/<ul>，不只是 div —— 实测机器学习页是
        #    <ol class="steps">，只扫 div/section/nav 会漏，副本被扔到文档末尾。
        for m in re.finditer(r"<(div|section|nav|ol|ul)\b[^>]*>", src, re.I):
            if re.search(pat, m.group(0), re.I):
                return m.start(), m.group(1)
    return None, None


def build_static_print(src: str) -> tuple[list[tuple[tuple[str, str], str]], list[str], list[str]]:
    """构建期生成打印副本：步骤全量 + 节点说明全量。

    为什么必须在构建期做：步骤/说明数据写在 JS 字面量里，而 `const`/`let`
    声明**不进 window**，运行时脚本读不到 → 打印只剩当前选中的那一条。
    实测 4 个页面（Langfuse / vLLM / K8s 生产化四件套 / FastAPI 流式响应）
    用 `const ST=[...]`，7 步里只印出第 1 步。

    返回 ([(锚点容器 id, 副本 html)], 要隐藏的容器 id 列表, 说明列表)。
    副本插在锚点容器**前面**（锚点在打印时被藏掉，副本正好占它的位置）——
    不能统一放文末，否则「流程讲解」在正文中部、副本跑到最后一页去。
    """
    arr = find_array(src)
    # ⚠️ 不能只处理 const/let：实测 `var QSTEPS` 也常写在页面自己的 IIFE 里，
    #    同样不在 window 上 → 运行时副本是空的。只要解析得出就静态生成。
    if not arr:
        return [], [], []

    blocks: list[tuple[tuple[str, str], str]] = []
    hide: list[str] = []
    desc: list[str] = []

    steps = arr["steps"]
    # 页面自带手写的全量副本（如 K8s 六概念页）→ 不再生成，否则重复一份
    if len(steps) >= 2 and not _has_filled_copy(src, "printSteps"):
        rows = []
        payload = []
        for idx, item in enumerate(steps, 1):
            title, body, term, extras = step_fields(item)
            payload.append(
                {
                    "t": title,
                    "b": body,
                    "m": "\n".join(term),
                    "e": "\n".join(t for _k, t in extras),
                }
            )
            row = ['<div class="pstep">']
            row.append(f"<h3>{idx}. {_esc(title)}</h3>")
            if term:
                # ⚠️ 不要用 <pre>：门禁把「页面有 pre」当作「必须写 white-space:pre-wrap」的触发条件，
                #    静态副本自带一个 <pre> 会让本来没代码块的页面被误判（实测 3 页因此掉档）。
                #    样式表里 .pt 已经有 white-space:pre-wrap，用 div 效果一样。
                row.append('<div class="pt">' + _esc("\n".join(term)) + "</div>")
            if body:
                row.append(f'<div class="ps">{_esc(body)}</div>')
            for label, txt in extras:
                # 正文自带「以为：」「其实：」这类前缀时别再叠一遍标签
                for sep in ("：", ":"):
                    if txt.startswith(label + sep):
                        txt = txt[len(label) + 1 :]
                        break
                row.append(f'<div class="pnote"><b>{_esc(label)}</b>：{_esc(txt)}</div>')
            row.append("</div>")
            rows.append("".join(row))
        # 步骤数据同时以 JSON 形式留给运行时：打印时用来认出「当前步容器」并藏掉，
        # 避免与全量副本重复（各页容器写法不一，静态认不出来，只能运行时按正文匹配）。
        data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
        # 锚点优先级：步骤按钮容器之后 > 已知的「当前步」容器之前 > 文末兜底。
        # 放在按钮容器之后读起来最顺（先看步骤清单，再看全量正文）。
        anchor: tuple[str, str] = ("after_steps_btns", "")
        if _find_steps_container(src)[0] is None:
            anchor = ("before_id", "stepDesc") if 'id="stepDesc"' in src else ("end", "")
            if anchor[0] == "end":
                for cand in ("q-say", "stepBody", "stepVis", "stepText", "stepDesc"):
                    if f'id="{cand}"' in src:
                        anchor = ("before_id", cand)
                        break
        blocks.append(
            (
                anchor,
                '<script type="application/json" id="printStepData">'
                + data_json
                + "</script>"
                + '<div class="print-only" id="'
                + ("printStepsStatic" if 'id="printSteps"' in src else "printSteps")
                + '">'
                + f'<div class="phead">流程讲解 · 全 {len(steps)} 步（打印版；屏幕上点上面的按钮逐步看）</div>'
                + "".join(rows)
                + "</div>",
            )
        )
        hide.append("stepDesc")
        desc.append(f"步骤全量 {len(steps)} 步")

    nodes = extract_nodes(src)
    if len(nodes) >= 2 and 'id="nodeDesc"' in src and not _has_filled_copy(src, "printNodes"):
        rows = []
        for label, text in nodes:
            # ND 的正文很多本来就以「节点名：」开头，别再加一遍标签。
            # ⚠️ 不能只做 startswith 精确比对：按钮标签常带端口（「MinIO :9090」），
            #    正文却写作「MinIO：…」→ 要把冒号前那段和标签做「互相包含」判断。
            t = text
            for sep in ("：", ":"):
                head, got, rest = t.partition(sep)
                if got and head and len(head) <= 30:
                    a = head.replace(" ", "").lower()
                    b = label.replace(" ", "").lower()
                    if a and b and (a in b or b in a):
                        t = rest
                        break
            rows.append(f'<div class="pnode"><b>{_esc(label)}</b>：{_esc(t)}</div>')
        blocks.append(
            (
                ("before_id", "nodeDesc"),
                '<div class="print-only" id="'
                + ("printNodesStatic" if 'id="printNodes"' in src else "printNodes")
                + '">'
                f'<div class="phead">架构节点说明 · 全 {len(nodes)} 个（打印版）</div>'
                + "".join(rows)
                + "</div>",
            )
        )
        hide.append("nodeDesc")
        desc.append(f"节点说明 {len(nodes)} 条")

    return blocks, hide, desc


STATIC_CSS_MARK = "/* 静态打印副本排版 · print-static-css:2026-10-30 */"

# 速查表分类筛选：屏幕上点「数据/模型/训练」会把别的行 display:none 掉，
# 打印时若停在某个分类，纸面上就只剩那一类（实测 6 页有这种筛选）。
FILTER_MARK = "/* 打印时展开被筛掉的行 · print-filter:2026-10-30 */"
FILTER_CSS = (
    FILTER_MARK
    + "\n@media print{[data-cat]{display:table-row!important}}\n"
)

STATIC_CSS = """/* 静态打印副本的排版：中性灰阶，不抢页面语义色 */
.print-only .phead{font-weight:700;margin:0 0 8px;font-size:.95em;opacity:.75}
.print-only .pstep{margin:0 0 12px;padding-left:10px;border-left:3px solid #c8c8c8;break-inside:avoid}
.print-only .pstep h3{font-size:1em;margin:0 0 4px}
.print-only .pt{font-family:ui-monospace,Consolas,monospace;font-size:.85em;background:#f4f4f4;color:#222;
  padding:6px 8px;border-radius:4px;margin:0 0 5px;white-space:pre-wrap;word-break:break-all}
.print-only .ps{margin:0;font-size:.95em;line-height:1.6}
.print-only .pnote{margin:6px 0 0;padding:5px 8px;font-size:.9em;line-height:1.6;
  border-left:2px solid #d8d8d8;background:#fafafa;color:#333}
.print-only .pnode{margin:0 0 7px;font-size:.95em;line-height:1.6;break-inside:avoid}
"""


def has_screen_print_only_hide(src: str) -> bool:
    """屏幕端（@media print 之外）是否已有 .print-only 的隐藏规则。

    必须先把 @media print 块剥掉再判 —— 否则打印端的 display:block 会被误认。
    """
    css = "\n".join(m.group(1) for m in re.finditer(r"<style\b[^>]*>(.*?)</style>", src, re.S | re.I))
    out: list[str] = []
    i = 0
    while True:
        m = re.search(r"@media[^{]*\bprint\b[^{]*\{", css[i:])
        if not m:
            out.append(css[i:])
            break
        out.append(css[i : i + m.start()])
        # 花括号配对跳过整个 @media print 块
        depth = 0
        j = i + m.end() - 1
        while j < len(css):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        i = j
    screen = "".join(out)
    for m in re.finditer(r"([^{}]*\.print-only[^{}]*)\{([^}]*)\}", screen):
        if re.search(r"display\s*:\s*none", m.group(2), re.I):
            return True
    return False


def patch(src: str, gate) -> tuple[str, list[str]]:
    notes: list[str] = []

    # ① 移动端断点限定 screen（这是根因修复，不依赖审计项）
    def _fix(m: re.Match) -> str:
        return "@media screen" + m.group(0)[len("@media"):]

    new_src, n = RE_MOBILE.subn(_fix, src)
    if n:
        notes.append(f"移动端断点限定 screen ×{n}")

    # ② 按审计缺口注入 CSS 补丁
    fails, _warns = audit(new_src, gate)
    if CSS_MARK in new_src:
        notes.append("CSS 补丁已存在，跳过")
    else:
        css_patch = build_patch_css(fails)
        if not css_patch:
            notes.append("审计无缺口，不注 CSS")
        else:
            idx = new_src.rfind("</style>")
            if idx == -1:
                notes.append("未找到 </style>，跳过 CSS 注入")
            else:
                new_src = new_src[:idx] + css_patch + "\n" + new_src[idx:]
                notes.append(f"注入 CSS 补丁（{len(fails)} 项缺口）")

    # ②b 静态打印副本：把「点一下换一段」的步骤/节点说明全量生成出来
    # 必须在 ④ 之前，④ 靠 "printSteps" 判断要不要补 .print-only 显隐。
    # 幂等：先摘掉上一次生成的副本（步骤/节点各一块，需循环摘）
    while RE_STATIC_BLOCK.search(new_src):
        new_src = RE_STATIC_BLOCK.sub("\n", new_src, count=1)
    blocks, hide_ids, static_desc = build_static_print(new_src)
    if blocks:
        for (kind, key), block in blocks:
            wrapped = STATIC_MARK + "\n" + block + "\n<!-- /print-static -->\n"
            pos = None
            if kind == "before_id":
                m = re.search(r'<[a-zA-Z][\w-]*\b[^>]*\bid="' + re.escape(key) + r'"[^>]*>', new_src)
                if m:
                    pos = m.start()
            elif kind == "after_steps_btns":
                start, tag = _find_steps_container(new_src)
                if start is not None:
                    end = _element_end(new_src, start, tag)
                    if end > 0:
                        pos = end
            if pos is None:  # 兜底：找不到锚点就放文末
                idx = new_src.lower().rfind("</body>")
                pos = idx if idx != -1 else len(new_src)
            new_src = new_src[:pos] + wrapped + new_src[pos:]
        notes.append("生成静态打印副本（" + "、".join(static_desc) + "）")
        # 当前选中那条的容器在打印时藏掉，避免与全量副本重复
        if hide_ids and STATIC_CSS_MARK not in new_src:
            css = (
                STATIC_CSS_MARK
                + "\n"
                + STATIC_CSS
                + "@media print{"
                + ",".join("#" + i for i in hide_ids)
                + "{display:none!important}}\n"
            )
            idx2 = new_src.rfind("</style>")
            if idx2 != -1:
                new_src = new_src[:idx2] + css + new_src[idx2:]

    # ③ 注入打印状态脚本（折叠区展开 / 标签页面板展开 / 讲解器全量副本）
    # 旧版脚本（无 expandHidden）必须整块换掉，不能跳过——否则 tabpanel 页照旧丢内容。
    cur_mark = RE_JS_MARK.search(new_src)
    if cur_mark and cur_mark.group(0) == JS_MARK:
        notes.append(f"JS 脚本已是 v{JS_VER}，跳过")
    else:
        if cur_mark:
            new_src = strip_old_js(new_src)
            notes.append("移除旧版 JS 脚本")
        js = build_patch_js(new_src)
        if not js:
            notes.append("无需 JS 补丁")
        else:
            idx = new_src.lower().rfind("</body>")
            if idx == -1:
                new_src = new_src + "\n" + js
                notes.append("注入 JS 脚本（追加到末尾）")
            else:
                new_src = new_src[:idx] + js + "\n" + new_src[idx:]
            notes.append(f"注入 JS 脚本 v{JS_VER}")

    # ④ 打印副本显隐：屏幕隐藏 + 打印显示，两向都要
    # 旧版只写了打印端 → 屏幕上 #printSteps 直接露出来（重复一份讲解副本）。
    new_src, nl = RE_LEGACY_PRINT_ONLY.subn("\n", new_src)
    if nl:
        notes.append(f"清理旧版单端 print-only 规则 ×{nl}")
    # 旧版 print-only 块缺 .print-hide（隐藏「当前步」用）→ 整块换成新版
    if PRINT_ONLY_MARK in new_src and ".print-hide" not in new_src:
        new_src = new_src.replace(
            PRINT_ONLY_MARK + "\n.print-only{display:none!important}\n"
            "@media print{.print-only{display:block!important}}\n",
            PRINT_ONLY_CSS,
        )
        if ".print-hide" not in new_src:  # 换失败就删了重加
            i0 = new_src.find(PRINT_ONLY_MARK)
            if i0 != -1:
                j0 = new_src.find("\n", new_src.find("@media print", i0))
                new_src = new_src[:i0] + new_src[j0 + 1 :]
        notes.append("升级 print-only 块（补 .print-hide）")
    if PRINT_ONLY_MARK not in new_src:
        need_copy = ("printSteps" in new_src) or re.search(
            r'<(div|section)\b[^>]*class="[^"]*print-only', new_src, re.I
        )
        if need_copy and not has_screen_print_only_hide(new_src):
            idx2 = new_src.rfind("</style>")
            if idx2 != -1:
                new_src = new_src[:idx2] + PRINT_ONLY_CSS + new_src[idx2:]
                notes.append("补 print-only 双向显隐")

    # ⑤ 分类筛选：打印时把被筛掉的行全部展开
    if 'data-cat="' in new_src and FILTER_MARK not in new_src:
        idx3 = new_src.rfind("</style>")
        if idx3 != -1:
            new_src = new_src[:idx3] + FILTER_CSS + new_src[idx3:]
            notes.append("补筛选行打印展开")

    return new_src, notes


def main() -> int:
    ap = argparse.ArgumentParser(description="给一页纸页面补齐打印基线（审计驱动）")
    ap.add_argument("html", nargs="*", help="待处理 HTML")
    ap.add_argument("--dir", help="目录（批量处理其中所有 *.html）")
    ap.add_argument("--dry-run", action="store_true", help="只报告要做什么，不写盘")
    args = ap.parse_args()

    targets = [Path(p) for p in args.html]
    if args.dir:
        targets += sorted(Path(args.dir).glob("*.html"))
    if not targets:
        print("用法：patch_print_baseline.py <html...> | --dir <目录>", file=sys.stderr)
        return 2

    gate = load_gate()

    for p in targets:
        if not p.exists():
            print(f"[跳过] 不存在：{p}", file=sys.stderr)
            continue
        src = p.read_text(encoding="utf-8")
        out, notes = patch(src, gate)
        if out == src:
            print(f"[跳过] {p.name}（无变化）")
            continue
        if not args.dry_run:
            # 写盘前留一份原稿：<文件名>.bak，只保留首份——重跑不覆盖最初的样子，
            # 这样"补丁打坏了"永远能退回补丁前的状态（原来直接 write_text 无回滚）。
            bak = p.with_name(p.name + ".bak")
            if not bak.exists():
                shutil.copy2(p, bak)
            p.write_text(out, encoding="utf-8")
        print(f"[{'计划' if args.dry_run else '已改'}] {p.name} → {'；'.join(notes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
