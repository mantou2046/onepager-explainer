"""embed_audio.py —— 把 gen_tts.py 产出的 mp3 以 base64 内嵌进「一页读懂」HTML，
并把第④屏讲解器的播放逻辑从 speechSynthesis 升级为「内嵌音频优先」。

用法：
    python embed_audio.py --html 页面.html --audio-dir ./tts_out
    # 段数按 女声/stepNN.mp3 自动推断；--min-kb 默认 8

前置契约（本 skill 的讲解器范式，页面必须按 references/design-tokens.md 的规范生成，
否则锚点 assert 会失败——这是有意的防呆，见 SKILL.md「讲解器契约」）：
  A1 CSS：存在 `.qctl .cnt{margin-left:auto;color:var(--muted);font-size:14px}`（控件条计数样式）
  A2 控件：存在 `<button type="button" id="q-voice" aria-pressed="false">🔇 语音讲解：关</button>`
  A3 提示：第④屏 hint 段落（可用 --hint-old 覆盖默认范式文案）
  A4 声明行：存在 `var qpipe=$('pipe'),qcur=0,qtimer=null,qvoice=false;`
  A5 播放逻辑：`function qspeak(html){` 起，到脚本里最后一个独立成行的 `qshow();` 止

替换内容：var AUD={f:[…],m:[…]} + QDUR（体积/6000 秒，仅作保护计时）+ .vsel 样式 +
四档声音下拉（女声/男声/浏览器朗读/关，默认女声）+ narrate/qbrowser/qctx/qcancel 降级链。

产出后必须跑 scripts/dom_smoke.js 冒烟（AUD 帧校验 + 四档切换 + 降级路径）。
⚠️ 锚点教训（10-12 实测）：结束锚点不能取「第一个 qshow();」——旧 qauto 内部也有这个调用，
必须取脚本内最后一个独立成行的 `qshow();`；替换后要复查 `function qspeak` 与
`q-voice').onclick` 残留计数为 0。
"""
import argparse
import base64
import pathlib
import re
import sys

HINT_OLD_DEFAULT = (
    "<p class=\"hint\">提示：所有互动都在浏览器本地完成，不会连接或修改你的集群。"
    "开着「语音讲解」点自动播放，就能坐着听一遍完整流程。</p>"
)
HINT_NEW = (
    "<p class=\"hint\">提示：讲解语音由 Edge-TTS 预合成真人音（女声 Xiaoxiao / 男声 Yunxi），"
    "已 base64 内嵌在本文件里，<strong>离线也能播</strong>；也可切到「浏览器朗读」或关闭。"
    "所有互动都在浏览器本地完成，不会连接或修改你的集群。选好声音后点「自动播放」，"
    "即可坐着听完整流程——每一步播完自动进入下一步。</p>"
)


def load_steps(audio_dir: pathlib.Path, folder: str) -> list[str]:
    d = audio_dir / folder
    files = sorted(d.glob("step*.mp3"))
    if not files:
        print(f"缺少音频：{d} 下没有 step*.mp3（先跑 gen_tts.py）", file=sys.stderr)
        sys.exit(2)
    return [base64.b64encode(f.read_bytes()).decode("ascii") for f in files]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="目标单文件 HTML（原地修改）")
    ap.add_argument("--audio-dir", required=True, help="gen_tts.py 的输出根目录（含 女声/ 男声/）")
    ap.add_argument("--min-kb", type=int, default=8, help="单段 mp3 体积下限（KB）")
    ap.add_argument("--hint-old", default=HINT_OLD_DEFAULT, help="第④屏旧提示文案锚点（默认=范式文案）")
    args = ap.parse_args()

    html_path = pathlib.Path(args.html)
    audio_dir = pathlib.Path(args.audio_dir)

    f_b64 = load_steps(audio_dir, "女声")
    m_b64 = load_steps(audio_dir, "男声")
    assert len(f_b64) == len(m_b64), f"女声 {len(f_b64)} 段 vs 男声 {len(m_b64)} 段，数量不一致"
    min_bytes = args.min_kb * 1024
    qdur = []
    for i in range(len(f_b64)):
        # QDUR 取两声较大值；体积/6000 ≈ 48kbps 假设下的估算秒数，仅作讲解中断保护计时
        sizes = [len(base64.b64decode(b)) for b in (f_b64[i], m_b64[i])]
        assert min(sizes) >= min_bytes, f"step{i+1:02d} 体积 {min(sizes)}B 低于下限（先过 gen_tts.py 校验）"
        qdur.append(round(max(sizes) / 6000))

    aud_js = (
        "var AUD={f:[\n" + ",\n".join(' "' + a + '"' for a in f_b64) + "\n],m:[\n"
        + ",\n".join(' "' + a + '"' for a in m_b64) + "\n]};\n"
        + "var QDUR=" + str(qdur) + ";\n"
        + "var actx=null,deccache={},qonend=function(){};\n"
    )

    raw = html_path.read_text(encoding="utf-8")
    n0 = len(raw)

    def sub(old: str, new: str, tag: str) -> None:
        nonlocal raw
        assert raw.count(old) == 1, f"锚点 {tag} 不唯一（{raw.count(old)} 处）——先核对讲解器契约"
        raw = raw.replace(old, new)

    # ---- A1 CSS：.vsel 下拉框样式 ----
    old_css = ".qctl .cnt{margin-left:auto;color:var(--muted);font-size:14px}"
    new_css = (
        ".vsel{display:flex;align-items:center;gap:6px;font-size:14px;color:var(--muted)}\n"
        ".vsel select{font:inherit;font-size:14px;border:1px solid var(--line);background:var(--bg);"
        "color:var(--ink);border-radius:8px;padding:4px 8px}\n" + old_css
    )
    sub(old_css, new_css, "A1 css")

    # ---- A2 控件：语音开关按钮 → 四档下拉 ----
    old_btn = '<button type="button" id="q-voice" aria-pressed="false">🔇 语音讲解：关</button>'
    new_btn = (
        '<label class="vsel">讲解声音 <select id="q-voice" aria-label="讲解声音">'
        '<option value="f" selected>女声</option><option value="m">男声</option>'
        '<option value="tts">浏览器朗读</option><option value="off">关</option></select></label>'
    )
    sub(old_btn, new_btn, "A2 button")

    # ---- A3 提示文案 ----
    sub(args.hint_old, HINT_NEW, "A3 hint")

    # ---- A4 声明行：注入 AUD/QDUR/运行期变量 ----
    old_decl = "var qpipe=$('pipe'),qcur=0,qtimer=null,qvoice=false;"
    new_decl = (
        aud_js
        + "var qpipe=$('pipe'),qcur=0,qtimer=null,qvoice='f',qsafety=null,qaud=null,qbusy=false;"
    )
    sub(old_decl, new_decl, "A4 decl")

    # ---- A5 播放逻辑：从 qspeak 起，到脚本内最后一个独立成行的 qshow(); 止 ----
    logic_start = raw.index("function qspeak(html){")
    finals = [m for m in re.finditer(r"^qshow\(\);[ \t]*$", raw[logic_start:], re.M)]
    assert len(finals) >= 2, (
        f"播放逻辑块应有 ≥2 个独立成行的 qshow();（qauto 内部 + 块尾 init），实际 {len(finals)} 个"
    )
    j = logic_start + finals[-1].end()
    new_logic = NEW_LOGIC
    raw = raw[:logic_start] + new_logic + raw[j:]

    # ---- 替换后复查：旧痕迹必须清零 ----
    for residue, tag in (
        ("function qspeak", "旧 qspeak 函数"),
        ("q-voice').onclick", "旧 onclick 绑定"),
        ("qvoice=!qvoice", "旧布尔 qvoice 切换"),
    ):
        assert raw.count(residue) == 0, f"残留未清：{tag}（{raw.count(residue)} 处）"

    html_path.write_text(raw, encoding="utf-8")
    print(f"OK {n0} -> {len(raw)} ({len(raw)/1024/1024:.2f} MB)，段数 {len(f_b64)}，QDUR={qdur}")
    print("下一步：node scripts/dom_smoke.js " + str(html_path))
    return 0


NEW_LOGIC = '''function qplain(html){var d=document.createElement('div');d.innerHTML=html;return d.textContent;}
function qctx(){
  if(!actx){var AC=window.AudioContext||window.webkitAudioContext;if(!AC)return null;actx=new AC();}
  if(actx.state==='suspended'&&actx.resume)actx.resume();
  return actx;
}
function qcancel(){
  qbusy=false;
  if(qsafety){clearTimeout(qsafety);qsafety=null;}
  if(qaud){try{qaud.onended=null;qaud.stop();}catch(e){}qaud=null;}
  if('speechSynthesis' in window)speechSynthesis.cancel();
}
function qbrowser(idx,onEnd){
  if(!('speechSynthesis' in window)){return;}
  try{
    var u=new SpeechSynthesisUtterance(qplain(QSTEPS[idx].say));
    u.lang='zh-CN';u.rate=0.95;qbusy=true;
    u.onend=function(){qbusy=false;if(qsafety){clearTimeout(qsafety);qsafety=null;}if(onEnd)onEnd();};
    u.onerror=u.onend;
    speechSynthesis.speak(u);
    qsafety=setTimeout(function(){if(qbusy){qcancel();if(onEnd)onEnd();}},Math.round(QDUR[idx]*1.3+6)*1000);
  }catch(e){}
}
function narrate(idx,onEnd){
  qcancel();
  if(qvoice==='off'){return;}
  var ctx=qctx();
  if((qvoice==='f'||qvoice==='m')&&ctx&&AUD[qvoice]&&AUD[qvoice][idx]){
    qbusy=true;
    var start=function(){
      if(!qbusy)return;
      try{
        var src=ctx.createBufferSource();
        src.buffer=deccache[idx];
        src.connect(ctx.destination);
        qaud=src;
        src.onended=function(){qaud=null;qbusy=false;if(qsafety){clearTimeout(qsafety);qsafety=null;}if(onEnd)onEnd();};
        src.start(0);
        qsafety=setTimeout(function(){if(qbusy){qcancel();if(onEnd)onEnd();}},(QDUR[idx]+8)*1000);
      }catch(e){qbusy=false;qbrowser(idx,onEnd);}
    };
    if(deccache[idx]){start();return;}
    var bin=atob(AUD[qvoice][idx]),n=bin.length,b=new Uint8Array(n);
    for(var i=0;i<n;i++)b[i]=bin.charCodeAt(i);
    if(ctx.decodeAudioData){
      ctx.decodeAudioData(b.buffer,function(buf){if(!qbusy)return;deccache[idx]=buf;start();},function(){if(qbusy){qbusy=false;qbrowser(idx,onEnd);}});
    }else{qbusy=false;qbrowser(idx,onEnd);}
    return;
  }
  qbrowser(idx,onEnd);
}
function qshow(withVoice){
  var x=QSTEPS[qcur];
  Array.prototype.forEach.call(qpipe.children,function(e,k){e.className='st'+(k===qcur?' on':(k<qcur?' done':''));});
  $('q-title').textContent=x.t;
  $('q-term').textContent=x.term;
  $('q-say').innerHTML=x.say;
  $('q-cnt').textContent=(qcur+1)+' / '+QSTEPS.length+' 步';
  $('q-prev').disabled=qcur===0;
  $('q-next').disabled=qcur===QSTEPS.length-1;
  if(withVoice!==false)narrate(qcur,qonend);
}
function qadvance(){
  if(qcur<QSTEPS.length-1){qcur++;qshow(true);}
  else{qstop();}
}
function qstop(){
  if(qtimer!==null){clearInterval(qtimer);qtimer=null;$('q-auto').textContent='▶ 自动播放';}
  qcancel();
}
function qauto(){
  if(qcur===QSTEPS.length-1)qcur=0;
  qonend=qadvance;
  qshow(true);
  $('q-auto').textContent='⏸ 暂停';
  if(qvoice==='off'){
    qtimer=setInterval(function(){if(qcur<QSTEPS.length-1){qcur++;qshow(true);}else{qstop();}},4500);
  }else{
    qtimer=1;
  }
}
$('q-prev').onclick=function(){qstop();qonend=function(){};if(qcur>0){qcur--;qshow(true);}};
$('q-next').onclick=function(){qstop();qonend=function(){};if(qcur<QSTEPS.length-1){qcur++;qshow(true);}};
$('q-auto').onclick=function(){
  if(qtimer!==null){qstop();qonend=function(){};return;}
  qauto();
};
$('q-voice').addEventListener('change',function(){
  qvoice=$('q-voice').value;
  qcancel();
  narrate(qcur,qonend);
});
qshow(false);
'''


if __name__ == "__main__":
    sys.exit(main())
