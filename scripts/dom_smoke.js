#!/usr/bin/env node
/* dom_smoke.js —— 「一页读懂」HTML 的标准冒烟（TTS 内嵌版）
 *
 * 用法：
 *   NODE_PATH=<jsdom 所在 node_modules 绝对路径> node dom_smoke.js "页面.html"
 *
 * 覆盖：AUD 12/… 段 base64 帧校验、标签页、声音四档切换、无 AudioContext 静默降级、
 *       off 档 4500ms 兜底 interval、onEnd 链式（有声音档不注册 interval）、
 *       讲解器步进、评分测验、主题切换。
 *
 * ⚠️ 本脚本是「范式断言」：只覆盖讲解器 + 语音契约的公共部分。
 *    当页特有交互（目录树点击、渲染演示、自测题具体题量）按需增删断言——
 *    增删后必须保证：任何 JS 报错都会进 errors 数组（runScripts 下 error 事件兜底）。
 *
 * 环境说明：jsdom 无 AudioContext/speechSynthesis → 静默降级路径正好在此验证；
 *            jsdom 无 matchMedia → 主题断言前需 polyfill（脚本内已处理）。
 */
const fs = require('fs');
const { JSDOM } = require(process.env.JSDOM_PATH || 'jsdom');

const htmlPath = process.argv[2];
if (!htmlPath) { console.error('usage: node dom_smoke.js <html>'); process.exit(2); }

let html = fs.readFileSync(htmlPath, 'utf-8');
const errors = [];
const assert = (c, msg) => { if (!c) { errors.push('ASSERT: ' + msg); } else console.log('ok -', msg); };

/* 1) 前置 hook：包住 setInterval 观测 4500ms 兜底（仅内存中） */
const hook = '<script>window.__iv=[];var _si=window.setInterval;window.setInterval=function(fn,ms){window.__iv.push(ms);return _si.call(window,fn,ms);};</script>';
html = html.replace('<script>', hook + '<script>');
/* 2) IIFE 收尾前暴露 AUD/QDUR（仅测试用） */
const tail = html.lastIndexOf('})();');
assert(tail > 0, 'find IIFE tail');
html = html.slice(0, tail) + 'window.__AUD=AUD;window.__QDUR=QDUR;' + html.slice(tail);

const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true });
dom.window.addEventListener('error', e => errors.push('WINDOW ERROR: ' + e.message));
const d = dom.window.document;
const $ = id => d.getElementById(id);

/* ---- A. 音频数据 ---- */
const A = dom.window.__AUD, QD = dom.window.__QDUR;
assert(A && A.f && A.m, 'AUD exposed: f/m keys');
assert(A.f.length >= 1 && A.f.length === A.m.length, 'AUD f/m same length: ' + (A && A.f.length));
assert(QD && QD.length === A.f.length && QD.every(x => typeof x === 'number' && x > 5), 'QDUR positive durations: ' + QD);
let mp3ok = 0; const mp3bad = [];
['f', 'm'].forEach(v => A[v].forEach((b64, i) => {
  try {
    const bin = Buffer.from(b64, 'base64');
    const isMp3 = (bin.length > 3 && bin[0] === 0x49 && bin[1] === 0x44 && bin[2] === 0x33)
      || (bin[0] === 0xFF && (bin[1] & 0xE0) === 0xE0);
    if (isMp3 && bin.length > 20000) mp3ok++; else mp3bad.push(v + i + ':' + bin.length + 'B');
  } catch (e) { mp3bad.push(v + i + ' decode-throw'); }
}));
assert(mp3ok === 2 * A.f.length && mp3bad.length === 0,
  `all ${2 * A.f.length} base64 -> valid mp3 frames` + (mp3bad.length ? ' bad=' + mp3bad.join(',') : ''));

/* ---- B. 标签页（按当页数量断言） ---- */
const tabs = [...d.querySelectorAll('[role=tab]')];
assert(tabs.length >= 2, 'has ' + tabs.length + ' tabs');
if (tabs[2]) { tabs[2].click(); assert(!!tabs[2].getAttribute('aria-controls'), 'tab3 switch works'); tabs[0].click(); }

/* ---- C. 讲解器 + 语音控件 ---- */
const steps = [...d.querySelectorAll('#pipe .st')];
assert(steps.length === QD.length, 'stepper steps == audio segments: ' + steps.length + ' vs ' + QD.length);
assert($('q-cnt') && $('q-cnt').textContent === '1 / ' + QD.length + ' 步', 'step counter init');
assert($('q-prev').disabled === true, 'prev disabled at step 1');

const sel = $('q-voice');
assert(sel && sel.tagName === 'SELECT', 'voice control is SELECT, got ' + (sel && sel.tagName));
assert(sel.options.length === 4 && [...sel.options].map(o => o.value).join(',') === 'f,m,tts,off', 'voice options f/m/tts/off');
assert(sel.value === 'f', 'default voice = f（女声）');
assert(sel.closest('.vsel') !== null, 'voice select wrapped in .vsel');

/* 步进 */
if (QD.length > 1) {
  $('q-next').click();
  assert($('q-cnt').textContent === '2 / ' + QD.length + ' 步', 'next -> step 2');
  assert(steps[0].className.includes('done'), 'step 1 marked done');
  for (let k = 2; k <= QD.length; k++) $('q-next').click();
  assert($('q-cnt').textContent === QD.length + ' / ' + QD.length + ' 步', 'reached last step');
  assert($('q-next').disabled === true, 'next disabled at last');
}

/* 自动播放：无 AudioContext → 静默降级，按钮文案切换，不得报错 */
$('q-auto').click();
assert($('q-auto').textContent.includes('暂停'), 'auto (女声,无Audio) toggles to pause, no crash');
assert(errors.length === 0, 'no errors during voice=f auto play (silent degrade path)');
$('q-auto').click();
assert($('q-auto').textContent.includes('自动播放'), 'auto toggles back');
$('q-auto').click(); $('q-auto').click(); /* 防止残留 interval 在收尾时打印噪音 */

/* 声音切换 m/tts/off 无报错；off 前不得注册 interval */
sel.value = 'm'; sel.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
sel.value = 'tts'; sel.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
sel.value = 'off'; sel.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
assert(errors.length === 0, 'voice switch m/tts/off no errors');
assert(dom.window.__iv.length === 0, 'no interval while voice!=off (onEnd chained)');

/* off 档 → 4500ms 兜底 interval */
$('q-auto').click();
assert(dom.window.__iv.includes(4500), 'voice=off registers 4500ms fallback interval');
$('q-auto').click();

/* ---- D. 评分测验（存在才测；题量从 QA 对象长度推断） ---- */
if ($('quizform')) {
  const qaMatch = html.match(/var QA=\{([^}]+)\}/);
  const nq = qaMatch ? qaMatch[1].split(',').length : 0;
  const form = $('quizform');
  form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  assert($('qscore').textContent === '得分：0 / ' + nq, `quiz empty -> 0/${nq}`);
}

/* ---- E. 主题切换（jsdom 无 matchMedia，polyfill） ---- */
if ($('th')) {
  if (!dom.window.matchMedia) dom.window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
  $('th').click();
  assert(['dark', 'light'].includes(d.documentElement.getAttribute('data-theme')), 'theme toggle sets data-theme');
}

console.log(errors.length ? '\nFAILURES:\n' + errors.join('\n') : '\nALL DOM SMOKE TESTS PASSED');
process.exit(errors.length ? 1 : 0);
