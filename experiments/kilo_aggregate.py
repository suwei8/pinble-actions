# -*- coding: utf-8 -*-
"""大模型直选大底实验·聚合器(正向模式):
1. 收齐 preds/*.txt 40个runner预测 → 并集 = 大底(模型选什么就要什么)
2. 大底写 pools_kilo/{target}.txt;其余号码视为排除
3. 结算账本中 pending 行 vs 最新试机号
4. TG 推送结果
"""
import argparse, csv, glob, itertools, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, "experiments", "kilo_ledger.csv")
POOLS = os.path.join(BASE, "experiments", "pools_kilo")
FIELDS = ["target_issue", "generated_at", "kill_n", "pool_n", "status", "actual", "hit", "actual_rank"]
ALL = {"".join(map(str, p)) for p in itertools.product(range(10), repeat=3)}
EXCLUDE = [(2002001, 2002070), (2002110, 2002179)]
BJ = ZoneInfo("Asia/Shanghai")

def load_csv(path):
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            s = r["ShiJiHao"].strip()
            if len(s) == 3 and s.isdigit():
                iss = int(r["Issue"])
                if not any(a <= iss <= b for a, b in EXCLUDE):
                    out[iss] = s
    return out

def next_issue(latest):
    y = datetime.now(BJ).year
    return y * 1000 + 1 if latest // 1000 < y else latest + 1

def read_ledger():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def write_ledger(rows):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)

def load_pool(issue):
    p = os.path.join(POOLS, f"{issue}.txt")
    if not os.path.exists(p):
        return set()
    return {x.strip() for x in open(p, encoding="utf-8") if x.strip() and not x.startswith("#")}

def load_ranked(issue):
    # {issue}_ranked.txt: 按加权得分降序的全量并集,供结算时算 actual 名次
    p = os.path.join(POOLS, f"{issue}_ranked.txt")
    if not os.path.exists(p):
        return []
    return [x.strip() for x in open(p, encoding="utf-8") if x.strip() and not x.startswith("#")]

def naive_pool(actual_map, n):
    # 朴素基线:近300期数字集合频率给全部1000注打分取top-n,用于同期对照
    draws = [s for _, s in sorted(actual_map.items())][-300:]
    fr = {d: sum(1 for s in draws if str(d) in s) / len(draws) for d in range(10)}
    r = sorted(ALL, key=lambda p: -(fr[int(p[0])] + fr[int(p[1])] + fr[int(p[2])]))
    return set(r[:n])

def tg(token, chat, text):
    import requests
    for i in range(0, len(text), 3800):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text[i:i + 3800]}, timeout=15)
        r.raise_for_status()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--preds", required=True)
    ap.add_argument("--model", default="")              # 模型名,仅用于消息展示
    ap.add_argument("--actual", default="")             # 盲测判决用的已知实际号
    ap.add_argument("--no-ledger", action="store_true") # 盲测模式:不写账本/池文件
    ap.add_argument("--pool-n", type=int, default=350)  # 大底目标注数(加权得分top-N)
    ap.add_argument("--upto", type=int, default=0)      # 盲测:只认期号<=upto的数据
    ap.add_argument("--neg", action="store_true")       # 负向:并集排名=排除候选
    ap.add_argument("--kill-n", type=int, default=200)  # 负向排除注数(残余=大底)
    a = ap.parse_args()

    actual_map = load_csv(a.csv)
    if a.upto > 0:
        actual_map = {k: v for k, v in actual_map.items() if k <= a.upto}
    latest = max(actual_map)
    target = next_issue(latest)

    score = {}
    files = sorted(glob.glob(os.path.join(a.preds, "*.txt")))
    for p in files:
        r = 0
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if len(line) == 3 and line.isdigit():
                r += 1
                score[line] = score.get(line, 0) + (41 - r)  # 维度内第r名得41-r分
    ranked = sorted(score, key=lambda n: (-score[n], n))
    if a.neg:
        # 负向杀号:加权排名靠前=多维度共认"最不可能" → 杀掉,残余800=大底
        kill = set(ranked[:a.kill_n])
        pool = sorted(ALL - kill)
        print(f"runner预测文件 {len(files)} 个,并集 {len(score)} 注 → 负向杀 top{len(kill)} 大底 {len(pool)} 注")
    else:
        pool = sorted(ranked[:a.pool_n])   # 正向·加权得分 top-N = 大底
        kill = ALL - set(pool)             # 其余号码视为排除
        print(f"runner预测文件 {len(files)} 个,并集 {len(score)} 注 → 加权top{a.pool_n} 大底 {len(pool)} 注,排除 {len(kill)} 注")

    # 结算(盲测模式跳过账本)
    ledger = read_ledger()
    settled_now = None
    if not a.no_ledger:
        for row in ledger:
            if row["status"] == "pending" and int(row["target_issue"]) in actual_map:
                act = actual_map[int(row["target_issue"])]
                row["actual"] = act
                row["hit"] = "1" if act in load_pool(int(row["target_issue"])) else "0"
                rk = load_ranked(int(row["target_issue"]))
                row["actual_rank"] = str(rk.index(act) + 1) if act in rk else ("out" if rk else "")
                row["status"] = "settled"
                settled_now = row

        # 本期行:同日重跑则覆盖
        gen = datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")
        ledger = [r for r in ledger if not (r["target_issue"] == str(target) and r["status"] == "pending")]
        ledger.append({"target_issue": str(target), "generated_at": gen,
                       "kill_n": str(len(kill)), "pool_n": str(len(pool)),
                       "status": "pending", "actual": "", "hit": "", "actual_rank": ""})
        os.makedirs(POOLS, exist_ok=True)
        with open(os.path.join(POOLS, f"{target}.txt"), "w", encoding="utf-8") as f:
            mode = f"负向·杀top{a.kill_n}" if a.neg else f"正向·加权top{a.pool_n}"
            f.write(f"# {target}期大模型直选大底({mode}) 生成{gen} 大底{len(pool)}注 排除{len(kill)}注\n")
            f.write("\n".join(pool) + "\n")
        # 全量名次文件:结算时用 actual_rank 记录实际号在加权榜上的位置
        with open(os.path.join(POOLS, f"{target}_ranked.txt"), "w", encoding="utf-8") as f:
            f.write(f"# {target}期 加权得分降序全量并集({len(ranked)}注) 生成{gen}\n")
            f.write("\n".join(ranked) + "\n")
        write_ledger(ledger)

    done = [] if a.no_ledger else [r for r in ledger if r["status"] == "settled"]
    nh = sum(1 for r in done if r["hit"] == "1")
    msg = f"拼搏 {target}期 大模型直选大底实验·{'负向' if a.neg else '正向'}(福彩3D)\n"
    if a.model:
        msg += f"模型 {a.model}\n"
    if a.neg:
        msg += (f"40维负向runner → 并集 {len(score)} 注,杀top{len(kill)} "
                f"→ 大底 {len(pool)} 注\n")
    else:
        msg += (f"40维提示词runner → 并集 {len(score)} 注,加权top{a.pool_n} "
                f"→ 大底 {len(pool)} 注(排除 {len(kill)} 注)\n")
    if settled_now:
        msg += (f"上期结算:{settled_now['target_issue']}期 实际 {settled_now['actual']} "
                f"→ {'命中' if settled_now['hit'] == '1' else '未中'}"
                f"(名次{settled_now.get('actual_rank', '?')})\n")
    if done:
        msg += f"累计:{nh}/{len(done)} 命中({nh / len(done) * 100:.0f}%)\n"
    if a.actual:
        if a.neg:
            for N in dict.fromkeys([a.kill_n, 300]):   # 主口径 + kill300 对照
                eff = min(N, len(ranked))
                s = ALL - set(ranked[:eff])
                verdict = "命中大底" if a.actual in s else "未中"
                msg += (f"盲测判决kill{eff}:{target}期实际 {a.actual} → {verdict}"
                        f"(大底{1000 - eff}注,随机基线{(1000 - eff) / 10:.0f}%)\n")
        else:
            for N in dict.fromkeys([a.pool_n, 275]):   # 主口径 + top275 对照口径
                eff = min(N, len(ranked))
                s = set(ranked[:N])
                verdict = "命中大底" if a.actual in s else "未中"
                msg += (f"盲测判决top{eff}:{target}期实际 {a.actual} → {verdict}"
                        f"(大底{eff}注,随机基线{eff / 10:.0f}%)\n")
        # 实际号在加权榜上的名次——比命中与否更细的排序质量信号
        rk = ranked.index(a.actual) + 1 if a.actual in score else None
        msg += f"实际号加权排名:{f'{rk}/{len(ranked)}' if rk else '未入并集'}\n"
        # 朴素基线:近300期数字频率top-N,同期对照LLM有无增量价值
        nb = naive_pool(actual_map, min(a.kill_n if a.neg else a.pool_n, len(ranked)))
        if a.neg:
            nb = ALL - nb   # 负向口径:朴素"最可能"的kill_n注被杀,残余为大底
        msg += (f"朴素基线top{len(nb)}(近300期数字频率):{a.actual} → "
                f"{'命中' if a.actual in nb else '未中'}\n")
    msg += "大底:\n" + " ".join(pool)
    print(msg[:500] + ("..." if len(msg) > 500 else ""))

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if token and chat:
        tg(token, chat, msg)
        print("TG 已发送")
    else:
        print("::warning::未设置 TG secret,跳过推送")

if __name__ == "__main__":
    main()
