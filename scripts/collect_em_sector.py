#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行业/概念板块采集器（东财数据中心版）

替代原 MCP 连接器方案，实现全自动化无人值守。

背景：
  push2.eastmoney.com（板块行情主源）在本机被长期限流（RemoteDisconnected），
  原实现需人工调用 MCP 连接器补齐板块数据。现改用
  datacenter-web.eastmoney.com 的两个报表接口，不受限流影响：

    RPT_INDUSTRY_FUNDFLOW  -> 128 个行业板块
    RPT_CONCEPT_FUNDFLOW   -> 400 个概念板块

字段（比原 push2 更全）：
  NET_INFLOW          主力净额
  NET_INFLOW_RATIO    主力净占比(%)
  SUPERDEAL_NET       超大单净额
  BIGDEAL_NET         大单净额
  MIDDEAL_NET         中单净额
  SMALLDEAL_NET       小单净额
  MAX_NETINFLOW_SEC   领涨股（按主力净额口径）
  CHANGE_RATE         涨跌幅(%)

用法:
    python3 collect_em_sector.py 2026-10-14                    # 只看结果
    python3 collect_em_sector.py 2026-10-14 --merge data/x.json # 合并进 JSON
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_http import fetch_json

HDR_DC = {"Referer": "https://data.eastmoney.com/"}
BASE = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=%s&columns=ALL&pageSize=%d&sortColumns=NET_INFLOW&sortTypes=-1"
        "&filter=(TRADE_DATE%%3D%%27%s%%27)")

REPORTS = {
    "industry": ("RPT_INDUSTRY_FUNDFLOW", 300),
    "concept": ("RPT_CONCEPT_FUNDFLOW", 600),
}


def fetch_sector(kind, date):
    """返回板块列表（按主力净额降序）。失败返回 (None, err)。"""
    report, size = REPORTS[kind]
    url = BASE % (report, size, date)
    obj, err = fetch_json(url, headers=HDR_DC, retries=3, timeout=25)
    if not obj or not obj.get("result"):
        return None, err or (obj or {}).get("message") or "empty result"

    rows = []
    for d in obj["result"].get("data") or []:
        # 只保留目标交易日（接口可能混入其他日期）
        td = str(d.get("TRADE_DATE") or "")[:10]
        if td and td != date:
            continue
        rows.append({
            "code": d.get("BOARD_CODE"),
            "name": d.get("BOARD_NAME"),
            "change_pct": nz(d.get("CHANGE_RATE")),
            "main_net": nz(d.get("NET_INFLOW")),
            "main_net_pct": nz(d.get("NET_INFLOW_RATIO")),
            "super_net": nz(d.get("SUPERDEAL_NET")),
            "large_net": nz(d.get("BIGDEAL_NET")),
            "medium_net": nz(d.get("MIDDEAL_NET")),
            "small_net": nz(d.get("SMALLDEAL_NET")),
            "lead_name": d.get("MAX_NETINFLOW_SEC"),
            "lead_code": None,
        })
    if not rows:
        return None, "交易日 %s 无数据" % date
    rows.sort(key=lambda x: x["change_pct"] if x["change_pct"] is not None else -999,
              reverse=True)
    return rows, None


def nz(v):
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    if f != f:          # NaN
        return None
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--merge", help="合并进指定的 data JSON")
    a = ap.parse_args()

    result = {}
    errs = []
    for kind in ("industry", "concept"):
        rows, err = fetch_sector(kind, a.date)
        if rows is None:
            print("[sector] %-8s ✗ %s" % (kind, err), file=sys.stderr)
            errs.append((kind, err))
            continue
        result[kind] = rows
        print("[sector] %-8s ✓ %d 个板块" % (kind, len(rows)), file=sys.stderr)
        for r in rows[:3]:
            print("           %-12s %+6.2f%%  主力%+8.2f亿  %s"
                  % (r["name"], r["change_pct"] or 0,
                     (r["main_net"] or 0) / 1e8, r["lead_name"] or ""), file=sys.stderr)

    if a.merge and result:
        with open(a.merge, encoding="utf-8") as fp:
            d = json.load(fp)
        if "industry" in result:
            d["industry_top"] = result["industry"][:15]
            d["industry_bottom"] = result["industry"][-12:]
        if "concept" in result:
            d["concept_top"] = result["concept"][:20]
            d["concept_bottom"] = result["concept"][-8:]
        d["sector_source"] = "eastmoney_datacenter"
        # 清除已解决的缺失项
        d["missing"] = [m for m in (d.get("missing") or [])
                        if "板块" not in m["item"]]
        with open(a.merge, "w", encoding="utf-8") as fp:
            json.dump(d, fp, ensure_ascii=False, indent=1)
        print("[sector] 已合并进 %s（剩余缺失 %d 项）"
              % (a.merge, len(d["missing"])), file=sys.stderr)

    return 1 if errs and not result else 0


if __name__ == "__main__":
    sys.exit(main())
