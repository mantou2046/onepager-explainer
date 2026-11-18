#!/usr/bin/env node
/**
 * text_check.mjs —— 一页纸「中文排版与断行」实测门禁
 *
 * 不是读代码判对错，而是真开浏览器量：正文行长是否超标、标题末行有没有孤字、
 * 混排数字有没有被拆开、320px 还撑不撑得住、用户改文字间距后会不会塌。
 * 这些问题全部静默——页面不报错、dom_smoke 全绿、截图看着也还行，只有逐行读才看得见。
 *
 * 用法（在技能根目录下跑，或在任意目录用绝对路径调）：
 *     node scripts/text_check.mjs 页面.html
 *     node scripts/text_check.mjs 页面.html --widths 1440,768,390,320 --json
 *     node scripts/text_check.mjs 页面.html --keep        # 保留截图
 *     node scripts/text_check.mjs 页面.html --static-only # 只跑静态审计，不开浏览器
 *
 * 退出码：0 全过 / 1 有 FAIL / 2 环境缺失（找不到 Chrome）或文件不存在
 *
 * 依赖：本机 Chrome（或 Edge）。零 npm 依赖——直连 Chrome DevTools Protocol，
 *       用 Node 内置 WebSocket（需 Node ≥ 22；Node 21 起为全局对象）。
 *
 * 边界（必须一起报，不许只看退出码）：
 *   - 孤字只判「末行 ≤1 字」为失败、≤2 字为待人工；语义是否自然仍需人读行片段
 *   - 200% 文字放大在无头环境无法真实模拟 → 恒为 not_run，不得当通过
 *   - 行长按「容器宽 ÷ 字号」估算汉字数，混排英文会偏高，报告里附实际行片段供复核
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, mkdirSync, existsSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, basename } from 'node:path';
import { pathToFileURL } from 'node:url';

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
].filter(Boolean);

const DEFAULT_WIDTHS = '1440,1024,768,390,320';
const DESKTOP_MIN = 768;   // 该宽度及以上才判行长上限
const LINE_MAX = 40;       // 桌面多行正文行长上限（汉字）
const LINE_SINGLE = 60;    // 桌面单行长句上限（汉字）
const TARGET_MIN = 24;     // WCAG 2.5.8 AA 最小可点目标
const CDP_PORT = 9335;

// ---------------------------------------------------------------- 参数
function parseArgs(argv) {
  const args = { html: null, widths: DEFAULT_WIDTHS, json: false, keep: false, staticOnly: false, noSpacing: false, out: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--json') args.json = true;
    else if (a === '--keep') args.keep = true;
    else if (a === '--static-only') args.staticOnly = true;
    else if (a === '--no-spacing') args.noSpacing = true;
    else if (a === '--widths') args.widths = argv[++i];
    else if (a === '--out') args.out = argv[++i];
    else if (a === '--help' || a === '-h') { printHelp(); process.exit(0); }
    else if (!a.startsWith('--')) args.html = a;
  }
  return args;
}

function printHelp() {
  console.log(`text_check.mjs —— 一页纸中文排版与断行实测

用法：
  node scripts/text_check.mjs 页面.html [选项]

选项：
  --widths a,b,c    要测的视口宽度（默认 ${DEFAULT_WIDTHS}）
  --out DIR         截图与 JSON 输出目录（默认临时目录）
  --keep            保留截图与报告
  --static-only     只跑静态审计，不开浏览器
  --no-spacing      跳过「用户文字间距覆盖」一项
  --json            输出 JSON 报告
  -h, --help        显示本帮助

退出码：0 全过 / 1 有 FAIL / 2 环境缺失或文件不存在`);
}

// ---------------------------------------------------------------- 静态审计
function staticAudit(src) {
  const rawCss = [...src.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)].map((m) => m[1]).join('\n');
  // 抹掉 @media 前导，否则 @media (max-width:720px) 会被当成 max-width 声明
  const css = rawCss.replace(/@media[^{]*\{/g, '{');
  const body = src.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, '');
  const res = [];
  // ok=false + warn=true → 计入「待人工」，不算失败、不影响退出码（同 print_check.py 约定）
  const item = (name, ok, hint) => res.push({ name, ok: !!ok, hint: ok ? '' : hint });
  const info = (name, ok, hint) => res.push({ name, ok: !!ok, hint: ok ? '' : hint, ...(ok ? {} : { warn: true }) });

  // CSS 变量表，供 max-width:var(--x) 解析
  const vars = {};
  for (const m of rawCss.matchAll(/--([\w-]+)\s*:\s*([\d.]+)\s*(px|ch|em|rem)\b/gi)) {
    vars[m[1]] = { v: parseFloat(m[2]), u: m[3].toLowerCase() };
  }
  const resolveDim = (raw) => {
    const t = raw.trim();
    const vm = /^var\(\s*--([\w-]+)\s*\)$/.exec(t);
    if (vm) return vars[vm[1]] || null;
    const nm = /^([\d.]+)\s*(px|ch|em|rem)$/i.exec(t);
    return nm ? { v: parseFloat(nm[1]), u: nm[2].toLowerCase() } : null;
  };
  const toPx = (d) => (d.u === 'px' ? d.v : d.u === 'ch' ? d.v * 8 : d.v * 16);

  // ① 正文行宽约束
  const widths = [];
  for (const m of css.matchAll(/max-width\s*:\s*([^;}]+)/gi)) {
    if (/none/i.test(m[1])) continue;
    const d = resolveDim(m[1]);
    if (d) widths.push(toPx(d));
  }
  if (!widths.length) {
    item('正文行宽约束', false, '完全没有 max-width → 段落跑满视口，桌面行长必然超标（§2.3）');
  } else {
    const narrow = Math.min(...widths);
    info('正文行宽约束', narrow <= 640,
      `最窄行宽上限 ${Math.round(narrow)}px ≈ ${Math.round(narrow / 16)} 汉字（§2.3 定版：多行正文 ≤40 汉字 = 640px）；超了则正文未被限宽 —— 限宽可落在容器上（.prose/.narrow/.narrow-card）或段落上（p,li{max-width:40em}），后者在正文卡片本身较窄时几乎无副作用，但宽卡片里会留空右边，需用容器级方案`);
  }

  // ② 混排数字保护
  const hasNowrap = /white-space\s*:\s*nowrap/i.test(css) || /&nbsp;/.test(src) || /class="[^"]*\bnw\b/.test(src);
  const hasNumber = /\d[\d,.]*\s*(KB|MB|GB|%|元|万|亿|天|年|个月|px|mm)/.test(body);
  item('混排数字保护', hasNowrap || !hasNumber, '页面有数字+单位但 CSS 里没有 white-space:nowrap / .nw / &nbsp; → ¥1,280、≤50KB 这类片段会被拆到两行（§2）');

  // ③ 正文行高：任一 ≥1.5 的声明即算（取全部匹配，不能只看第一个）
  const lhVals = [...css.matchAll(/line-height\s*:\s*([\d.]+)\s*(?![%])(?!px|rem|em)/gi)].map((m) => parseFloat(m[1]));
  const lhPx = /line-height\s*:\s*[\d.]+px/i.test(css);
  item('正文行高 ≥1.5', lhPx || lhVals.some((v) => v >= 1.5), '所有 line-height 都 <1.5 → 中文长文行距过密（用户文字间距覆盖也更容易塌）');

  // ④ 字号体系（信息项）
  const pxCount = (css.match(/font-size\s*:\s*[\d.]+px/gi) || []).length;
  const relCount = (css.match(/font-size\s*:\s*[\d.]+(?:rem|em)/gi) || []).length;
  info('字号体系', relCount > 0 || pxCount === 0,
    `${pxCount} 处 px / ${relCount} 处 rem-em → 浏览器「默认字号」设置对本页无效，只有 Ctrl+= 缩放有效；200% 放大项只能人验`);

  // ⑤ 标题均衡断行（信息项）
  const hasBalance = /text-wrap\s*:\s*balance/i.test(css);
  const longHead = /<h[12][^>]*>[^<]{14,}/i.test(body);
  info('标题 text-wrap:balance', hasBalance || !longHead,
    '有 ≥14 字的长标题但没写 text-wrap:balance → 末行容易只剩一两个字；注意它只改断点、不保证中文语义（§2.4 第 4 步）');

  // ⑥ 纵向比较数字等宽（信息项）
  const hasTable = /<table\b/i.test(body);
  const hasTnum = /font-variant-numeric\s*:\s*tabular-nums/i.test(css);
  info('数字等宽对齐', hasTnum || !hasTable,
    '有表格但没写 font-variant-numeric:tabular-nums → 数字列纵向不对齐（§2）');

  return res;
}

// ---------------------------------------------------------------- 页内测量
const PROBE = String.raw`
(() => {
  const out = {};
  const de = document.documentElement;
  out.viewport = de.clientWidth;
  out.scrollWidth = de.scrollWidth;
  out.hOverflow = de.scrollWidth > de.clientWidth + 1;
  out.overflowBy = de.scrollWidth - de.clientWidth;

  const textNodes = (el) => {
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const a = []; let n; while ((n = w.nextNode())) a.push(n); return a;
  };
  const lineSplit = (el) => {
    const nodes = textNodes(el);
    if (!nodes.length) return [];
    const total = nodes.map((n) => n.textContent).join('');
    const range = document.createRange();
    const lines = []; let s = 0, prevTop = null;
    for (let i = 0; i < total.length; i++) {
      let acc = 0, ni = -1, local = 0;
      for (let k = 0; k < nodes.length; k++) {
        const L = nodes[k].textContent.length;
        if (i < acc + L) { ni = k; local = i - acc; break; }
        acc += L;
      }
      if (ni < 0) continue;
      range.setStart(nodes[ni], local); range.setEnd(nodes[ni], local + 1);
      const r = range.getClientRects()[0];
      if (!r) continue;
      if (prevTop === null) prevTop = r.top;
      else if (Math.abs(r.top - prevTop) > 2) { lines.push(total.slice(s, i)); s = i; prevTop = r.top; }
    }
    lines.push(total.slice(s));
    return lines.map((x) => x.trim()).filter(Boolean);
  };

  // 纯文字段落行长（汉字数 = 内容宽 ÷ 字号）
  const isProse = (el) => {
    const t = el.innerText ? el.innerText.trim() : '';
    if (t.length < 24) return false;
    if (el.querySelector('p,div,pre,table,ul,ol,img,svg,canvas,figure')) return false;
    const cs = getComputedStyle(el);
    if (parseFloat(cs.fontSize) < 14) return false;
    if (cs.whiteSpace === 'nowrap' || cs.whiteSpace === 'pre') return false;
    return true;
  };
  const paras = [...document.querySelectorAll('p,li,.p,.lead,dd,blockquote')].filter(isProse);
  out.lineLength = paras.map((el) => {
    const cs = getComputedStyle(el);
    const fs = parseFloat(cs.fontSize);
    const w = el.clientWidth - parseFloat(cs.paddingLeft || 0) - parseFloat(cs.paddingRight || 0);
    const lines = lineSplit(el);
    const cap = Math.round(w / fs);            // 容器能排多少字（满行行长）
    let act = cap;
    if (lines.length <= 1) {                    // 单行：看实际文字多宽，不是容器多宽
      const rg = document.createRange();
      rg.selectNodeContents(el);
      act = Math.round(rg.getBoundingClientRect().width / fs);
    }
    return { chars: cap, act, lines: lines.length, w: Math.round(w), fs, sample: el.innerText.trim().slice(0, 18) };
  }).sort((a, b) => b.chars - a.chars);
  out.maxChars = out.lineLength.length ? out.lineLength[0].chars : 0;
  // 多行段落按 40 字上限（满行行长），单行长句按 60 字上限（实际文字宽）
  out.overMulti = out.lineLength.filter((x) => x.lines >= 2 && x.chars > 40);
  out.overSingle = out.lineLength.filter((x) => x.lines < 2 && x.act > 60);

  // 标题逐行片段
  out.headings = [...document.querySelectorAll('h1,h2,h3')].filter((el) => el.offsetParent !== null).slice(0, 20).map((el) => {
    const lines = lineSplit(el);
    const last = lines.length ? lines[lines.length - 1] : '';
    return { tag: el.tagName, fs: parseFloat(getComputedStyle(el).fontSize), lines, lastLen: [...last].length };
  });

  // 混排数字串被拆
  const NUMRE = /\d[\d,.]*\s*(KB|MB|GB|TB|ms|px|mm|cm|%|元|万|亿|天|年|个月|小时|分钟|次|人|台|核|G|M|K)(?![\w])/g;
  const broken = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node, guard = 0;
  while ((node = walker.nextNode()) && guard++ < 6000) {
    const t = node.textContent;
    if (!/\d/.test(t)) continue;
    NUMRE.lastIndex = 0;
    let m;
    while ((m = NUMRE.exec(t))) {
      const r = document.createRange();
      r.setStart(node, m.index); r.setEnd(node, m.index + m[0].length);
      if (r.getClientRects().length > 1) {
        broken.push({ token: m[0], ctx: t.trim().slice(Math.max(0, m.index - 10), m.index + m[0].length + 10) });
      }
    }
  }
  out.brokenNumbers = broken.slice(0, 12);
  out.brokenCount = broken.length;

  // 可点目标 <24px（WCAG 2.5.8 AA；行内链接有例外）
  const clickable = [...document.querySelectorAll('a,button,select,[role=button],input[type=button],summary')]
    .filter((el) => el.offsetParent !== null);
  out.clickableCount = clickable.length;
  out.smallTargets = clickable.filter((el) => {
    const r = el.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0 && (r.width < 24 || r.height < 24))) return false;
    // 例外：句子里的行内链接，尺寸受行高约束，不算目标过小
    if (el.tagName === 'A' && getComputedStyle(el).display === 'inline') {
      const pt = (el.parentElement && el.parentElement.innerText ? el.parentElement.innerText : '').trim();
      if (pt.length > (el.innerText || '').trim().length * 2) return false;
    }
    return true;
  }).slice(0, 8).map((el) => {
    const r = el.getBoundingClientRect();
    return { text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 14), w: Math.round(r.width), h: Math.round(r.height) };
  });

  return out;
})()
`;

const TEXT_SPACING_CSS = `
*{line-height:1.5 !important}
p,li,dd,blockquote{margin-bottom:2em !important}
*{letter-spacing:0.12em !important}
*{word-spacing:0.16em !important}
`;

// ---------------------------------------------------------------- CDP
class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map();
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.id && this.pending.has(m.id)) { this.pending.get(m.id)(m); this.pending.delete(m.id); }
    };
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      this.pending.set(id, (m) => (m.error ? rej(new Error(`${method}: ${m.error.message}`)) : res(m.result)));
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text || 'page eval failed');
    return r.result.value;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function findChrome() {
  for (const c of CHROME_CANDIDATES) if (existsSync(c)) return c;
  return null;
}

async function getWsUrl(port) {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const p = list.find((t) => t.type === 'page');
      if (p && p.webSocketDebuggerUrl) return p.webSocketDebuggerUrl;
    } catch { /* 还没起来 */ }
    await sleep(200);
  }
  throw new Error('Chrome DevTools 端口未就绪');
}

// ---------------------------------------------------------------- 判定
function judgeViewport(vp) {
  const fails = [];
  const warns = [];
  if (vp.hOverflow) fails.push(`横向溢出 ${vp.overflowBy}px`);

  if (vp.viewport >= DESKTOP_MIN) {
    const multi = vp.overMulti || [];
    const single = vp.overSingle || [];
    if (multi.length) {
      const top = multi[0];
      fails.push(`多行正文行长超标：${multi.length} 段满行超 ${LINE_MAX} 汉字，最长 ${top.chars} 字 / ${top.w}px（「${top.sample}…」）`);
    }
    if (single.length) {
      fails.push(`单行长句过长：${single.length} 段超 ${LINE_SINGLE} 汉字，最长 ${single[0].act} 字（「${single[0].sample}…」）`);
    }
  }

  for (const h of vp.headings) {
    if (h.lines.length < 2) continue;
    if (h.lastLen === 1) fails.push(`孤字：${h.tag} 末行只有「${h.lines[h.lines.length - 1]}」 ← ${JSON.stringify(h.lines)}`);
    else if (h.lastLen === 2) warns.push(`末行仅 2 字：${h.tag}「${h.lines[h.lines.length - 1]}」 ← ${JSON.stringify(h.lines)}`);
  }

  if (vp.brokenCount > 0) {
    fails.push(`混排数字被拆 ${vp.brokenCount} 处：${vp.brokenNumbers.map((b) => `「${b.token}」`).join(' ')}`);
  }

  if (vp.smallTargets.length > 0) {
    fails.push(`可点目标 <${TARGET_MIN}px ${vp.smallTargets.length} 个：${vp.smallTargets.map((s) => `「${s.text}」${s.w}×${s.h}`).join(' ')}`);
  }
  return { fails, warns };
}

// ---------------------------------------------------------------- 主流程
async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.html) { printHelp(); return 2; }

  const page = resolve(args.html);
  if (!existsSync(page)) { console.error(`文件不存在：${page}`); return 2; }

  const src = readFileSync(page, 'utf8');
  const stat = staticAudit(src);

  const ZOOM_REASON = '无头 Chrome 无法模拟真实浏览器文字缩放（Ctrl+= 是视口级缩放，CDP 无对应指令）；用 html{font-size:200%} 注入只对 rem/em 生效，本页若全 px 则测不出——必须人工开浏览器验';

  const report = { page, static: stat, viewports: [], textSpacing: null, textZoom: { status: 'not_run', reason: ZOOM_REASON }, env: {}, evidence: '' };

  const widths = args.widths.split(',').map((s) => parseInt(s.trim(), 10)).filter((n) => n >= 240 && n <= 7680);
  if (!widths.length) { console.error('--widths 无有效宽度'); return 2; }

  let dynamicOk = true;

  if (!args.staticOnly) {
    const chrome = findChrome();
    report.env.chrome = chrome || '';
    if (!chrome) {
      console.error('[环境缺失] 找不到 Chrome / Edge → 无法实测（设 CHROME_PATH 或装 Chrome）');
      dynamicOk = null;
    } else {
      const userDir = mkdtempSync(join(tmpdir(), 'tc_profile_'));
      const outDir = args.out ? resolve(args.out) : mkdtempSync(join(tmpdir(), 'tc_run_'));
      mkdirSync(outDir, { recursive: true });
      report.evidence = outDir;

      const proc = spawn(chrome, [
        '--headless=new', `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${userDir}`,
        '--no-first-run', '--no-default-browser-check', '--hide-scrollbars',
        '--allow-file-access-from-files', '--disable-gpu', 'about:blank',
      ], { stdio: 'ignore' });

      try {
        const ws = new WebSocket(await getWsUrl(CDP_PORT));
        await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
        const cdp = new CDP(ws);
        await cdp.send('Page.enable');
        await cdp.send('Runtime.enable');

        const load = async (w) => {
          await cdp.send('Emulation.setDeviceMetricsOverride', { width: w, height: 900, deviceScaleFactor: 1, mobile: w < 800 });
          await cdp.send('Page.navigate', { url: pathToFileURL(page).href });
          await sleep(1500);
          await cdp.eval('document.fonts.ready.then(() => true)');
        };
        const shoot = async (name) => {
          if (!args.keep && !args.out) return;
          const m = await cdp.send('Page.getLayoutMetrics');
          const size = m.cssContentSize;
          const shot = await cdp.send('Page.captureScreenshot', {
            format: 'png', captureBeyondViewport: true,
            clip: { x: 0, y: 0, width: size.width, height: Math.min(size.height, 7000), scale: 1 },
          });
          writeFileSync(join(outDir, name), Buffer.from(shot.data, 'base64'));
        };

        for (const w of widths) {
          await load(w);
          const vp = await cdp.eval(PROBE);
          const j = judgeViewport(vp);
          report.viewports.push({ ...vp, ...j, status: j.fails.length ? 'fail' : 'pass' });
          if (j.fails.length) dynamicOk = false;
          await shoot(`page-${w}.png`);
        }

        if (!args.noSpacing) {
          const w = widths.includes(390) ? 390 : widths[widths.length - 1];
          await load(w);
          await cdp.eval(`(() => { const s = document.createElement('style'); s.textContent = ${JSON.stringify(TEXT_SPACING_CSS)}; document.head.appendChild(s); return true; })()`);
          await sleep(400);
          const vp = await cdp.eval(PROBE);
          const j = judgeViewport(vp);
          const fails = j.fails.filter((f) => f.startsWith('横向溢出'));
          report.textSpacing = { width: w, overflow: vp.hOverflow, overflowBy: vp.overflowBy, fails, status: fails.length ? 'fail' : 'pass' };
          if (fails.length) dynamicOk = false;
          await shoot(`page-${w}-textspacing.png`);
        }

        // 200% 文字放大：无头环境无法真实模拟，恒 not_run
        report.textZoom = { status: 'not_run', reason: ZOOM_REASON };

        ws.close();
      } catch (e) {
        console.error(`[实测失败] ${e.message}`);
        dynamicOk = false;
      } finally {
        proc.kill();
        await sleep(700); // Windows 上 Chrome 退出后仍短暂占着 profile 里的文件
        try { rmSync(userDir, { recursive: true, force: true, maxRetries: 4, retryDelay: 250 }); } catch { /* 临时目录清不掉不算失败 */ }
        if (args.keep || args.out) {
          console.error(`[保留] 截图与报告在：${outDir}`);
          try { writeFileSync(join(outDir, 'report.json'), JSON.stringify(report, null, 2)); } catch { /* 写不进也不阻塞判定 */ }
        } else {
          try { rmSync(outDir, { recursive: true, force: true }); } catch { /* 同上 */ }
        }
      }
    }
  }

  // ------------------------------------------------------------ 输出
  const statFails = stat.filter((s) => !s.ok && !s.warn);
  const statWarns = stat.filter((s) => !s.ok && s.warn);
  const badStatic = statFails.length > 0;
  const verdict = !badStatic && dynamicOk !== false && dynamicOk !== null;
  const status = dynamicOk === null ? 'not_run' : verdict ? 'pass' : 'fail';
  report.status = status;

  if (args.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`\n[中文排版实测] ${basename(page)}`);
    console.log(`静态审计：${stat.length} 项 → 通过 ${stat.length - statFails.length - statWarns.length} / 失败 ${statFails.length} / 待人工 ${statWarns.length}`);
    for (const s of statFails) console.log(`  ✗ ${s.name}：${s.hint}`);
    for (const s of statWarns) console.log(`  ! ${s.name}：${s.hint}`);

    if (report.viewports.length) {
      console.log(`动态实测：${report.viewports.length} 个视口`);
      for (const v of report.viewports) {
        const head = `  [${v.viewport}] 溢出 ${v.hOverflow ? v.overflowBy + 'px' : '无'}；行长最长 ${v.maxChars} 字${v.viewport >= DESKTOP_MIN ? `（多行超 ${LINE_MAX} 字 ${(v.overMulti || []).length} 段 / 单行超 ${LINE_SINGLE} 字 ${(v.overSingle || []).length} 段）` : '（窄屏不判上限）'}；标题 ${v.headings.length} 个`;
        console.log(head);
        for (const f of v.fails) console.log(`    ✗ ${f}`);
        for (const w of v.warns) console.log(`    ! ${w}`);
      }
    }

    if (report.textSpacing) {
      const t = report.textSpacing;
      console.log(`文字间距覆盖（${t.width}px，行高1.5×/段后2×/字距0.12×/词距0.16×）：${t.status === 'pass' ? '通过' : `不过 → ${t.fails.join('；')}`}`);
    }
    if (report.textZoom.status === 'not_run') console.log(`200% 文字放大：not_run（${report.textZoom.reason}）`);

    const label = { pass: '通过', fail: '不过', not_run: '未运行（环境缺失）' }[status];
    console.log(`结论：中文排版基线${label}${args.staticOnly ? '（仅静态审计，动态实测 not_run）' : ''}\n`);
    if (status === 'pass' && statWarns.length) console.log('注意：待人工项不算通过，需人读行片段与截图确认。\n');
  }

  return status === 'pass' ? 0 : status === 'not_run' ? 2 : 1;
}

main().then((code) => process.exit(code)).catch((e) => { console.error('ERR', e.message); process.exit(2); });
