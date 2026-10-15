#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复盘分析辅助：一次性输出撰写 analysis.json 所需的全部输入。

用途：DSH 定时任务唤起会话后，运行本脚本即可拿到当日所有关键数据，
      供 AI 撰写 data/YYYY-MM-DD.analysis.json（第 1/9/10/11 章）。

用法:
    python3 analysis_input.py              # 最近交易日
    python3 analysis_input.py 2026-10-15   # 指定日期
"""
import argparse
import datetime as dt
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def wd(date):
    return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
        dt.date.fromisoformat(date).weekday()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?")
    a = ap.parse_args()

    date = a.date
    if not date:
        fs = sorted([os.path.basename(f)[:-5] for f in
                     __import__("glob").glob(os.path.join(BASE, "data", "*.json"))
                     if not f.endswith(".analysis.json")])
        if not fs:
            print("无数据文件", file=sys.stderr)
            return 1
        date = fs[-1]

    p = os.path.join(BASE, "data", "%s.json" % date)
    if not os.path.exists(p):
        print("数据文件不存在: %s" % p, file=sys.stderr)
        return 1
    d = json.load(open(p, encoding="utf-8"))

    L = []
    L.append("=" * 66)
    L.append(" 复盘分析输入 | %s（%s）" % (date, wd(date)))
    L.append("=" * 66)

    # ---------- 指数 ----------
    idx = {i["name"]: i for i in d.get("indexes") or []}
    L.append("\n## 1. 指数行情")
    for n in ["上证指数", "深证成指", "创业板指", "科创50", "沪深300",
              "上证50", "中证500", "中证1000", "北证50"]:
        i = idx.get(n)
        if not i:
            continue
        L.append("  %-8s 收盘 %10.2f  涨跌 %+6.2f%%  振幅 %s%%  成交 %s亿"
                 % (n, i["close"], i["change_pct"],
                    i.get("amplitude") or "-", i.get("amount_yi") or "-"))
    sh, bi = idx.get("上证指数"), idx.get("深证成指")
    if sh and bi and sh.get("amount_yi") and bi.get("amount_yi"):
        L.append("  两市成交: %.2f 万亿元" % ((sh["amount_yi"] + bi["amount_yi"]) / 10000))

    # ---------- 涨跌 ----------
    b = d.get("breadth")
    L.append("\n## 2. 市场宽度")
    if b:
        L.append("  上涨 %d / 下跌 %d / 平盘 %d（共 %d）"
                 % (b["up"], b["down"], b["flat"], b["total"]))
        L.append("  上涨占比 %.1f%%  下跌占比 %.1f%%"
                 % (b["up"] / b["total"] * 100, b["down"] / b["total"] * 100))
        bk = b.get("buckets") or {}
        L.append("  分布: 涨停%d >7%%%d 5-7%%%d 2-5%%%d 0-2%%%d | 平%d | "
                 "0~-2%%%d -2~-5%%%d -5~-7%%%d <-7%%%d 跌停%d"
                 % (bk.get("limit_up"), bk.get("gt7"), bk.get("b5_7"),
                    bk.get("b2_5"), bk.get("b0_2"), bk.get("flat"),
                    bk.get("d0_2"), bk.get("d2_5"), bk.get("d5_7"),
                    bk.get("lt_d7"), bk.get("limit_down")))
    else:
        L.append("  （无数据）")

    # ---------- 技术指标 ----------
    t = d.get("technicals_sh")
    L.append("\n## 3. 上证技术指标")
    if t:
        L.append("  均线: " + "  ".join("%s=%s" % (k, v)
                                       for k, v in (t.get("ma") or {}).items()))
        m = t.get("macd") or {}
        L.append("  MACD: DIF=%s DEA=%s 柱=%s" % (m.get("dif"), m.get("dea"), m.get("macd")))
        k = t.get("kdj") or {}
        L.append("  KDJ: K=%s D=%s J=%s" % (k.get("k"), k.get("d"), k.get("j")))
        L.append("  RSI: 6日=%s 12日=%s 24日=%s"
                 % (t.get("rsi6"), t.get("rsi12"), t.get("rsi24")))
        bl = t.get("boll") or {}
        L.append("  BOLL: 上=%s 中=%s 下=%s" % (bl.get("upper"), bl.get("mid"), bl.get("lower")))
        cur = (sh or {}).get("close")
        if cur and bl.get("lower"):
            L.append("  收盘距BOLL下轨: %.2f 点" % (cur - bl["lower"]))

    # ---------- 涨停 ----------
    zt, zb, dtp = d.get("zt") or {}, d.get("zb") or {}, d.get("dt") or {}
    L.append("\n## 4. 涨停 / 炸板 / 跌停")
    L.append("  涨停 %s 只 | 炸板 %s 只 | 跌停 %s 只"
             % (zt.get("count"), zb.get("count"), dtp.get("count")))
    zl = zt.get("list") or []
    if zl:
        from collections import Counter
        c = Counter(int(r.get("stat_boards") or r.get("consec_boards") or 1) for r in zl)
        L.append("  连板梯队（几天几板口径）:")
        for kk in sorted(c, reverse=True):
            names = [r["name"] for r in zl
                     if int(r.get("stat_boards") or r.get("consec_boards") or 1) == kk][:8]
            L.append("    %2d板 %2d只: %s" % (kk, c[kk], "、".join(names)))
        hi = Counter(r.get("industry") or "?" for r in zl)
        L.append("  涨停行业分布: " + "  ".join("%s%d" % (a, n) for a, n in hi.most_common(8)))
        L.append("  封成比<10的弱封: %d 只" % sum(1 for r in zl if (r.get("seal_ratio") or 99) < 10))
        L.append("  曾开板: %d 只" % sum(1 for r in zl if (r.get("broken_count") or 0) >= 1))
    dl = dtp.get("list") or []
    if dl:
        L.append("  跌停明细（前12）:")
        for r in dl[:12]:
            L.append("    %-8s %+7.2f%%  开板%s次  封单%.0f万  %s"
                     % (r["name"], r["change_pct"], r.get("broken_count") or 0,
                        (r.get("seal_amount") or 0) / 1e4, r.get("industry") or ""))

    # ---------- 行业 ----------
    L.append("\n## 5. 行业（涨幅排序）")
    for r in (d.get("industry_top") or [])[:15]:
        L.append("  ↑ %-10s %+6.2f%%  主力%+8.2f亿  领涨 %s"
                 % (r["name"], r["change_pct"] or 0, (r.get("main_net") or 0) / 1e8,
                    r.get("lead_name") or ""))
    for r in reversed((d.get("industry_bottom") or [])[-12:]):
        L.append("  ↓ %-10s %+6.2f%%  主力%+8.2f亿  领涨 %s"
                 % (r["name"], r["change_pct"] or 0, (r.get("main_net") or 0) / 1e8,
                    r.get("lead_name") or ""))

    # ---------- 概念 ----------
    L.append("\n## 6. 概念（涨幅排序）")
    for r in (d.get("concept_top") or [])[:20]:
        L.append("  ↑ %-14s %+6.2f%%  主力%+8.2f亿  领涨 %s"
                 % (r["name"], r["change_pct"] or 0, (r.get("main_net") or 0) / 1e8,
                    r.get("lead_name") or ""))
    L.append("  --- 垫底 ---")
    for r in reversed((d.get("concept_bottom") or [])[-8:]):
        L.append("  ↓ %-14s %+6.2f%%  主力%+8.2f亿"
                 % (r["name"], r["change_pct"] or 0, (r.get("main_net") or 0) / 1e8))

    # ---------- 资金流 ----------
    L.append("\n## 7. 个股主力净流入 TOP15")
    for r in (d.get("fundflow_top") or [])[:15]:
        L.append("  %-8s %+7.2f%%  主力%+8.2f亿  超大单%+8.2f亿  换手%s%%"
                 % (r["name"], r["change_pct"] or 0, (r.get("main_net") or 0) / 1e8,
                    (r.get("super_net") or 0) / 1e8, r.get("turnover_rate") or "-"))

    # ---------- 机构 ----------
    org = d.get("lhb_org") or []
    L.append("\n## 8. 机构席位（龙虎榜机构榜，共 %d 条）" % len(org))
    if org:
        L.append("  净买入 TOP8:")
        for r in sorted(org, key=lambda x: x.get("net_buy") or 0, reverse=True)[:8]:
            L.append("    %-8s %+7.2f%%  机构净买%+9.2f万"
                     % (r["name"], r.get("change_pct") or 0, (r.get("net_buy") or 0) / 1e4))
        L.append("  净卖出 TOP8:")
        for r in sorted(org, key=lambda x: x.get("net_buy") or 0)[:8]:
            L.append("    %-8s %+7.2f%%  机构净卖%+9.2f万"
                     % (r["name"], r.get("change_pct") or 0, (r.get("net_buy") or 0) / 1e4))

    # ---------- 龙虎榜 ----------
    lhb = d.get("lhb") or []
    if lhb:
        L.append("\n## 9. 龙虎榜净买 TOP10（共 %d 条）" % len(lhb))
        for r in sorted(lhb, key=lambda x: x.get("net_buy") or 0, reverse=True)[:10]:
            L.append("  %-8s %+7.2f%%  净买%+9.2f万  %s"
                     % (r["name"], r.get("change_pct") or 0, (r.get("net_buy") or 0) / 1e4,
                        (r.get("reason") or "")[:28]))

    # ---------- 缺失/降级 ----------
    L.append("\n## 10. 数据质量")
    fb = d.get("fallbacks") or []
    ms = d.get("missing") or []
    L.append("  降级 %d 项:" % len(fb))
    for x in fb:
        L.append("    ~ %s -> %s" % (x["item"], x["action"]))
    L.append("  缺失 %d 项:" % len(ms))
    for x in ms:
        L.append("    ! %s -> %s" % (x["item"], x["reason"][:60]))
    if not ms:
        L.append("    （无）")

    L.append("\n" + "=" * 66)
    L.append(" 以上为全部输入。请据此撰写 data/%s.analysis.json" % date)
    L.append(" 字段要求见 scripts/ANALYSIS_SPEC.md")
    L.append("=" * 66)

    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
