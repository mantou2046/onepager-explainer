"""gen_tts.py —— 讲稿 → Edge-TTS 真人语音（女声 + 男声双份）

用法：
    python gen_tts.py --script 讲稿.txt --out ./tts_out
    # 可选：--min-kb 8（单段 mp3 体积下限）--tol 50（时长-字数偏离容差 %）--bps 48000（码率假设）

产物：--out/女声/step01.mp3 … 、--out/男声/step01.mp3 …

可靠性与质量设计（skill「可选语音分支」的第二层门禁）：
- 幂等：已存在且通过校验的 mp3 跳过；已存在但校验不过 → 删除重合成
- 候选声音回退：首选声音不在服务器列表里就换下一个，第一段定声后本组固定
- 偶发失败重试 3 次
- 合成后自动质量校验（三条）：
    1) 帧头合法：ID3v2 (`ID3`) 或 MPEG 帧同步头 (0xFF Ex)
    2) 体积 ≥ --min-kb KB（低于视为截断/空合成）
    3) 时长估算（size*8/bps）与讲稿字数期望（中文字数/4.5 字每秒）偏离 ≤ --tol %
 校验不过 → 打印 WARN、计入失败、exit code 1；文件保留供人工判断（不静默吞掉）
- 声音配置沿用 K8s/Helm 页既定：女声 XiaoxiaoNeural / 男声 YunxiNeural / 语速 -5%

依赖：edge-tts（pip install -U edge-tts）。本机受管 venv 示例：
    python gen_tts.py ...
"""
import argparse
import asyncio
import pathlib
import re
import sys

import edge_tts

PREFER = {
    "女声": ["zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural"],
    "男声": ["zh-CN-YunxiNeural", "zh-CN-YunjianNeural", "zh-CN-YunyangNeural"],
}
RATE = "-5%"

# ---------- 质量校验 ----------


def mp3_valid(path: pathlib.Path, min_bytes: int) -> tuple[bool, str]:
    """帧头合法 + 体积下限。返回 (是否通过, 说明)。"""
    b = path.read_bytes()
    if len(b) < min_bytes:
        return False, f"{len(b)}B < 下限 {min_bytes}B（疑似截断/空合成）"
    head_ok = b[:3] == b"ID3" or (b[0] == 0xFF and (b[1] & 0xE0) == 0xE0)
    if not head_ok:
        return False, "帧头非法（既非 ID3 也非 MPEG 同步头）"
    return True, "ok"


def est_seconds(size: int, bps: int) -> float:
    return size * 8 / bps


def cjk_chars(s: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", s))


def check_duration(path: pathlib.Path, text: str, bps: int, tol: float) -> tuple[bool, str]:
    want = cjk_chars(text) / 4.5  # 中文朗读约 4.5 字/秒（rate -5% 的经验值）
    if want <= 0:
        return True, "no-cjk"
    got = est_seconds(path.stat().st_size, bps)
    dev = abs(got - want) / want * 100
    ok = dev <= tol
    return ok, f"估算 {got:.1f}s vs 期望 {want:.1f}s（偏离 {dev:.0f}%）"


# ---------- 合成 ----------


async def available() -> dict:
    zh = [v for v in await edge_tts.list_voices() if v["Locale"] == "zh-CN"]
    return {
        "女声": [v["ShortName"] for v in zh if v["Gender"] == "Female"],
        "男声": [v["ShortName"] for v in zh if v["Gender"] == "Male"],
    }


async def synth(content: str, voice: str, out: pathlib.Path) -> bool:
    for _ in range(3):
        try:
            await edge_tts.Communicate(content, voice, rate=RATE).save(str(out))
            if out.exists() and out.stat().st_size > 0:
                return True
        except edge_tts.exceptions.NoAudioReceived:
            await asyncio.sleep(1.5)
        except Exception as e:  # 网络波动等：重试即可
            print(f"  合成异常（将重试）：{type(e).__name__}: {e}")
            await asyncio.sleep(1.5)
    if out.exists() and out.stat().st_size == 0:
        out.unlink()
    return False


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="讲稿 txt（按空行分段）")
    ap.add_argument("--out", required=True, help="输出根目录（生成 女声/ 男声/ 子目录）")
    ap.add_argument("--min-kb", type=int, default=8, help="单段 mp3 体积下限（KB），默认 8")
    ap.add_argument("--tol", type=float, default=50, help="时长-字数偏离容差（%%），默认 50")
    ap.add_argument("--bps", type=int, default=48000, help="码率假设（bit/s），默认 48000")
    args = ap.parse_args()

    script = pathlib.Path(args.script)
    outroot = pathlib.Path(args.out)
    min_bytes = args.min_kb * 1024

    steps = [s.strip() for s in re.split(r"\n\s*\n", script.read_text(encoding="utf-8")) if s.strip()]
    if not steps:
        print("讲稿为空：按「空行分段」至少需要 1 段", file=sys.stderr)
        return 2
    print(f"讲稿共 {len(steps)} 段；中文字符数：{[cjk_chars(s) for s in steps]}")

    failures = []
    avail = await available()
    for folder, prefer in PREFER.items():
        outdir = outroot / folder
        outdir.mkdir(parents=True, exist_ok=True)
        cands = [v for v in prefer if v in avail[folder]]
        cands += [v for v in avail[folder] if v not in cands]
        print(f"\n【{folder}】候选声音：{cands}")
        voice = None
        for i, content in enumerate(steps, 1):
            out = outdir / f"step{i:02d}.mp3"
            if out.exists():
                ok, why = mp3_valid(out, min_bytes)
                ok2, why2 = check_duration(out, content, args.bps, args.tol)
                if ok and ok2:
                    print("跳过（已存在且校验通过）", out.name)
                    continue
                print(f"已存在但校验不过（{why}；{why2}）→ 删除重合成", out.name)
                out.unlink()
            if voice is None:
                for v in cands:
                    if await synth(content, v, out):
                        voice = v
                        print(f"使用声音 {v}")
                        break
                if voice is None:
                    print(f"{folder} 的所有候选声音都失败了，跳过该组")
                    failures.append(folder)
                    break
            elif not await synth(content, voice, out):
                print("失败", out.name)
                failures.append(str(out))
                continue
            ok, why = mp3_valid(out, min_bytes)
            ok2, why2 = check_duration(out, content, args.bps, args.tol)
            if not (ok and ok2):
                print(f"⚠️ 质量警告 {folder}/{out.name}：{why}；{why2}（文件保留，请人工抽听确认）")
                failures.append(f"{folder}/{out.name}")
            else:
                print("完成", folder, out.name)

    if failures:
        print(f"\n共 {len(failures)} 个文件未过自动校验，exit 1。可人工抽听后放行（远程embed）。")
        return 1
    print("\n全部通过自动校验。下一步：讲稿人审 + 至少 1 段人耳抽听 → 通过再 embed。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
