# -*- coding: utf-8 -*-
"""大模型直选大底实验·聚合器:
1. 收齐 preds/*.txt 40个runner预测 → 并集 = 杀号
2. 残余 = 大底,写 pools_kilo/{target}.txt
3. 结算账本中 pending 行 vs 最新试机号
4. TG 推送结果
"""
import argparse, csv, glob, itertools, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, "experiments", "kilo_ledger.csv")
POOLS = os.path.join(BASE, "experiments", "pools_kilo")
FIELDS = ["target_issue", "generated_at", "kill_n", "pool_n", "status", "actual", "hit"]
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
    a = ap.parse_args()

    actual_map = load_csv(a.csv)
    latest = max(actual_map)
    target = next_issue(latest)

    kill = set()
    files = sorted(glob.glob(os.path.join(a.preds, "*.txt")))
    for p in files:
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if len(line) == 3 and line.isdigit():
                kill.add(line)
    pool = sorted(ALL - kill)
    print(f"runner预测文件 {len(files)} 个,杀号并集 {len(kill)} 注,大底 {len(pool)} 注")

    # 结算(盲测模式跳过账本)
    ledger = read_ledger()
    settled_now = None
    if not a.no_ledger:
        for row in ledger:
            if row["status"] == "pending" and int(row["target_issue"]) in actual_map:
                act = actual_map[int(row["target_issue"])]
                row["actual"] = act
                row["hit"] = "1" if act in load_pool(int(row["target_issue"])) else "0"
                row["status"] = "settled"
                settled_now = row

        # 本期行:同日重跑则覆盖
        gen = datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")
        ledger = [r for r in ledger if not (r["target_issue"] == str(target) and r["status"] == "pending")]
        ledger.append({"target_issue": str(target), "generated_at": gen,
                       "kill_n": str(len(kill)), "pool_n": str(len(pool)),
                       "status": "pending", "actual": "", "hit": ""})
        os.makedirs(POOLS, exist_ok=True)
        with open(os.path.join(POOLS, f"{target}.txt"), "w", encoding="utf-8") as f:
            f.write(f"# {target}期大模型直选大底 生成{gen} 杀号{len(kill)}注 大底{len(pool)}注\n")
            f.write("\n".join(pool) + "\n")
        write_ledger(ledger)

    done = [] if a.no_ledger else [r for r in ledger if r["status"] == "settled"]
    nh = sum(1 for r in done if r["hit"] == "1")
    msg = f"拼搏 {target}期 大模型直选大底实验(福彩3D)\n"
    if a.model:
        msg += f"模型 {a.model}\n"
    msg += f"40维提示词runner×40注 → 杀号并集 {len(kill)} 注 → 大底 {len(pool)} 注\n"
    if settled_now:
        msg += (f"上期结算:{settled_now['target_issue']}期 实际 {settled_now['actual']} "
                f"→ {'命中' if settled_now['hit'] == '1' else '未中'}\n")
    if done:
        msg += f"累计:{nh}/{len(done)} 命中({nh / len(done) * 100:.0f}%)\n"
    if a.actual:
        in_pool = a.actual in pool
        verdict = "命中大底" if in_pool else "被杀号杀掉"
        msg += (f"盲测判决:{target}期实际 {a.actual} → {verdict}"
                f"(大底{len(pool)}注,随机基线{len(pool) / 10:.0f}%)\n")
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
