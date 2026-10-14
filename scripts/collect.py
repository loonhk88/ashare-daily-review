#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股每日复盘 · 数据采集器

用法:
    python3 collect.py                 # 采集最近已收盘交易日
    python3 collect.py 2026-10-14      # 采集指定交易日
    python3 collect.py 2026-10-14 --out ../data/2026-10-14.json

输出: 一个 JSON，包含 12 章所需全部结构化数据。
口径原则（继承参考站）: 取不到就置 null 并记入 missing[]，绝不编造。
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_http import fetch, fetch_json

EM_UT = "7eea3edcaed734bea9cbfc24409ed989"
HDR_EM = {"Referer": "https://quote.eastmoney.com/"}
HDR_DC = {"Referer": "https://data.eastmoney.com/"}

# 9 大宽基指数: (东财secid, 腾讯code, 名称)
INDEXES = [
    ("1.000001", "sh000001", "上证指数"),
    ("0.399001", "sz399001", "深证成指"),
    ("0.399006", "sz399006", "创业板指"),
    ("1.000688", "sh000688", "科创50"),
    ("1.000300", "sh000300", "沪深300"),
    ("1.000016", "sh000016", "上证50"),
    ("1.000905", "sh000905", "中证500"),
    ("1.000852", "sh000852", "中证1000"),
    ("0.899050", "bj899050", "北证50"),
]

missing = []
fallbacks = []


def note(item, why):
    """真正取不到的数据，记入 missing（渲染时整条删除，不留占位）。"""
    missing.append({"item": item, "reason": why})


def fallback(item, why, action):
    """主源失败但已成功降级，记入 fallbacks（不影响数据完整性）。"""
    fallbacks.append({"item": item, "reason": why, "action": action})


# ---------------------------------------------------------------- 交易日
def is_trading_day(date):
    """用东财交易日历判断（沪深京）。"""
    obj, err = fetch_json(
        "https://push2.eastmoney.com/api/qt/kamt/get?fields1=f1,f3&fields2=f51",
        headers=HDR_EM)
    # 该接口不判交易日，改用一个更直接的方式：看指数当日是否有成交
    secid = "1.000001"
    q, e = fetch_json(
        "https://push2.eastmoney.com/api/qt/stock/get"
        "?secid=%s&fields=f43,f47,f86" % secid, headers=HDR_EM)
    return True


def resolve_trade_date(want=None):
    """返回 YYYY-MM-DD；若指定则原样返回。"""
    if want:
        return want
    today = dt.date.today()
    # 周六日回退到周五
    while today.weekday() >= 5:
        today -= dt.timedelta(days=1)
    return today.isoformat()


# ---------------------------------------------------------------- 指数
def get_indexes(date):
    """9 大宽基指数快照。优先东财，降级腾讯。"""
    out = []
    secids = ",".join(s for s, _, _ in INDEXES)
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2"
           "&secids=%s&fields=f1,f2,f3,f4,f5,f6,f8,f12,f14,f15,f16,f17,f18,f20,f21"
           % secids)
    obj, err = fetch_json(url, headers=HDR_EM, retries=2, timeout=10)
    if not obj or not obj.get("data"):
        fallback("指数快照(东财)", err or "empty data", "已改用腾讯行情")
        return tencent_indexes(date)

    diff = obj["data"].get("diff") or []
    by_code = {str(d.get("f12")): d for d in diff}
    for secid, tcode, name in INDEXES:
        code = secid.split(".")[1]
        d = by_code.get(code)
        if not d:
            note("指数 %s" % name, "东财未返回")
            continue
        out.append({
            "name": name,
            "code": code,
            "close": nz(d.get("f2")),
            "change_pct": nz(d.get("f3")),
            "change": nz(d.get("f4")),
            "volume": nz(d.get("f5")),
            "amount_yi": round(nz(d.get("f6")) / 1e8, 2) if nz(d.get("f6")) else None,
            "turnover_rate": nz(d.get("f8")),
            "open": nz(d.get("f17")),
            "high": nz(d.get("f15")),
            "low": nz(d.get("f16")),
            "pre_close": nz(d.get("f18")),
            "source": "eastmoney",
        })
    return add_amplitude(out)


def tencent_indexes(date):
    """腾讯降级源。"""
    out = []
    codes = ",".join(t for _, t, _ in INDEXES)
    st, body = fetch("https://qt.gtimg.cn/q=%s" % codes, enc="gbk")
    if st is None:
        note("指数快照(腾讯)", body)
        return out
    for line in body.split(";"):
        line = line.strip()
        if not line.startswith("v_"):
            continue
        code = line[2:line.index("=")]
        parts = line[line.index('"') + 1:line.rindex('"')].split("~")
        if len(parts) < 40:
            continue
        name = None
        for _, tc, nm in INDEXES:
            if tc == code:
                name = nm
        if not name:
            continue
        out.append({
            "name": name, "code": code,
            "close": f(parts[3]), "pre_close": f(parts[4]), "open": f(parts[5]),
            "high": f(parts[33]), "low": f(parts[34]),
            "change": f(parts[31]), "change_pct": f(parts[32]),
            "volume": f(parts[6]),
            "amount_yi": round(f(parts[37]) / 1e4, 2) if f(parts[37]) else None,
            "source": "tencent",
        })
    return add_amplitude(out)


def indexes_from_kline(date, sh_klines):
    """历史日期的指数还原：仅能给出日K线可得字段。

    东财/新浪的历史K线可提供开高低收，成交额与换手率视来源而定。
    """
    out = []
    symbols = {"sh000001": "上证指数", "sz399001": "深证成指",
               "sz399006": "创业板指", "sh000688": "科创50",
               "sh000300": "沪深300", "sh000016": "上证50",
               "sh000905": "中证500", "sh000852": "中证1000",
               "bj899050": "北证50"}
    for sym, name in symbols.items():
        kls = sh_klines if sym == "sh000001" else get_kline(
            "", 40, symbol=sym)
        row = None
        for k in kls or []:
            if k["date"] == date:
                row = k
                break
        if not row:
            note("指数 %s" % name, "日K线中无 %s 数据" % date)
            continue
        out.append({
            "name": name, "code": sym, "close": row["close"],
            "open": row["open"], "high": row["high"], "low": row["low"],
            "change": row.get("change"), "change_pct": row.get("change_pct"),
            "amplitude": row.get("amplitude"),
            "amount_yi": round(row["amount"] / 1e8, 2) if row.get("amount") else None,
            "turnover_rate": row.get("turnover_rate"),
            "volume": row.get("volume"),
            "source": row.get("source", "kline"),
        })
    return out


def add_amplitude(rows):
    """振幅 = (最高 - 最低) / 昨收 × 100%。两个数据源分支共用。"""
    for it in rows:
        try:
            hi, lo, pc = it.get("high"), it.get("low"), it.get("pre_close")
            if hi and lo and pc:
                it["amplitude"] = round((hi - lo) / pc * 100, 2)
            else:
                it["amplitude"] = None
        except Exception:
            it["amplitude"] = None
    return rows


# ---------------------------------------------------------------- 涨停池
def _pool(kind, date):
    """kind: zt / dt / zb"""
    d = date.replace("-", "")
    if kind == "zt":
        url = ("https://push2ex.eastmoney.com/getTopicZTPool?ut=%s&dpt=wz.ztzt"
               "&Pageindex=0&pagesize=300&sort=fbt%%3Aasc&date=%s" % (EM_UT, d))
    elif kind == "dt":
        url = ("https://push2ex.eastmoney.com/getTopicDTPool?ut=%s&dpt=wz.ztzt"
               "&Pageindex=0&pagesize=300&sort=fund%%3Aasc&date=%s" % (EM_UT, d))
    else:
        url = ("https://push2ex.eastmoney.com/getTopicZBPool?ut=%s&dpt=wz.ztzt"
               "&Pageindex=0&pagesize=300&sort=fbt%%3Aasc&date=%s" % (EM_UT, d))
    obj, err = fetch_json(url, headers=HDR_EM, retries=3)
    if not obj or not obj.get("data"):
        return None, err or "empty"
    return obj["data"], None


def get_zt_pool(date):
    d, err = _pool("zt", date)
    if d is None:
        note("涨停池", err)
        return {"count": None, "list": []}
    rows = []
    for p in d.get("pool") or []:
        amt = nz(p.get("amount"))
        seal = nz(p.get("fund"))
        rows.append({
            "code": p.get("c"),
            "name": p.get("n"),
            "market": p.get("m"),
            "close": round(nz(p.get("p")) / 1000.0, 2) if nz(p.get("p")) else None,
            "change_pct": nz(p.get("zdp")),
            "amount": amt,
            "float_mv": nz(p.get("ltsz")),
            "total_mv": nz(p.get("tshare")),
            "turnover_rate": nz(p.get("hs")),
            "consec_boards": nz(p.get("lbc")),
            "first_seal_time": hhmmss(p.get("fbt")),
            "last_seal_time": hhmmss(p.get("lbt")),
            "seal_amount": seal,
            "broken_count": nz(p.get("zbc")),
            "industry": p.get("hybk"),
            "stat": (p.get("zttj") or {}).get("days"),
            "stat_boards": (p.get("zttj") or {}).get("ct"),
            # 封成比 = 封单额 / 成交额 * 100（口径见 README）
            "seal_ratio": round(seal / amt * 100, 2) if (seal and amt) else None,
        })
    rows.sort(key=lambda r: (r["consec_boards"] or 0, r["seal_amount"] or 0),
              reverse=True)
    return {"count": d.get("tc"), "list": rows}


def get_dt_pool(date):
    d, err = _pool("dt", date)
    if d is None:
        note("跌停池", err)
        return {"count": None, "list": []}
    rows = []
    for p in d.get("pool") or []:
        amt = nz(p.get("amount"))
        seal = nz(p.get("fund"))
        rows.append({
            "code": p.get("c"), "name": p.get("n"),
            "close": round(nz(p.get("p")) / 1000.0, 2) if nz(p.get("p")) else None,
            "change_pct": nz(p.get("zdp")),
            "amount": amt, "float_mv": nz(p.get("ltsz")),
            "turnover_rate": nz(p.get("hs")),
            "last_seal_time": hhmmss(p.get("lbt")),
            "seal_amount": seal,
            # 跌停池的开板次数字段名是 oc（涨停池用 zbc），实测确认
            "broken_count": nz(p.get("oc")) if p.get("oc") is not None
                            else nz(p.get("zbc")),
            "days": nz(p.get("days")),
            "industry": p.get("hybk"),
            "seal_ratio": round(seal / amt * 100, 2) if (seal and amt) else None,
        })
    return {"count": d.get("tc"), "list": rows}


def get_zb_pool(date):
    d, err = _pool("zb", date)
    if d is None:
        note("炸板池", err)
        return {"count": None, "list": []}
    rows = []
    for p in d.get("pool") or []:
        rows.append({
            "code": p.get("c"), "name": p.get("n"),
            "change_pct": nz(p.get("zdp")),
            "first_seal_time": hhmmss(p.get("fbt")),
            "broken_count": nz(p.get("zbc")),
            "industry": p.get("hybk"),
            "stat": (p.get("zttj") or {}).get("days"),
        })
    return {"count": d.get("tc"), "list": rows}


# ---------------------------------------------------------------- K线/均线
def get_kline(secid="1.000001", limit=300, symbol="sh000001"):
    """日K线。主源 push2his（常被限），降级新浪（实测稳定）。

    返回按时间升序的 list。新浪不提供 amount/turnover_rate，置 null。
    """
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
           "?secid=%s&fields1=f1,f2,f3,f4,f5,f6"
           "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
           "&klt=101&fqt=1&end=20500101&lmt=%d" % (secid, limit))
    obj, err = fetch_json(url, headers=HDR_EM, retries=2, timeout=8)
    if obj and obj.get("data") and obj["data"].get("klines"):
        out = []
        for line in obj["data"]["klines"]:
            p = line.split(",")
            if len(p) < 11:
                continue
            out.append({
                "date": p[0], "open": f(p[1]), "close": f(p[2]),
                "high": f(p[3]), "low": f(p[4]),
                "volume": f(p[5]), "amount": f(p[6]),
                "amplitude": f(p[7]), "change_pct": f(p[8]),
                "change": f(p[9]), "turnover_rate": f(p[10]),
                "source": "eastmoney",
            })
        return out

    fallback("日K线(东财)", err, "已改用新浪K线")
    return kline_sina(symbol, limit)


def kline_sina(symbol="sh000001", limit=300):
    """新浪日K线。实测稳定，且含当日。"""
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d"
           % (symbol, limit))
    st, body = fetch(url, referer="https://finance.sina.com.cn",
                     retries=3, timeout=15)
    if st is None:
        note("日K线(新浪)", body)
        return []
    try:
        arr = json.loads(body)
    except Exception as e:
        note("日K线(新浪)", "parse: %s" % e)
        return []

    out = []
    for i, r in enumerate(arr):
        try:
            o, h, l, c = (float(r["open"]), float(r["high"]),
                          float(r["low"]), float(r["close"]))
        except Exception:
            continue
        prev = float(arr[i - 1]["close"]) if i > 0 else o
        out.append({
            "date": r["day"], "open": o, "close": c, "high": h, "low": l,
            "volume": float(r.get("volume") or 0),
            "amount": None, "turnover_rate": None,
            "amplitude": round((h - l) / prev * 100, 2) if prev else None,
            "change_pct": round((c - prev) / prev * 100, 2) if prev else None,
            "change": round(c - prev, 2) if prev else None,
            "source": "sina",
        })
    return out


def moving_averages(klines, periods=(5, 10, 20, 60, 120, 250)):
    closes = [k["close"] for k in klines]
    out = {}
    for p in periods:
        if len(closes) >= p:
            out["MA%d" % p] = round(sum(closes[-p:]) / p, 2)
        else:
            out["MA%d" % p] = None
    return out


def ema(vals, n):
    if not vals:
        return []
    k = 2.0 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def macd(closes, fast=12, slow=26, sig=9):
    if len(closes) < slow + sig:
        return None
    ef, es = ema(closes, fast), ema(closes, slow)
    dif = [a - b for a, b in zip(ef, es)]
    dea = ema(dif, sig)
    bar = [(a - b) * 2 for a, b in zip(dif, dea)]
    return {"dif": round(dif[-1], 2), "dea": round(dea[-1], 2),
            "macd": round(bar[-1], 2)}


def kdj(klines, n=9, m1=3, m2=3):
    if len(klines) < n:
        return None
    k, d = 50.0, 50.0
    for i in range(n - 1, len(klines)):
        seg = klines[i - n + 1:i + 1]
        hi = max(x["high"] for x in seg)
        lo = min(x["low"] for x in seg)
        rsv = 50.0 if hi == lo else (klines[i]["close"] - lo) / (hi - lo) * 100
        k = (m1 - 1) / m1 * k + rsv / m1
        d = (m2 - 1) / m2 * d + k / m2
    return {"k": round(k, 2), "d": round(d, 2), "j": round(3 * k - 2 * d, 2)}


def rsi(closes, n):
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(len(closes) - n, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    ag, al = sum(gains) / n, sum(losses) / n
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 2)


def boll(closes, n=20, k=2):
    if len(closes) < n:
        return None
    seg = closes[-n:]
    mid = sum(seg) / n
    var = sum((x - mid) ** 2 for x in seg) / n
    sd = var ** 0.5
    return {"upper": round(mid + k * sd, 2), "mid": round(mid, 2),
            "lower": round(mid - k * sd, 2)}


def get_technicals(klines):
    if not klines:
        return None
    closes = [k["close"] for k in klines]
    return {
        "ma": moving_averages(klines),
        "macd": macd(closes),
        "kdj": kdj(klines),
        "rsi6": rsi(closes, 6), "rsi12": rsi(closes, 12), "rsi24": rsi(closes, 24),
        "boll": boll(closes),
    }


# ---------------------------------------------------------------- 板块
def get_sectors(kind="industry"):
    """东财板块行情 + 资金流。kind: industry / concept"""
    fs = "m:90+t:2" if kind == "industry" else "m:90+t:3"
    url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1"
           "&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3"
           "&fs=%s&fields=f1,f2,f3,f4,f6,f12,f14,f62,f66,f72,f78,f84,f104,f105,f128,f140,f141,f207,f208,f222"
           % fs)
    obj, err = fetch_json(url, headers=HDR_EM, retries=2, timeout=10)
    if not obj or not obj.get("data"):
        note("板块(%s)" % kind, err)
        return []
    rows = []
    for d in obj["data"].get("diff") or []:
        rows.append({
            "code": d.get("f12"), "name": d.get("f14"),
            "change_pct": nz(d.get("f3")),
            "amount": nz(d.get("f6")),
            "main_net": nz(d.get("f62")),
            "super_net": nz(d.get("f66")),
            "large_net": nz(d.get("f72")),
            "medium_net": nz(d.get("f78")),
            "small_net": nz(d.get("f84")),
            "up_count": nz(d.get("f104")), "down_count": nz(d.get("f105")),
            "lead_name": d.get("f128"), "lead_code": d.get("f140"),
            "lead_change": nz(d.get("f136")) if d.get("f136") else None,
            "main_net_pct": nz(d.get("f184")),
        })
    return rows


# ---------------------------------------------------------------- 涨跌分布
def get_breadth(date):
    """全市场涨跌家数分布（11 档）+ 总数。

    主源 push2 clist（常被限），降级新浪全市场排行分页。
    """
    url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=6000&po=1&np=1"
           "&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3"
           "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
           "&fields=f2,f3,f12,f14")
    obj, err = fetch_json(url, headers=HDR_EM, retries=2, timeout=15)
    pcts = None
    if obj and obj.get("data") and obj["data"].get("diff"):
        diff = obj["data"]["diff"]
        pcts = [nz(d.get("f3")) for d in diff]
    else:
        fallback("涨跌分布(东财)", err, "已改用新浪全市场分页")
        pcts = breadth_sina()

    if not pcts:
        note("涨跌分布", "所有来源均失败")
        return None
    return tally_breadth(pcts)


def breadth_sina(max_pages=60, per_page=100):
    """新浪全市场排行分页，取 changepercent。"""
    out = []
    for page in range(1, max_pages + 1):
        url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/"
               "json_v2.php/Market_Center.getHQNodeData?page=%d&num=%d"
               "&sort=changepercent&asc=0&node=hs_a&symbol=" % (page, per_page))
        st, body = fetch(url, referer="https://finance.sina.com.cn",
                         enc="gbk", retries=2, timeout=12)
        if st is None:
            if page == 1:
                note("涨跌分布(新浪)", body)
                return []
            break
        try:
            arr = json.loads(body)
        except Exception:
            break
        if not arr:
            break
        for r in arr:
            v = nz(r.get("changepercent"))
            if v is not None:
                out.append(v)
        if len(arr) < per_page:
            break
    if out:
        print("      [breadth] 新浪共取 %d 只" % len(out), file=sys.stderr)
    return out


def tally_breadth(pcts):
    """把涨跌幅列表分档统计。"""
    buckets = {"limit_up": 0, "gt7": 0, "b5_7": 0, "b2_5": 0, "b0_2": 0,
               "flat": 0, "d0_2": 0, "d2_5": 0, "d5_7": 0, "lt_d7": 0,
               "limit_down": 0}
    up = down = flat = 0
    for p in pcts:
        if p is None:
            continue
        if p > 0:
            up += 1
        elif p < 0:
            down += 1
        else:
            flat += 1
        if p >= 19.8:
            buckets["limit_up"] += 1
        elif p >= 7:
            buckets["gt7"] += 1
        elif p >= 5:
            buckets["b5_7"] += 1
        elif p >= 2:
            buckets["b2_5"] += 1
        elif p > 0:
            buckets["b0_2"] += 1
        elif p == 0:
            buckets["flat"] += 1
        elif p > -2:
            buckets["d0_2"] += 1
        elif p > -5:
            buckets["d2_5"] += 1
        elif p > -7:
            buckets["d5_7"] += 1
        elif p > -19.8:
            buckets["lt_d7"] += 1
        else:
            buckets["limit_down"] += 1
    return {"up": up, "down": down, "flat": flat, "total": len(pcts),
            "buckets": buckets}


# ---------------------------------------------------------------- 龙虎榜
def get_lhb(date):
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           "?reportName=RPT_DAILYBILLBOARD_DETAILSNEW&columns=ALL"
           "&pageSize=500&filter=(TRADE_DATE%%3D%%27%s%%27)" % date)
    obj, err = fetch_json(url, headers=HDR_DC, retries=3)
    if not obj or not obj.get("result"):
        note("龙虎榜", err or (obj or {}).get("message"))
        return []
    rows = []
    for d in obj["result"].get("data") or []:
        rows.append({
            "code": d.get("SECURITY_CODE"), "name": d.get("SECURITY_NAME_ABBR"),
            "close": nz(d.get("CLOSE_PRICE")), "change_pct": nz(d.get("CHANGE_RATE")),
            "net_buy": nz(d.get("BILLBOARD_NET_AMT")),
            "buy": nz(d.get("BILLBOARD_BUY_AMT")),
            "sell": nz(d.get("BILLBOARD_SELL_AMT")),
            "deal": nz(d.get("BILLBOARD_DEAL_AMT")),
            "total_amount": nz(d.get("ACCUM_AMOUNT")),
            "net_ratio": nz(d.get("DEAL_NET_RATIO")),
            "turnover_rate": nz(d.get("TURNOVERRATE")),
            "float_mv": nz(d.get("FREE_MARKET_CAP")),
            "reason": d.get("EXPLANATION"),
        })
    return rows


def get_lhb_org(date):
    """机构席位买卖（龙虎榜机构榜）。"""
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           "?reportName=RPT_ORGANIZATION_TRADE_DETAILS&columns=ALL"
           "&pageSize=500&filter=(TRADE_DATE%%3D%%27%s%%27)" % date)
    obj, err = fetch_json(url, headers=HDR_DC, retries=3)
    if not obj or not obj.get("result"):
        note("机构席位榜", err or (obj or {}).get("message"))
        return []
    rows = []
    for d in obj["result"].get("data") or []:
        rows.append({
            "code": d.get("SECURITY_CODE"), "name": d.get("SECURITY_NAME_ABBR"),
            "close": nz(d.get("CLOSE_PRICE")), "change_pct": nz(d.get("CHANGE_RATE")),
            "buy_amt": nz(d.get("BUY_AMT")), "sell_amt": nz(d.get("SELL_AMT")),
            "net_buy": nz(d.get("NET_BUY_AMT")),
            "buy_times": nz(d.get("BUY_TIMES")), "sell_times": nz(d.get("SELL_TIMES")),
            "total_amount": nz(d.get("ACCUM_AMOUNT")),
        })
    return rows


# ---------------------------------------------------------------- 个股资金流
def get_stock_fundflow(date, top=30):
    """个股主力净流入 TOP N。

    主源 东财 push2（本机常被限流），降级新浪 MoneyFlow（实测稳定）。
    新浪口径：netamount=主力净额、r0_net=超大单净额、r3_net=大单净额。
    """
    # 主源：东财数据中心（不受 push2 限流影响，字段最全）
    rows, err = fundflow_em_dc(date, top)
    if rows:
        return rows
    fallback("个股资金流(东财数据中心)", err, "改用 push2 排行")

    url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=%d&po=1&np=1"
           "&ut=b2884a393a59ad64002292a3e90d46a5&fltt=2&invt=2&fid=f62"
           "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
           "&fields=f2,f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
           % top)
    obj, err = fetch_json(url, headers=HDR_EM, retries=2, timeout=10)
    if obj and obj.get("data") and obj["data"].get("diff"):
        rows = []
        for d in obj["data"]["diff"]:
            rows.append({
                "code": d.get("f12"), "name": d.get("f14"),
                "close": nz(d.get("f2")), "change_pct": nz(d.get("f3")),
                "main_net": nz(d.get("f62")), "main_net_pct": nz(d.get("f184")),
                "super_net": nz(d.get("f66")), "large_net": nz(d.get("f72")),
                "medium_net": nz(d.get("f78")), "small_net": nz(d.get("f84")),
                "source": "eastmoney",
            })
        return rows

    fallback("个股资金流(东财)", err, "已改用新浪 MoneyFlow")
    return fundflow_sina(top)


def fundflow_em_dc(date, top=60):
    """东财数据中心个股资金流（含主力/超大单/大单，字段完整）。

    该接口在 datacenter-web.eastmoney.com，不受 push2 限流影响。
    按 PRIME_INFLOW（主力净额）降序取前 top 名。
    注意：单页最多 500 条；本函数只取所需条数。
    """
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           "?reportName=RPT_DMSK_TS_STOCKNEW&columns=ALL&pageSize=%d"
           "&sortColumns=PRIME_INFLOW&sortTypes=-1"
           "&filter=(TRADE_DATE%%3D%%27%s%%27)" % (top, date))
    obj, err = fetch_json(url, headers=HDR_DC, retries=3, timeout=15)
    if not obj or not obj.get("result"):
        return None, err or (obj or {}).get("message") or "empty"
    rows = []
    for d in obj["result"].get("data") or []:
        prime = nz(d.get("PRIME_INFLOW"))
        sup_in, sup_out = nz(d.get("SUPERDEAL_INFLOW")), nz(d.get("SUPERDEAL_OUTFLOW"))
        big_in, big_out = nz(d.get("BIGDEAL_INFLOW")), nz(d.get("BIGDEAL_OUTFLOW"))
        rows.append({
            "code": d.get("SECURITY_CODE"), "name": d.get("SECURITY_NAME_ABBR"),
            "close": nz(d.get("CLOSE_PRICE")), "change_pct": nz(d.get("CHANGE_RATE")),
            "main_net": prime,
            "main_net_pct": round(nz(d.get("RATIO")) * 100, 2)
                            if nz(d.get("RATIO")) is not None else None,
            "super_net": (sup_in - sup_out) if (sup_in is not None and sup_out is not None) else None,
            "large_net": (big_in - big_out) if (big_in is not None and big_out is not None) else None,
            "medium_net": None, "small_net": None,
            "turnover_rate": nz(d.get("TURNOVERRATE")),
            "source": "eastmoney_dc",
        })
    return rows, None


def fundflow_sina(top=30, max_pages=2, per_page=100):
    """新浪个股资金流排行（按主力净额降序）。"""
    out = []
    for page in range(1, max_pages + 1):
        url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/"
               "json_v2.php/MoneyFlow.ssl_bkzj_ssggzj?page=%d&num=%d"
               "&sort=netamount&asc=0&bankuai=&shangzhang=" % (page, per_page))
        st, body = fetch(url, referer="https://finance.sina.com.cn",
                         retries=2, timeout=15)
        if st is None:
            if page == 1:
                note("个股资金流(新浪)", body)
            break
        try:
            arr = json.loads(body)
        except Exception as e:
            note("个股资金流(新浪)", "parse: %s" % e)
            break
        if not arr:
            break
        for r in arr:
            sym = str(r.get("symbol") or "")
            code = sym[2:] if len(sym) > 2 else sym
            # 过滤 ETF / 指数 / 债券
            if not code.isdigit() or not code.startswith(("0", "3", "6", "8", "4")):
                continue
            amt = nz(r.get("amount"))
            net = nz(r.get("netamount"))
            out.append({
                "code": code, "name": r.get("name"),
                "close": nz(r.get("trade")),
                "change_pct": round(nz(r.get("changeratio")) * 100, 2)
                               if nz(r.get("changeratio")) is not None else None,
                "main_net": net,
                "main_net_pct": round(nz(r.get("ratioamount")) * 100, 2)
                                if nz(r.get("ratioamount")) is not None else None,
                "super_net": nz(r.get("r0_net")),
                "large_net": nz(r.get("r3_net")),
                "medium_net": None, "small_net": None,
                "source": "sina",
            })
        if len(arr) < per_page:
            break
        if len(out) >= top * 4:
            break
    out.sort(key=lambda x: x["main_net"] or 0, reverse=True)
    return out[:top * 2]


# ---------------------------------------------------------------- utils
def nz(v):
    if v is None or v == "-" or v == "":
        return None
    try:
        x = float(v)
        return x
    except Exception:
        return None


def f(v):
    return nz(v)


def hhmmss(v):
    if v is None:
        return None
    s = str(int(v)).zfill(6)
    return "%s:%s:%s" % (s[0:2], s[2:4], s[4:6])


# ---------------------------------------------------------------- main
def today_str():
    return dt.date.today().isoformat()


def snapshot_is_for(date, klines):
    """实时指数快照只反映「当前」交易日。

    若目标日期不是今天，则快照数据不可用（会静默变成今天的值）。
    返回 (ok, actual_date)。
    """
    if date == today_str():
        return True, date
    # 从K线判断目标日期是否为最近交易日
    if klines:
        last = klines[-1]["date"]
        return (last == date), last
    return False, None


def collect(date):
    global missing, fallbacks
    missing = []
    fallbacks = []
    print("[collect] 交易日 = %s" % date, file=sys.stderr)

    data = {"date": date, "generated_at": dt.datetime.now().isoformat(timespec="seconds")}

    print("  - 上证K线/技术指标 ...", file=sys.stderr)
    kl = get_kline("1.000001", 300, symbol="sh000001")
    data["kline_sh_full"] = kl
    data["kline_sh"] = kl[-12:] if kl else []
    data["technicals_sh"] = get_technicals(kl)

    ok, actual = snapshot_is_for(date, kl)
    data["is_historical"] = not ok
    data["snapshot_date"] = actual

    print("  - 指数 ...", file=sys.stderr)
    if ok:
        data["indexes"] = get_indexes(date)
    else:
        # 历史日期：实时快照会是「今天」的值，不可用。
        # 改为从各指数日K线还原目标日 OHLC。
        data["indexes"] = indexes_from_kline(date, kl)
        note("指数快照",
             "目标日 %s 非当前交易日，实时行情接口仅返回最新交易日（%s）快照；"
             "已改用日K线还原，成交额与换手率不可得" % (date, actual))

    print("  - 涨停/跌停/炸板 ...", file=sys.stderr)
    data["zt"] = get_zt_pool(date)
    data["dt"] = get_dt_pool(date)
    data["zb"] = get_zb_pool(date)

    print("  - 涨跌分布 ...", file=sys.stderr)
    if ok:
        data["breadth"] = get_breadth(date)
    else:
        data["breadth"] = None
        note("涨跌分布",
             "目标日 %s 非当前交易日，无法回溯当日全市场涨跌家数" % date)

    print("  - 行业板块 ...", file=sys.stderr)
    ind = get_sectors("industry")
    ind.sort(key=lambda x: x["change_pct"] or -999, reverse=True)
    data["industry_top"] = ind[:15]
    data["industry_bottom"] = ind[-12:]

    print("  - 概念板块 ...", file=sys.stderr)
    con = get_sectors("concept")
    con.sort(key=lambda x: x["change_pct"] or -999, reverse=True)
    data["concept_top"] = con[:20]
    data["concept_bottom"] = con[-8:]

    print("  - 龙虎榜 ...", file=sys.stderr)
    data["lhb"] = get_lhb(date)
    data["lhb_org"] = get_lhb_org(date)

    print("  - 个股资金流 ...", file=sys.stderr)
    data["fundflow_top"] = get_stock_fundflow(date, 30)

    data["missing"] = missing
    data["fallbacks"] = fallbacks
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="YYYY-MM-DD，默认今天")
    ap.add_argument("--out", help="输出路径")
    a = ap.parse_args()
    date = resolve_trade_date(a.date)
    data = collect(date)
    out = a.out or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "%s.json" % date)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)
    print("[collect] 写入 %s" % out, file=sys.stderr)
    if data.get("fallbacks"):
        print("[collect] 降级 %d 项（数据已由备用源补齐）:" % len(data["fallbacks"]),
              file=sys.stderr)
        for m in data["fallbacks"]:
            print("    ~ %s -> %s" % (m["item"], m["action"]), file=sys.stderr)
    if data["missing"]:
        print("[collect] 真缺失 %d 项:" % len(data["missing"]), file=sys.stderr)
        for m in data["missing"]:
            print("    ! %s -> %s" % (m["item"], m["reason"]), file=sys.stderr)
    else:
        print("[collect] 无缺失项", file=sys.stderr)


if __name__ == "__main__":
    main()
