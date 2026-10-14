#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股交易日判断。

策略（按可靠性排序，任一成功即可判定）：
  1. 用上证指数日K线：若最新K线日期 == 目标日期，则是交易日（且已收盘）
  2. 用东财涨跌停专题：能取到该日期的涨停池数据，则是交易日
  3. 兜底：周一至周五视为交易日（不识别法定节假日，仅在 1、2 均失败时使用）

用法:
    python3 trading_calendar.py                # 判断今天
    python3 trading_calendar.py 2026-10-15     # 判断指定日期
    python3 trading_calendar.py --last         # 输出最近一个交易日
退出码: 0 = 是交易日; 1 = 不是
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_http import fetch, fetch_json

HDR_DC = {"Referer": "https://data.eastmoney.com/"}
EM_UT = "7eea3edcaed734bea9cbfc24409ed989"


def kline_has(date):
    """上证日K线是否包含该日期。"""
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol=sh000001&scale=240&ma=no&datalen=40")
    st, body = fetch(url, referer="https://finance.sina.com.cn", retries=2, timeout=15)
    if st is None:
        return None
    try:
        arr = json.loads(body)
    except Exception:
        return None
    days = {r.get("day") for r in arr}
    return date in days


def zt_pool_has(date):
    """东财涨停池是否返回该日期数据。"""
    d = date.replace("-", "")
    url = ("https://push2ex.eastmoney.com/getTopicZTPool?ut=%s&dpt=wz.ztzt"
           "&Pageindex=0&pagesize=3&sort=fbt%%3Aasc&date=%s" % (EM_UT, d))
    obj, err = fetch_json(url, headers=HDR_DC, retries=2, timeout=12)
    if not obj or not obj.get("data"):
        return None
    qdate = str(obj["data"].get("qdate") or "")
    if not qdate:
        return None
    q = "%s-%s-%s" % (qdate[:4], qdate[4:6], qdate[6:8])
    return q == date


def is_trading_day(date):
    """返回 (bool, 判定依据)。"""
    d = dt.date.fromisoformat(date)

    r = kline_has(date)
    if r is not None:
        return r, "上证日K线"

    r = zt_pool_has(date)
    if r is not None:
        return r, "东财涨跌停专题"

    # 兜底：仅按工作日判断（不识别法定节假日）
    return d.weekday() < 5, "工作日兜底（未识别节假日）"


def last_trading_day(upto=None):
    """返回 <= upto 的最近交易日（最多回溯 15 天）。"""
    d = dt.date.fromisoformat(upto) if upto else dt.date.today()
    for _ in range(15):
        ok, _src = is_trading_day(d.isoformat())
        if ok:
            return d.isoformat()
        d -= dt.timedelta(days=1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?")
    ap.add_argument("--last", action="store_true", help="输出最近一个交易日")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if a.last:
        d = last_trading_day(a.date)
        if d:
            print(d)
            return 0
        print("未找到交易日", file=sys.stderr)
        return 1

    date = a.date or dt.date.today().isoformat()
    ok, src = is_trading_day(date)
    if not a.quiet:
        wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
            dt.date.fromisoformat(date).weekday()]
        print("%s（%s）: %s  [依据: %s]"
              % (date, wd, "交易日" if ok else "非交易日", src),
              file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
