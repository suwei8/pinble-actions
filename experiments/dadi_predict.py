# -*- coding: utf-8 -*-
"""直选大底实验·单维度预测器:每个 runner(--dim 1..20)输出 top-40 直选。

20 个维度各自独立打分:
  1-4   数字集合频率   W150/300/800/2000
  5-6   位置数字频率   W300/800
  7-9   和值/和尾/跨度频率 W500
  10-13 大小/奇偶/质合/012路形态频率 W500
  14-16 最大/最小/均值频率 W500
  17-18 两码和/两码差频率 W500
  19    冷码优先(反向数字频率)W300
  20    同位回避优先(与上期同位个数最少)
"""
import argparse, csv, itertools
from collections import Counter

PERMS = list(itertools.product(range(10), repeat=3))
EXCLUDE = [(2002001, 2002070), (2002110, 2002179)]  # 3D 数据已知坏段

def load(path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            s = r["ShiJiHao"].strip()
            if len(s) == 3 and s.isdigit():
                iss = int(r["Issue"])
                if not any(a <= iss <= b for a, b in EXCLUDE):
                    rows.append((iss, tuple(int(c) for c in s)))
    rows.sort()
    return [s for _, s in rows]

def digit_rates(draws, W):
    seg = draws[-W:]
    n = len(seg)
    return {d: sum(1 for s in seg if d in s) / n for d in range(10)}

def pos_rates(draws, W):
    seg = draws[-W:]
    n = len(seg)
    return [{d: sum(1 for s in seg if s[p] == d) / n for d in range(10)} for p in range(3)]

def metric_rates(draws, W, fn):
    seg = draws[-W:]
    n = len(seg)
    c = Counter(fn(s) for s in seg)
    return {k: v / n for k, v in c.items()}

def m_hezhi(s): return sum(s)
def m_hewei(s): return sum(s) % 10
def m_kuadu(s): return max(s) - min(s)
def m_dx(s):    return "".join("大" if d >= 5 else "小" for d in s)
def m_jo(s):    return "".join("奇" if d % 2 else "偶" for d in s)
def m_zh(s):    return "".join("质" if d in (1, 2, 3, 5, 7) else "合" for d in s)
def m_r012(s):  return "".join(str(d % 3) for d in s)
def m_max(s):   return max(s)
def m_min(s):   return min(s)
def m_avg(s):   return round(sum(s) / 3)

def setscore(dr):
    return lambda p: dr[p[0]] + dr[p[1]] + dr[p[2]]

def posscore(pr):
    return lambda p: pr[0][p[0]] + pr[1][p[1]] + pr[2][p[2]]

def metricscore(mr, fn):
    return lambda p: mr.get(fn(p), 0.0)

def pairscore(draws, W, diff=False):
    seg = draws[-W:]
    n = len(seg)
    c = Counter()
    for s in seg:
        for a, b in ((0, 1), (0, 2), (1, 2)):
            v = abs(s[a] - s[b]) if diff else s[a] + s[b]
            c[v] += 1
    mr = {k: v / (3 * n) for k, v in c.items()}
    return lambda p: (mr.get(abs(p[0] - p[1]) if diff else p[0] + p[1], 0)
                      + mr.get(abs(p[0] - p[2]) if diff else p[0] + p[2], 0)
                      + mr.get(abs(p[1] - p[2]) if diff else p[1] + p[2], 0))

def build_dims(draws):
    dr150 = digit_rates(draws, 150); dr300 = digit_rates(draws, 300)
    dr800 = digit_rates(draws, 800); dr2k = digit_rates(draws, 2000)
    prev = draws[-1]
    sr = setscore(dr300)
    return {
        1: ("数字集合频率W150", setscore(dr150)),
        2: ("数字集合频率W300", sr),
        3: ("数字集合频率W800", setscore(dr800)),
        4: ("数字集合频率W2000", setscore(dr2k)),
        5: ("位置频率W300", posscore(pos_rates(draws, 300))),
        6: ("位置频率W800", posscore(pos_rates(draws, 800))),
        7: ("和值频率W500", metricscore(metric_rates(draws, 500, m_hezhi), m_hezhi)),
        8: ("和尾频率W500", metricscore(metric_rates(draws, 500, m_hewei), m_hewei)),
        9: ("跨度频率W500", metricscore(metric_rates(draws, 500, m_kuadu), m_kuadu)),
        10: ("大小形态W500", metricscore(metric_rates(draws, 500, m_dx), m_dx)),
        11: ("奇偶形态W500", metricscore(metric_rates(draws, 500, m_jo), m_jo)),
        12: ("质合形态W500", metricscore(metric_rates(draws, 500, m_zh), m_zh)),
        13: ("012路形态W500", metricscore(metric_rates(draws, 500, m_r012), m_r012)),
        14: ("最大值频率W500", metricscore(metric_rates(draws, 500, m_max), m_max)),
        15: ("最小值频率W500", metricscore(metric_rates(draws, 500, m_min), m_min)),
        16: ("均值频率W500", metricscore(metric_rates(draws, 500, m_avg), m_avg)),
        17: ("两码和频率W500", pairscore(draws, 500, diff=False)),
        18: ("两码差频率W500", pairscore(draws, 500, diff=True)),
        19: ("冷码优先W300", lambda p: -sr(p)),
        20: ("同位回避", lambda p: -(sum(1 for i in range(3) if p[i] == prev[i])) * 10
                                   + posscore(pos_rates(draws, 300))(p) * 0.01),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dim", type=int, required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    draws = load(a.csv)
    dims = build_dims(draws)
    name, fn = dims[a.dim]
    ranked = sorted(PERMS, key=lambda p: (-fn(p), p))
    top = ranked[:40]
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(f"# dim{a.dim} {name}\n")
        for p in top:
            f.write("".join(map(str, p)) + "\n")
    print(f"dim{a.dim} {name}: top5={[''.join(map(str,p)) for p in top[:5]]}")

if __name__ == "__main__":
    main()
