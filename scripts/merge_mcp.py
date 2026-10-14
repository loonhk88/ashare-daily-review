#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 MCP 连接器取到的板块/资金流数据合并进 collect.py 产出的 JSON。

背景：push2.eastmoney.com 在本机网络被限流，板块行情与个股资金流拿不到。
东财 MCP 连接器（本地 SQLite）可正常提供，故采用「脚本 + 连接器」混合取数。

用法:
    python3 merge_mcp.py data/2026-10-14.json --industry industry.json \
        --concept concept.json --fundflow fundflow.json

各 JSON 文件由 MCP 工具返回结果直接保存（本目录 tools/ 下有对应抓取说明）。
"""
import argparse
import json
import os
import sys


def load(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def normalize_sector(rows, kind):
    """MCP 板块字段 -> 统一结构。"""
    out = []
    for r in rows or []:
        out.append({
            "code": r.get("sector_code"),
            "name": r.get("sector_name"),
            "change_pct": r.get("change_pct"),
            "main_net": r.get("main_net_inflow"),
            "main_net_pct": r.get("main_net_pct"),
            "super_net": r.get("super_large_net"),
            "large_net": r.get("large_net"),
            "medium_net": r.get("medium_net"),
            "small_net": r.get("small_net"),
            "lead_name": r.get("lead_stock_name"),
            "lead_code": r.get("lead_stock_code"),
            "sector_type": kind,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--industry")
    ap.add_argument("--concept")
    ap.add_argument("--fundflow")
    a = ap.parse_args()

    if not os.path.exists(a.target):
        print("target JSON 不存在: %s" % a.target, file=sys.stderr)
        return 1
    with open(a.target, encoding="utf-8") as fp:
        data = json.load(fp)

    filled = []

    ind = load(a.industry)
    if ind:
        rows = normalize_sector(ind, "industry")
        rows.sort(key=lambda x: x["change_pct"] if x["change_pct"] is not None else -999,
                  reverse=True)
        data["industry_top"] = rows[:15]
        data["industry_bottom"] = rows[-12:]
        filled.append("行业板块 %d" % len(rows))

    con = load(a.concept)
    if con:
        rows = normalize_sector(con, "concept")
        rows.sort(key=lambda x: x["change_pct"] if x["change_pct"] is not None else -999,
                  reverse=True)
        data["concept_top"] = rows[:20]
        data["concept_bottom"] = rows[-8:]
        filled.append("概念板块 %d" % len(rows))

    ff = load(a.fundflow)
    if ff:
        data["fundflow_top"] = ff
        filled.append("个股资金流 %d" % len(ff))

    # 清掉已解决的缺失项
    resolved_kw = ["板块(industry)", "板块(concept)", "个股资金流"]
    if data.get("missing"):
        data["missing"] = [m for m in data["missing"]
                           if not any(k in m["item"] for k in resolved_kw)]

    with open(a.target, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)

    print("[merge] 已合并: %s" % (", ".join(filled) if filled else "无"))
    print("[merge] 剩余缺失 %d 项" % len(data.get("missing") or []))
    for m in data.get("missing") or []:
        print("    ! %s -> %s" % (m["item"], m["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
