#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从东方财富本地 SQLite 提取指定交易日的板块数据。

背景：东财 push2 接口在本机被限流，MCP 连接器的 get_sector_list 只返回
「当前」快照。对于历史日期，改从连接器的本地库 sector_data.db 直读，
但必须先校验 meta.sector_updated 与目标日期一致，避免张冠李戴。

用法:
    python3 sector_from_db.py 2026-10-13
    python3 sector_from_db.py 2026-10-13 --merge data/2026-10-13.json
"""
import argparse
import json
import os
import sqlite3
import sys

DB = "/vol1/@appshare/dsh/dsh_home/Desktop/分析板块/sector_data.db"

FIELDS = ("sector_code,sector_name,sector_type,latest_index,change_pct,"
          "main_net_inflow,main_net_pct,super_large_net,large_net,"
          "medium_net,small_net,lead_stock_name,lead_stock_code")


def load(date):
    if not os.path.exists(DB):
        print("板块库不存在: %s" % DB, file=sys.stderr)
        return None
    con = sqlite3.connect(DB)
    meta = dict(con.execute("select key,value from meta").fetchall())
    updated = meta.get("sector_updated")
    if updated != date:
        print("!! 板块库日期为 %s，与目标 %s 不一致，拒绝使用" % (updated, date),
              file=sys.stderr)
        return None
    rows = con.execute(
        "select %s from sector_basic" % FIELDS).fetchall()
    cols = FIELDS.split(",")
    out = [dict(zip(cols, r)) for r in rows]
    con.close()
    return out


def to_sector(r):
    return {
        "code": r["sector_code"], "name": r["sector_name"],
        "change_pct": r["change_pct"], "main_net": r["main_net_inflow"],
        "main_net_pct": r["main_net_pct"],
        "super_net": r["super_large_net"], "large_net": r["large_net"],
        "medium_net": r["medium_net"], "small_net": r["small_net"],
        "lead_name": r["lead_stock_name"], "lead_code": r["lead_stock_code"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--merge")
    a = ap.parse_args()

    rows = load(a.date)
    if rows is None:
        return 1

    ind = sorted([to_sector(r) for r in rows if r["sector_type"] == "industry"],
                 key=lambda x: x["change_pct"] if x["change_pct"] is not None else -999,
                 reverse=True)
    con = sorted([to_sector(r) for r in rows if r["sector_type"] == "concept"],
                 key=lambda x: x["change_pct"] if x["change_pct"] is not None else -999,
                 reverse=True)
    print("[sector] %s: 行业 %d, 概念 %d" % (a.date, len(ind), len(con)))

    if a.merge:
        with open(a.merge, encoding="utf-8") as fp:
            d = json.load(fp)
        d["industry_top"] = ind[:15]
        d["industry_bottom"] = ind[-12:]
        d["concept_top"] = con[:20]
        d["concept_bottom"] = con[-8:]
        d["sector_date"] = a.date
        d["missing"] = [m for m in (d.get("missing") or [])
                        if "板块" not in m["item"]]
        with open(a.merge, "w", encoding="utf-8") as fp:
            json.dump(d, fp, ensure_ascii=False, indent=1)
        print("[sector] 已合并进 %s；剩余缺失 %d 项"
              % (a.merge, len(d["missing"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
