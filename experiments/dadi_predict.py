# -*- coding: utf-8 -*-
"""直选大底实验·单维度预测器:每个 runner(--dim 1..40)输出 top-40 直选。

40 个维度各自独立打分:
  1-4   数字集合频率   W150/300/800/2000
  5-6   位置数字频率   W300/800
  7-9   和值/和尾/跨度频率 W500
  10-13 大小/奇偶/质合/012路形态频率 W500
  14-16 最大/最小/均值频率 W500
  17-18 两码和/两码差频率 W500
  19    冷码优先(反向数字频率)W300
  20    同位回避优先(与上期同位个数最少)
  21    数字集合频率   W60
  22    数字对共现频率 W500(哪些两码历史上同开)
  23    位置数字频率   W150
  24    重码迁移频率   W500(上期数字换位置再现的个数分布)
  25    数字当前遗漏深度
  26    位置当前遗漏深度
  27    与上期重码个数频率 W500
  28    组选形态(豹子/组三/组六)频率 W500
  29    序型(升/降/平/峰/谷)频率 W500
  30    AC值(不同两码差个数)频率 W500
  31    大小形态马尔可夫转移 W500(P(本期形态|上期形态))
  32    遗漏动量(当前遗漏深度×该深度历史命中率)
  33    和值组距(sum//5)频率 W500
  34-35 跨度/和尾频率 W150
  36    两码和尾(对和%10)频率 W500
  37    百个差频率 W500
  38    连号对数频率 W500
  39    近期开出回避 W200(近200期开过的罚分)
  40    上期数字完全回避(用上期数字越少越好)
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

def pairmodscore(draws, W):
    seg = draws[-W:]
    n = len(seg)
    c = Counter()
    for s in seg:
        for a, b in ((0, 1), (0, 2), (1, 2)):
            c[(s[a] + s[b]) % 10] += 1
    mr = {k: v / (3 * n) for k, v in c.items()}
    return lambda p: (mr.get((p[0] + p[1]) % 10, 0)
                      + mr.get((p[0] + p[2]) % 10, 0)
                      + mr.get((p[1] + p[2]) % 10, 0))

def digit_gaps(draws):
    return {d: next((i for i, s in enumerate(reversed(draws)) if d in s), len(draws))
            for d in range(10)}

def pos_gaps(draws):
    rev = list(reversed(draws))
    return [{d: next((i for i, s in enumerate(rev) if s[p] == d), len(draws))
             for d in range(10)} for p in range(3)]

def m_zuxuan(s):  return {1: "豹子", 2: "组三", 3: "组六"}[len(set(s))]
def m_xuxing(s):
    a = (s[0] > s[1]) - (s[0] < s[1]); b = (s[1] > s[2]) - (s[1] < s[2])
    return f"{a:+d}{b:+d}"
def m_ac(s):    return len({abs(s[0] - s[1]), abs(s[0] - s[2]), abs(s[1] - s[2])})
def m_hzuj(s):  return sum(s) // 5
def m_bgcha(s): return abs(s[0] - s[2])
def m_lian(s):  return sum(1 for a, b in ((0, 1), (0, 2), (1, 2)) if abs(s[a] - s[b]) == 1)

def repeat_rates(draws, W):
    c = Counter(len(set(draws[i]) & set(draws[i - 1])) for i in range(len(draws) - W, len(draws)))
    return {k: v / W for k, v in c.items()}

def pairco(draws, W):
    seg = draws[-W:]
    n = len(seg)
    c = Counter()
    for s in seg:
        st = sorted(set(s))
        for a in range(len(st)):
            for b in range(a + 1, len(st)):
                c[(st[a], st[b])] += 1
    mr = {k: v / n for k, v in c.items()}
    def f(p):
        st = sorted(set(p))
        return sum(mr.get((st[a], st[b]), 0) for a in range(len(st)) for b in range(a + 1, len(st)))
    return f

def mig_rates(draws, W):
    c = Counter(sum(1 for j in range(3) if draws[i][j] in draws[i - 1] and draws[i][j] != draws[i - 1][j])
                for i in range(len(draws) - W, len(draws)))
    return {k: v / W for k, v in c.items()}

def markov_rates(draws, W, fn):
    c = Counter(); d = Counter()
    for i in range(len(draws) - W, len(draws)):
        pv, s = fn(draws[i - 1]), fn(draws[i])
        d[pv] += 1; c[(pv, s)] += 1
    pm = fn(draws[-1])
    den = max(d.get(pm, 0), 1)
    return {m: c.get((pm, m), 0) / den for m in set(fn(s) for s in draws[-W:])}

def gap_hit_fn(draws):
    hits = Counter(); tot = Counter()
    gap = {d: next((i for i, s in enumerate(reversed(draws[:100])) if d in s), 100) for d in range(10)}
    for i in range(100, len(draws)):
        s = draws[i]
        for d in range(10):
            tot[gap[d]] += 1
            if d in s: hits[gap[d]] += 1
        for d in range(10):
            gap[d] = 0 if d in s else gap[d] + 1
    return lambda g: (hits[g] + 0.3) / (tot[g] + 1)

def build_dims(draws):
    dr150 = digit_rates(draws, 150); dr300 = digit_rates(draws, 300)
    dr800 = digit_rates(draws, 800); dr2k = digit_rates(draws, 2000)
    prev = draws[-1]
    sr = setscore(dr300)
    dg = digit_gaps(draws); pg = pos_gaps(draws)
    rec = Counter(draws[-200:]); gr = gap_hit_fn(draws)
    return {
        0: ("__tiebreak__", sr),
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
        21: ("数字集合频率W60", setscore(digit_rates(draws, 60))),
        22: ("两码共现频率W500", pairco(draws, 500)),
        23: ("位置频率W150", posscore(pos_rates(draws, 150))),
        24: ("重码迁移频率W500",
             metricscore(mig_rates(draws, 500),
                         lambda p: sum(1 for j in range(3) if p[j] in prev and p[j] != prev[j]))),
        25: ("数字遗漏深度", lambda p: sum(dg[d] for d in p)),
        26: ("位置遗漏深度", lambda p: sum(pg[i][p[i]] for i in range(3))),
        27: ("上期重码数频率W500",
             metricscore(repeat_rates(draws, 500), lambda p: len(set(p) & set(prev)))),
        28: ("组选形态W500", metricscore(metric_rates(draws, 500, m_zuxuan), m_zuxuan)),
        29: ("序型W500", metricscore(metric_rates(draws, 500, m_xuxing), m_xuxing)),
        30: ("AC值W500", metricscore(metric_rates(draws, 500, m_ac), m_ac)),
        31: ("大小马尔可夫W500", metricscore(markov_rates(draws, 500, m_dx), m_dx)),
        32: ("遗漏动量", lambda p: sum(gr(dg[d]) for d in p)),
        33: ("和值组距W500", metricscore(metric_rates(draws, 500, m_hzuj), m_hzuj)),
        34: ("跨度频率W150", metricscore(metric_rates(draws, 150, m_kuadu), m_kuadu)),
        35: ("和尾频率W150", metricscore(metric_rates(draws, 150, m_hewei), m_hewei)),
        36: ("两码和尾W500", pairmodscore(draws, 500)),
        37: ("百个差频率W500", metricscore(metric_rates(draws, 500, m_bgcha), m_bgcha)),
        38: ("连号对数W500", metricscore(metric_rates(draws, 500, m_lian), m_lian)),
        39: ("近期开出回避W200", lambda p: -rec.get(p, 0) * 10 + sr(p) * 0.01),
        40: ("上期数字回避", lambda p: -len(set(p) & set(prev)) * 10 + sr(p) * 0.01),
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
    tb = dims[0][1]
    ranked = sorted(PERMS, key=lambda p: (-fn(p), -tb(p), p))
    top = ranked[:40]
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(f"# dim{a.dim} {name}\n")
        for p in top:
            f.write("".join(map(str, p)) + "\n")
    print(f"dim{a.dim} {name} 共{len(top)}注:")
    print(" ".join("".join(map(str, p)) for p in top))

if __name__ == "__main__":
    main()
