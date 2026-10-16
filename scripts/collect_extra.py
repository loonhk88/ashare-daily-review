#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股每日复盘 · 扩展数据源采集（同花顺 + 东财数据中心）

纳入 5 个零鉴权公开端点（来源：simonlin1212/Vibe-Research 的端点评测，
均经本机实测可用，2026-10-16 验证）：

  1. ths_limit_up_pool   同花顺涨停揭秘 —— 涨停原因题材 / 板型 / 封板率 / 几板
  2. ths_hsgt_realtime   沪深股通分钟累计净买入（北向资金）
  3. em_suspensions      当日停复牌名单
  4. ipo_calendar        新股申购日历（沪深京）
  5. em_lockup_history   限售解禁（全市场，未来 N 天）

设计原则（与主采集器一致）：
  - 任一源失败只记录 note，不影响其他源
  - 不编造数据：拿不到就不写该字段
  - 全部纯标准库实现（urllib），不引入 pandas 等依赖

用法:
    python3 collect_extra.py 2026-10-16                    # 打印结果
    python3 collect_extra.py 2026-10-16 --merge data/x.json
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

missing = []


def note(item, why):
    missing.append({"item": item, "reason": why})


def http_json(url, headers=None, timeout=15, retries=3, enc="utf-8"):
    """GET 并解析 JSON，带重试。返回 (obj, err)。"""
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    last = "unknown"
    for i in range(retries):
        req = urllib.request.Request(url, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode(enc, "ignore")
            return json.loads(body), None
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
            if 400 <= e.code < 500 and e.code != 429:
                return None, last
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e)[:70])
        if i < retries - 1:
            import time
            time.sleep(0.8 * (i + 1))
    return None, last


# --------------------------------------------------------------- 1 涨停揭秘
def ths_limit_up_pool(date):
    """同花顺涨停揭秘：reason_type(题材归因) / limit_up_type(板型) /
    limit_up_suc_rate(封板成功率) / high_days(几天几板) / open_num(开板次数)。

    返回 {code: {...}}，用于并入东财涨停池（东财无「涨停原因」字段）。
    """
    ymd = date.replace("-", "")
    params = {
        "page": 1, "limit": 200,
        "field": ("199112,10,9001,330323,330324,330325,9002,330329,"
                  "133971,133970,1968584,3475914,9003,9004"),
        "filter": "HS,GEM2STAR", "order_field": "330324",
        "order_type": "0", "date": ymd,
    }
    url = ("https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?"
           + urllib.parse.urlencode(params))
    obj, err = http_json(url, headers={"Referer": "https://data.10jqka.com.cn/"},
                         timeout=20)
    if not obj:
        note("涨停原因(同花顺)", err)
        return {}
    if obj.get("status_code") not in (0, None) and obj.get("status_msg"):
        note("涨停原因(同花顺)", str(obj.get("status_msg"))[:60])
        return {}
    info = ((obj.get("data") or {}).get("info")) or []

    out = {}
    for it in info:
        code = str(it.get("code") or "")
        if not code:
            continue
        out[code] = {
            "reason": (it.get("reason_type") or "").strip(),
            "board_type": it.get("limit_up_type") or "",
            "seal_rate": it.get("limit_up_suc_rate"),
            "high_days": it.get("high_days") or "",
            "currency_value": it.get("currency_value"),
            "order_volume": it.get("order_volume"),
            "is_again": it.get("is_again_limit"),
            "order_amount": it.get("order_amount"),
        }
    return out


# --------------------------------------------------------------- 2 北向资金
def ths_hsgt_realtime():
    """沪深股通当日分钟累计净买入（亿元）。返回 {hgt, sgt, total, last_time}。"""
    obj, err = http_json("https://data.hexin.cn/market/hsgtApi/method/dayChart/",
                         headers={"Host": "data.hexin.cn",
                                  "Referer": "https://data.hexin.cn/"},
                         timeout=15)
    if not obj:
        note("北向资金(同花顺)", err)
        return None
    times = obj.get("time") or []
    hgt = obj.get("hgt") or []
    sgt = obj.get("sgt") or []
    if not times:
        note("北向资金(同花顺)", "返回无时间序列")
        return None

    def last(lst):
        return lst[len(times) - 1] if len(lst) >= len(times) else (lst[-1] if lst else None)

    h, s = last(hgt), last(sgt)
    total = None
    if h is not None and s is not None:
        total = round(h + s, 2)
    return {
        "last_time": times[-1],
        "hgt": h, "sgt": s, "total": total,
        "points": len(times),
        # 保留尾盘若干点，便于观察日内节奏
        "tail": [{"t": times[i], "hgt": hgt[i] if i < len(hgt) else None,
                  "sgt": sgt[i] if i < len(sgt) else None}
                 for i in range(max(0, len(times) - 6), len(times))],
    }


# --------------------------------------------------------------- 3 停复牌
def em_suspensions(date, timeout=20):
    """沪深京当日停复牌名单。

    表名 RPT_CUSTOM_SUSPEND_DATA_INTERFACE，源要求按日期过滤。
    注意区分「确实没有」与「请求被拒」：success=false 或 result=null 都视为失败。
    """
    filt = '(MARKET="全部")(DATETIME=\'%s\')' % date
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           "?reportName=RPT_CUSTOM_SUSPEND_DATA_INTERFACE&columns=ALL"
           "&pageSize=500&sortColumns=SUSPEND_START_DATE&sortTypes=-1"
           "&filter=%s" % urllib.parse.quote(filt))
    obj, err = http_json(url, headers={"Referer": "https://data.eastmoney.com/"},
                         timeout=timeout)
    if not obj:
        note("停复牌", err)
        return None
    if not obj.get("success") or obj.get("result") is None:
        note("停复牌", str(obj.get("message") or "result=null")[:60])
        return None
    rows = []
    for r in (obj["result"].get("data") or []):
        rows.append({
            "code": r.get("SECURITY_CODE"),
            "name": r.get("SECURITY_NAME_ABBR"),
            "market": r.get("TRADE_MARKET"),
            "start": str(r.get("SUSPEND_START_TIME") or "")[:16],
            "end": str(r.get("SUSPEND_END_TIME") or "")[:16],
            "expire": r.get("SUSPEND_EXPIRE"),
            "reason": r.get("SUSPEND_REASON"),
            "resume_date": str(r.get("PREDICT_RESUME_DATE") or "")[:10],
        })
    return rows


# --------------------------------------------------------------- 4 新股日历
def ipo_calendar(date, days=15):
    """新股申购日历（沪深京）。取 date 起未来 days 天内的排期。"""
    d1 = (dt.date.fromisoformat(date) + dt.timedelta(days=days)).isoformat()
    # 实测：日期必须为 'YYYY-MM-DD' 带引号，否则报 filter 格式错误
    filt = "(APPLY_DATE>='%s')(APPLY_DATE<='%s')" % (date, d1)
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           "?reportName=RPTA_APP_IPOAPPLY&columns=ALL&pageSize=100"
           "&sortColumns=APPLY_DATE&sortTypes=1&filter=%s"
           % urllib.parse.quote(filt))
    obj, err = http_json(url, headers={"Referer": "https://data.eastmoney.com/"},
                         timeout=20)
    if not obj:
        note("新股申购日历", err)
        return None
    if not obj.get("success") or obj.get("result") is None:
        note("新股申购日历", str(obj.get("message") or "result=null")[:60])
        return None
    lo, hi = date, (dt.date.fromisoformat(date) + dt.timedelta(days=days)).isoformat()
    rows = []
    for r in (obj["result"].get("data") or []):
        ad = str(r.get("APPLY_DATE") or "")[:10]
        if not ad or not (lo <= ad <= hi):
            continue
        rows.append({
            "code": r.get("SECURITY_CODE"),
            "name": r.get("SECURITY_NAME_ABBR") or r.get("SECURITY_NAME"),
            "apply_date": ad,
            "market": r.get("MARKET_TYPE_NEW") or r.get("TRADE_MARKET"),
            "price": r.get("ISSUE_PRICE"),
            "pe": r.get("ISSUE_PE_RATIO"),
            "online_date": str(r.get("ONLINE_ISSUE_DATE") or "")[:10],
            "listing_date": str(r.get("LISTING_DATE") or "")[:10],
        })
    rows.sort(key=lambda x: x["apply_date"])
    return rows


# --------------------------------------------------------------- 5 限售解禁
def em_lockup_history(date, days=30):
    """限售解禁：未来 days 天内到期的解禁（全市场）。

    表名 RPT_LIFT_STAGE（实测 RPT_LIFT_STAGE_NEW 不存在）。
    字段口径（参考 simonlin1212/Vibe-Research 的审计结论）：
      - CURRENT_FREE_SHARES = 本次实际可上市流通股数（万股）
      - TOTAL_RATIO         = 占总股本比例（源给小数，×100 转 %）
      - 不用 FREE_RATIO     = 那是「占流通股比例」，与占总股本分母不同，易误读
    """
    d1 = (dt.date.fromisoformat(date) + dt.timedelta(days=days)).isoformat()
    filt = "(FREE_DATE>='%s')(FREE_DATE<='%s')" % (date, d1)
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           "?reportName=RPT_LIFT_STAGE&columns=ALL&pageSize=500"
           "&sortColumns=FREE_DATE&sortTypes=1&filter=%s"
           % urllib.parse.quote(filt))
    obj, err = http_json(url, headers={"Referer": "https://data.eastmoney.com/"},
                         timeout=20)
    if not obj:
        note("限售解禁", err)
        return None
    if not obj.get("success") or obj.get("result") is None:
        note("限售解禁", str(obj.get("message") or "result=null")[:60])
        return None

    def num(v):
        try:
            f = float(v)
            return None if f != f else f
        except Exception:
            return None

    rows = []
    for r in (obj["result"].get("data") or []):
        ratio = num(r.get("TOTAL_RATIO"))
        rows.append({
            "code": r.get("SECURITY_CODE"),
            "name": r.get("SECURITY_NAME_ABBR"),
            "free_date": str(r.get("FREE_DATE") or "")[:10],
            "shares_10k": num(r.get("CURRENT_FREE_SHARES")),   # 万股
            "ratio_pct": None if ratio is None else round(ratio * 100, 4),
            "market_cap": num(r.get("LIFT_MARKET_CAP")),
            "holders": num(r.get("BATCH_HOLDER_NUM")),
            "type": r.get("FREE_SHARES_TYPE"),
        })
    rows.sort(key=lambda x: x["free_date"])
    return rows


# --------------------------------------------------------------- main
def collect(date):
    global missing
    missing = []
    out = {}

    print("  - 涨停原因(同花顺) ...", file=sys.stderr)
    reasons = ths_limit_up_pool(date)
    out["zt_reason"] = reasons
    print("      %s" % ("✓ %d 只" % len(reasons) if reasons else "✗ 无"), file=sys.stderr)

    print("  - 北向资金 ...", file=sys.stderr)
    hsgt = ths_hsgt_realtime()
    out["northbound"] = hsgt
    if hsgt:
        print("      沪股通 %s / 深股通 %s / 合计 %s 亿（%s）"
              % (hsgt["hgt"], hsgt["sgt"], hsgt["total"], hsgt["last_time"]),
              file=sys.stderr)

    print("  - 停复牌 ...", file=sys.stderr)
    susp = em_suspensions(date)
    out["suspensions"] = susp
    print("      %s" % ("✓ %d 只" % len(susp) if susp is not None else "✗"), file=sys.stderr)

    print("  - 新股申购日历 ...", file=sys.stderr)
    ipos = ipo_calendar(date)
    out["ipo_calendar"] = ipos
    print("      %s" % ("✓ %d 只" % len(ipos) if ipos is not None else "✗"), file=sys.stderr)

    print("  - 限售解禁 ...", file=sys.stderr)
    lock = em_lockup_history(date)
    out["lockup"] = lock
    print("      %s" % ("✓ %d 条" % len(lock) if lock is not None else "✗"), file=sys.stderr)

    out["missing"] = missing
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--merge", help="合并进 data JSON")
    a = ap.parse_args()

    data = collect(a.date)

    if a.merge:
        with open(a.merge, encoding="utf-8") as fp:
            d = json.load(fp)

        # 1) 涨停原因并入涨停池
        reasons = data.get("zt_reason") or {}
        hit = 0
        for r in (d.get("zt") or {}).get("list") or []:
            info = reasons.get(str(r.get("code")))
            if info:
                r["reason"] = info.get("reason") or None
                r["board_type"] = info.get("board_type") or None
                r["seal_rate"] = info.get("seal_rate")
                r["high_days_ths"] = info.get("high_days") or None
                hit += 1
            else:
                r.setdefault("reason", None)
        print("[extra] 涨停原因命中 %d/%d" % (hit, len((d.get("zt") or {}).get("list") or [])),
              file=sys.stderr)

        # 2) 其余四项整体并入
        for k in ("northbound", "suspensions", "ipo_calendar", "lockup"):
            if data.get(k) is not None:
                d[k] = data[k]

        # 3) 记录缺失
        for m in data.get("missing") or []:
            d.setdefault("missing", []).append(m)

        with open(a.merge, "w", encoding="utf-8") as fp:
            json.dump(d, fp, ensure_ascii=False, indent=1)
        print("[extra] 已合并进 %s" % a.merge, file=sys.stderr)

    if data.get("missing"):
        print("[extra] 缺失 %d 项:" % len(data["missing"]), file=sys.stderr)
        for m in data["missing"]:
            print("    ! %s -> %s" % (m["item"], m["reason"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
