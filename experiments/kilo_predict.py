# -*- coding: utf-8 -*-
"""大模型直选大底实验·单runner预测器:每个 runner(--dim 1..40)用不同维度
提示词驱动 Kilo Code CLI 免费模型,输出 top-40 直选。

40 个维度与 dadi_predict.py 一一对应,只是把统计打分换成 LLM 推理,
便于与算法版大底做同期对照实验。
"""
import argparse, csv, re, subprocess, sys, tempfile

EXCLUDE = [(2002001, 2002070), (2002110, 2002179)]  # 3D 数据已知坏段

DIMS = {
    1:  ("数字频率·近150期", "统计最近150期内各数字(0-9)的出现频率(不限位置),优先挑选由高频数字组成的直选"),
    2:  ("数字频率·近300期", "统计最近300期内各数字的出现频率,优先挑选由高频数字组成的直选"),
    3:  ("数字频率·近800期", "以更长窗口(约800期)的数字频率为准,偏好长期热号组成的直选"),
    4:  ("数字频率·长期均衡", "从长期视角看数字频率的均衡性,优先选择贴近长期均值、不过热不过冷的数字组合"),
    5:  ("位置频率·近300期", "分别统计最近300期百位/十位/个位上各数字的频率,每个位置取各自热门数字再组合"),
    6:  ("位置频率·近800期", "以约800期窗口分别统计百/十/个位数字频率,按位置挑长期热号组合"),
    7:  ("和值", "统计历史上三位之和(和值0-27)的分布,找出高频和值区间,只在该区间内挑注"),
    8:  ("和尾", "关注和值尾数(和%10)的高频取值,按最可能开出的和尾挑注"),
    9:  ("跨度", "关注跨度(最大位-最小位)的高频区间,按最可能的跨度挑注"),
    10: ("大小形态", "分析大小形态(>=5为大)的常见模式(如大小大/小大小),按最可能形态挑注"),
    11: ("奇偶形态", "分析奇偶形态的常见模式,按最可能形态挑注"),
    12: ("质合形态", "按质数(1,2,3,5,7)与合数(0,4,6,8,9)的形态分布,按最可能形态挑注"),
    13: ("012路形态", "按数字%3余数(012路)的形态分布,按最可能的路数形态挑注"),
    14: ("最大值", "关注三位中最大值的高频取值,按最可能的最大值挑注"),
    15: ("最小值", "关注三位中最小值的高频取值,按最可能的最小值挑注"),
    16: ("均值", "关注round(和值/3)的高频取值,按最可能的均值挑注"),
    17: ("两码和", "关注任意两位之和的高频取值(每注含三对),优先选两码和落在高频区的注"),
    18: ("两码差", "关注任意两位之差绝对值的高频取值,优先选两码差落在高频区的注"),
    19: ("冷码优先", "反向思路:优先选择由近期低频/冷门数字组成的直选"),
    20: ("同位回避", "尽量避开与上一期同位置相同的数字,优先选同位重复个数最少的注"),
    21: ("数字频率·近60期", "只看最近60期的数字热度,追短期趋势挑注"),
    22: ("两码共现", "统计历史上经常同期开出的两码组合(不计位置),优先选含高频共现对的注"),
    23: ("位置频率·近150期", "分别统计最近150期百/十/个位数字频率,按位置挑短期热号组合"),
    24: ("重码迁移", "关注'上期数字换位置再现'现象:优先选含上期数字但换了位置的注"),
    25: ("数字遗漏", "关注各数字当前遗漏深度,优先选遗漏较深、可能回补的数字组合"),
    26: ("位置遗漏", "按位置看数字遗漏深度,优先选某位置遗漏较深的数字"),
    27: ("上期重码数", "统计'与上期重码个数'的历史分布,按最可能的重码个数挑注"),
    28: ("组选形态", "判断下期更可能出豹子/组三/组六,按该形态挑注"),
    29: ("序型", "按相邻两位的大小关系(升/降/平/峰/谷)的常见序型挑注"),
    30: ("AC值", "按不同两码差个数(AC值1-3)的高频取值挑注"),
    31: ("大小马尔可夫", "由上期大小形态出发,按历史上的形态转移规律推断本期形态再挑注"),
    32: ("遗漏动量", "综合'数字当前遗漏深度×历史上该深度附近的开出率',选动量最强的组合"),
    33: ("和值组距", "按和值//5组距的高频区段挑注"),
    34: ("跨度·近150期", "只看最近150期的跨度分布,按短期高频跨度挑注"),
    35: ("和尾·近150期", "只看最近150期的和尾分布,按短期高频和尾挑注"),
    36: ("两码和尾", "关注任意两位之和的尾数的高频取值,优先选对和尾落在高频区的注"),
    37: ("百个差", "关注百位与个位之差绝对值的高频取值,按最可能的百个差挑注"),
    38: ("连号", "关注含连号对(差为1的两位)个数的历史分布,按最可能的连号个数挑注"),
    39: ("近期回避", "近200期已开出过的直选降权,偏好历史上未开出或久未开出的注"),
    40: ("上期数字回避", "尽量不使用上一期出现过的数字,选与上期数字交集最小的注"),
}

def load(path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            s = r["ShiJiHao"].strip()
            if len(s) == 3 and s.isdigit():
                iss = int(r["Issue"])
                if not any(a <= iss <= b for a, b in EXCLUDE):
                    rows.append((iss, s))
    rows.sort()
    return rows

def digit_freq(draws, W):
    seg = draws[-W:]
    n = len(seg)
    return {d: sum(1 for s in seg if d in s) / n for d in range(10)}

def pos_freq(draws, W):
    seg = draws[-W:]
    n = len(seg)
    return [{d: sum(1 for s in seg if s[p] == d) / n for d in range(10)} for p in range(3)]

def digit_gaps(draws):
    return {d: next((i for i, s in enumerate(reversed(draws)) if d in s), len(draws))
            for d in range(10)}

def stats_block(draws):
    out = ["\n附:程序预统计(%,数字频率=含该数字的期数占比):"]
    for W in (150, 300, 800, 2000):
        if len(draws) >= W:
            fr = digit_freq(draws, W)
            out.append(f"数字频率W{W}: " + " ".join(f"{d}:{fr[d] * 100:.0f}" for d in range(10)))
    if len(draws) >= 300:
        pf = pos_freq(draws, 300)
        for p, nm in enumerate("百十个"):
            out.append(f"{nm}位频率W300: " + " ".join(f"{d}:{pf[p][d] * 100:.0f}" for d in range(10)))
    return "\n".join(out)

def build_prompt(dim, rows):
    name, ins = DIMS[dim]
    draws = [tuple(int(c) for c in s) for _, s in rows]
    recent = rows[-100:]
    hist = "\n".join(f"{iss} {s}" for iss, s in recent)
    g = digit_gaps(draws)
    return f"""你是福彩3D试机号直选分析师。以下是最近{len(recent)}期历史(每行:期号 三位直选,最新一期在最后):
{hist}
{stats_block(draws)}
上一期:{rows[-1][0]}期 开出 {rows[-1][1]}
各数字当前遗漏期数: {' '.join(f'{d}:{g[d]}' for d in range(10))}

本期分析维度「{name}」:{ins}。
请只基于上面给出的数据,按该维度推断下一期最可能开出的直选。

输出要求:
- 不要使用任何工具,不要读写文件,直接推理
- 分析过程不超过3行,然后单独输出一行 =====
- 分隔线之后恰好输出40注,每行一注三位有序数字(000-999),不带编号或其它字符"""

def extract(text):
    lines = text.splitlines()
    marks = [i for i, l in enumerate(lines) if re.fullmatch(r"\s*=+\s*", l)]
    tail = lines[marks[-1] + 1:] if marks else []

    def scan(ls):
        bare, inline = [], []
        for l in ls:
            s = re.sub(r"^\s*(?:\d+|[-*•#]+)[.、)」\]】\s]*\s*", "", l).strip()
            if re.fullmatch(r"\d{3}", s):
                bare.append(s)
            else:
                inline += re.findall(r"(?<![\d.])\d{3}(?![\d.])", s)
        return bare or inline

    nums = scan(tail) or scan(lines)
    return list(dict.fromkeys(nums))[:40]

def call_kilo(model, prompt, timeout_s):
    with tempfile.TemporaryDirectory() as td:
        return subprocess.run(
            ["kilo", "run", "--auto", "--pure", "-m", model, prompt],
            capture_output=True, text=True, cwd=td, timeout=timeout_s)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dim", type=int, required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="kilo/nvidia/nemotron-3-ultra-550b-a55b:free")
    ap.add_argument("--timeout", type=int, default=420)
    a = ap.parse_args()
    rows = load(a.csv)
    name, _ = DIMS[a.dim]
    prompt = build_prompt(a.dim, rows)

    nums, err = [], ""
    for attempt in (1, 2):
        try:
            p = call_kilo(a.model, prompt, a.timeout)
        except subprocess.TimeoutExpired:
            err = f"timeout {a.timeout}s"
            continue
        text = p.stdout + "\n" + p.stderr
        if p.returncode != 0:
            err = f"kilo exit {p.returncode}: {text[-200:]}"
            continue
        nums = extract(text)
        if nums:
            break
        err = "no picks parsed"
    if not nums and err:
        print(f"dim{a.dim} {name} 两次尝试失败: {err}", file=sys.stderr)

    with open(a.out, "w", encoding="utf-8") as f:
        f.write(f"# dim{a.dim} {name} model={a.model} n={len(nums)}\n")
        for n in nums:
            f.write(n + "\n")
    print(f"dim{a.dim} {name} 共{len(nums)}注: {' '.join(nums)}")

if __name__ == "__main__":
    main()
