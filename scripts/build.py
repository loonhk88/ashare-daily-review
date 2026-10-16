#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股每日复盘 · 页面构建器

读取 data/YYYY-MM-DD.json（含 analysis 段）→ 输出 reviews/YYYY-MM-DD.html
并重建 index.html 归档列表。

用法:
    python3 build.py 2026-10-14
    python3 build.py 2026-10-14 --all      # 重建所有已归档日期
"""
import argparse
import datetime as dt
import glob
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
REVIEWS = os.path.join(ROOT, "reviews")
ASSETS = os.path.join(ROOT, "assets")

WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


# ---------------------------------------------------------------- helpers
def boards_of(r):
    """返回 (连板高度, 显示文本)。

    东财涨停池有两个板数字段，语义不同，务必区分：

      lbc        = 连板数（当前连续涨停天数）
      zttj.a/b   = 「几天几板」中的 天数/板数（N 天内累计涨停次数）

    实测两者经常不一致：某只个股 13 天内涨停 9 次但今日是断板后重新首板，
    此时 lbc=1、zttj=13/9。参考站的口径是把 zttj 的「板数」作为连板高度
    （如澳弘电子 17 天 10 板列为最高标），本实现沿用该口径，

    但显示时若两者不一致一律标注为「N天M板」，避免把「累计板数」
    误读成「连续板数」。
    """
    sb = r.get("stat_boards")
    cb = r.get("consec_boards")
    days = r.get("stat")
    try:
        b = int(sb) if sb else int(cb or 1)
    except Exception:
        b = 1
    try:
        d = int(days) if days else None
    except Exception:
        d = None
    if d and d != b:
        return b, "%s天%s板" % (d, b)
    return b, "%s板" % b


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def n(v, d=2):
    """数字格式化（千分位）。"""
    if v is None:
        return "—"
    try:
        return "{:,.{p}f}".format(float(v), p=d)
    except Exception:
        return "—"


def yi(v, d=2):
    """元 -> 亿元。"""
    if v is None:
        return "—"
    try:
        return "{:,.{p}f}".format(float(v) / 1e8, p=d)
    except Exception:
        return "—"


def wan(v, d=2):
    """元 -> 万元。"""
    if v is None:
        return "—"
    try:
        return "{:,.{p}f}".format(float(v) / 1e4, p=d)
    except Exception:
        return "—"


def pct(v, d=2, sign=True):
    if v is None:
        return "—"
    try:
        x = float(v)
        s = "{:+,.{p}f}%".format(x, p=d) if sign else "{:,.{p}f}%".format(x, p=d)
        return s
    except Exception:
        return "—"


def cls(v):
    """红涨绿跌。"""
    if v is None:
        return "flat"
    try:
        x = float(v)
    except Exception:
        return "flat"
    return "up" if x > 0 else ("down" if x < 0 else "flat")


def pctc(v, d=2, sign=True):
    return '<span class="num %s">%s</span>' % (cls(v), pct(v, d, sign))


def intg(v):
    """连板数等整数字段：去掉小数尾巴。"""
    if v is None:
        return "—"
    try:
        x = float(v)
        return str(int(x)) if x == int(x) else ("%.1f" % x)
    except Exception:
        return "—"


def ncl(v, d=2):
    return '<span class="num %s">%s</span>' % (cls(v), n(v, d))


def yic(v, d=2):
    return '<span class="num %s">%s</span>' % (cls(v), yi(v, d))


def wd(date_str):
    try:
        d = dt.date.fromisoformat(date_str)
        return WEEKDAY[d.weekday()]
    except Exception:
        return ""


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


# ---------------------------------------------------------------- chapter 1
def ch1_summary(d, an):
    """一句话复盘 + 核心指标。"""
    idx = {i["name"]: i for i in d.get("indexes") or []}
    sh = idx.get("上证指数") or {}
    cyb = idx.get("创业板指") or {}
    b = d.get("breadth") or {}
    zt = (d.get("zt") or {}).get("count")
    dtt = (d.get("dt") or {}).get("count")
    zb = (d.get("zb") or {}).get("count")

    bi = idx.get("深证成指") or {}
    total = None
    if sh.get("amount_yi") and bi.get("amount_yi"):
        total = sh["amount_yi"] + bi["amount_yi"]

    ratio = None
    if zt and dtt:
        ratio = round(zt / dtt, 2)

    up_pct = None
    if b.get("total"):
        up_pct = round(b["up"] / b["total"] * 100, 2)

    h = ['<div class="card" id="c1">', '<h2><span class="n">1</span>一句话复盘</h2>']
    h.append('<p class="lead">%s</p>' % esc(an.get("one_line", "")))

    h.append('<div class="kpis">')
    h.append('<div class="kpi"><div class="k">上证指数</div><div class="v %s">%s</div>'
             '<div class="x">%s</div></div>'
             % (cls(sh.get("change_pct")), n(sh.get("close")),
                pct(sh.get("change_pct"))))
    if total:
        h.append('<div class="kpi"><div class="k">两市成交</div><div class="v">%s万亿</div>'
                 '<div class="x">沪 %s + 深 %s</div></div>'
                 % (n(total / 10000, 2), n(sh.get("amount_yi"), 0), n(bi.get("amount_yi"), 0)))
    if b:
        h.append('<div class="kpi up"><div class="k">上涨家数</div><div class="v">%s</div>'
                 '<div class="x">占比 %s%%</div></div>'
                 % (n(b["up"], 0), n(up_pct)))
        h.append('<div class="kpi down"><div class="k">下跌家数</div><div class="v">%s</div>'
                 '<div class="x">平盘 %s</div></div>' % (n(b["down"], 0), n(b.get("flat"), 0)))
    if zt is not None:
        h.append('<div class="kpi"><div class="k">涨停 / 跌停</div><div class="v">%s / %s</div>'
                 '<div class="x">比值 %s</div></div>' % (n(zt, 0), n(dtt, 0), n(ratio)))
    zl = (d.get("zt") or {}).get("list") or []
    if zl:
        # 最高连板只看「当前连续板数」(consec_boards)，
        # 不能用 stat_boards（那是 N 天内累计板数，会把 9 天 9 板误判为最高标）
        top = max(zl, key=lambda r: boards_of(r)[0])
        stat = top.get("stat")
        b, btxt = boards_of(top)
        h.append('<div class="kpi"><div class="k">最高连板</div><div class="v up">%s</div>'
                 '<div class="x" title="%s">%s</div></div>'
                 % (esc(btxt), esc(btxt), esc(top.get("name"))))
    h.append('</div>')

    if an.get("key_points"):
        h.append('<ul class="pt">')
        for p in an["key_points"]:
            h.append('<li>%s</li>' % p)
        h.append('</ul>')
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- chapter 2
def ch2_indexes(d, an):
    idxs = d.get("indexes") or []
    h = ['<div class="card" id="c2">', '<h2><span class="n">2</span>大盘指数深度分析</h2>']

    h.append('<h3 class="sub">指数全景</h3>')
    h.append('<div class="tw"><table><thead><tr>'
             '<th>指数</th><th class="num">收盘</th><th class="num">涨跌幅</th>'
             '<th class="num">开盘</th><th class="num">最高</th><th class="num">最低</th>'
             '<th class="num">振幅</th><th class="num">成交额(亿)</th></tr></thead><tbody>')
    srt = sorted(idxs, key=lambda x: (x.get("change_pct") if x.get("change_pct") is not None else -999),
                 reverse=True)
    for i in srt:
        h.append('<tr><td class="name">%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%s</td><td class="num">%s</td></tr>'
                 % (esc(i["name"]), n(i.get("close")), pctc(i.get("change_pct")),
                    n(i.get("open")), n(i.get("high")), n(i.get("low")),
                    pct(i.get("amplitude")), n(i.get("amount_yi"))))
    h.append('</tbody></table></div>')

    kl = d.get("kline_sh") or []
    if kl:
        h.append('<h3 class="sub">上证指数近 %d 个交易日</h3>' % len(kl))
        h.append('<div class="tw"><table><thead><tr>'
                 '<th>日期</th><th class="num">开盘</th><th class="num">最高</th>'
                 '<th class="num">最低</th><th class="num">收盘</th>'
                 '<th class="num">涨跌幅</th></tr></thead><tbody>')
        for k in kl:
            h.append('<tr><td class="name num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                     '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td></tr>'
                     % (k["date"], n(k.get("open")), n(k.get("high")),
                        n(k.get("low")), n(k.get("close")), pctc(k.get("change_pct"))))
        h.append('</tbody></table></div>')

    t = d.get("technicals_sh")
    if t:
        h.append('<h3 class="sub">均线系统（上证指数）</h3>')
        cur = None
        for i in idxs:
            if i["name"] == "上证指数":
                cur = i.get("close")
        h.append('<div class="tw"><table><thead><tr><th>均线</th><th class="num">点位</th>'
                 '<th class="num">与收盘价差</th><th>位置</th></tr></thead><tbody>')
        for k, v in (t.get("ma") or {}).items():
            if v is None:
                continue
            diff = (cur - v) if cur else None
            ddp = (diff / v * 100) if (diff is not None and v) else None
            h.append('<tr><td class="name">%s</td><td class="num">%s</td>'
                     '<td class="num %s">%s</td><td>%s</td></tr>'
                     % (k, n(v), cls(diff), ("%s (%s)" % (n(diff), pct(ddp))) if diff is not None else "—",
                        "收盘价在均线上方" if (diff or 0) > 0 else "收盘价在均线下方"))
        h.append('</tbody></table></div>')

        h.append('<h3 class="sub">技术指标（上证指数）</h3>')
        h.append('<div class="tw"><table><thead><tr><th>指标</th><th>数值</th><th>解读</th>'
                 '</tr></thead><tbody>')
        m = t.get("macd") or {}
        if m:
            h.append('<tr><td class="name">MACD</td><td class="num">DIF %s / DEA %s / 柱 %s</td>'
                     '<td>%s</td></tr>'
                     % (n(m.get("dif")), n(m.get("dea")), ncl(m.get("macd")),
                        "零轴下方" if (m.get("dif") or 0) < 0 else "零轴上方"))
        kd = t.get("kdj") or {}
        if kd:
            h.append('<tr><td class="name">KDJ</td><td class="num">K %s / D %s / J %s</td>'
                     '<td>%s</td></tr>'
                     % (n(kd.get("k")), n(kd.get("d")), n(kd.get("j")),
                        "超卖区" if (kd.get("j") or 50) < 20 else
                        ("超买区" if (kd.get("j") or 50) > 80 else "中性区间")))
        h.append('<tr><td class="name">RSI</td><td class="num">6日 %s / 12日 %s / 24日 %s</td>'
                 '<td>%s</td></tr>'
                 % (n(t.get("rsi6")), n(t.get("rsi12")), n(t.get("rsi24")),
                    "偏弱" if (t.get("rsi6") or 50) < 50 else "偏强"))
        bl = t.get("boll") or {}
        if bl:
            h.append('<tr><td class="name">BOLL</td><td class="num">上 %s / 中 %s / 下 %s</td>'
                     '<td>%s</td></tr>'
                     % (n(bl.get("upper")), n(bl.get("mid")), n(bl.get("lower")),
                        ("距下轨 %s" % n(((cur or 0) - bl["lower"]))) if cur else "—"))
        h.append('</tbody></table></div>')

    if an.get("index_reading"):
        h.append('<div class="note">%s</div>' % an["index_reading"])
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- chapter 3
def ch3_sentiment(d, an):
    b = d.get("breadth") or {}
    zt = (d.get("zt") or {})
    dtt = (d.get("dt") or {})
    zb = (d.get("zb") or {})
    h = ['<div class="card" id="c3">', '<h2><span class="n">3</span>市场情绪全景</h2>']

    score = an.get("sentiment_score")
    if score is not None:
        h.append('<div class="temp"><div class="temp-bar">'
                 '<div class="temp-pin" style="left:%s%%"></div></div>'
                 '<div class="temp-scale"><span>冰点</span><span>低迷</span><span>回暖</span>'
                 '<span>活跃</span><span>狂热</span></div>'
                 '<div class="temp-val">情绪读数 %s / 100</div></div>' % (score, score))

    up_pct = (b.get("up", 0) / b["total"] * 100) if b.get("total") else None
    dn_pct = (b.get("down", 0) / b["total"] * 100) if b.get("total") else None
    ratio = round(zt.get("count") / dtt["count"], 2) if (zt.get("count") and dtt.get("count")) else None
    zb_rate = None
    if zt.get("count") and zb.get("count") is not None:
        tot = zt["count"] + zb["count"]
        zb_rate = round(zb["count"] / tot * 100, 1) if tot else None

    if not b:
        h.append('<div class="note">本交易日的<b>全市场涨跌家数与涨跌幅分布无法回溯</b>'
                 '（实时行情接口仅返回最新交易日快照），该部分整条删除，'
                 '不以占位符标记、不编造。以下保留由涨跌停专题可得的指标。</div>')

    h.append('<div class="kpis">')
    if b:
        h.append('<div class="kpi up"><div class="k">上涨家数</div><div class="v">%s</div>'
                 '<div class="x">占比 %s%%</div></div>' % (n(b.get("up"), 0), n(up_pct)))
        h.append('<div class="kpi down"><div class="k">下跌家数</div><div class="v">%s</div>'
                 '<div class="x">占比 %s%%</div></div>' % (n(b.get("down"), 0), n(dn_pct)))
    h.append('<div class="kpi"><div class="k">涨停 / 跌停</div><div class="v">%s / %s</div>'
             '<div class="x">比值 %s</div></div>'
             % (n(zt.get("count"), 0), n(dtt.get("count"), 0), n(ratio)))
    h.append('<div class="kpi"><div class="k">炸板</div><div class="v">%s</div>'
             '<div class="x">炸板率 %s%%</div></div>'
             % (n(zb.get("count"), 0), n(zb_rate, 1)))
    h.append('</div>')

    if b.get("buckets"):
        bk = b["buckets"]
        # 注意：本表为「按涨跌幅区间」的统计口径，与第 4/5 章的
        # 「涨停专题」口径不同（专题已剔除新股/ST 等特殊规则），
        # 故首末两档命名为「涨停区间」「跌停区间」以示区分。
        rows = [
            ("涨停区间", bk.get("limit_up"), "up"),
            ("&gt;+7%", bk.get("gt7"), "up"),
            ("+5~7%", bk.get("b5_7"), "up"),
            ("+2~5%", bk.get("b2_5"), "up"),
            ("0~+2%", bk.get("b0_2"), "up"),
            ("平盘", bk.get("flat"), "flat"),
            ("0~-2%", bk.get("d0_2"), "down"),
            ("-2~-5%", bk.get("d2_5"), "down"),
            ("-5~-7%", bk.get("d5_7"), "down"),
            ("&lt;-7%", bk.get("lt_d7"), "down"),
            ("跌停区间", bk.get("limit_down"), "down"),
        ]
        mx = max([r[1] or 0 for r in rows] + [1])
        h.append('<h3 class="sub">涨跌幅分布（沪深京 A 股，共 %s 只）</h3>' % n(b.get("total"), 0))
        h.append('<div class="note">本表为<b>按涨跌幅区间统计</b>的口径：'
                 '「涨停区间」指涨幅达到该板块涨停幅度的个股（主板≥9.8%、双创≥19.8%、北交所≥29.8%），'
                 '<b>因无法逐一识别新股上市首日、ST 股（±5%）等特殊规则，数值与第 4 章「涨跌停专题」'
                 '（已剔除特殊情形）可能存在小幅差异</b>，请以专题口径为准。</div>')
        h.append('<div class="dist">')
        for lb, c, c2 in rows:
            w = (c or 0) / mx * 100
            color = {"up": "var(--up)", "down": "var(--down)",
                     "flat": "var(--flat)"}[c2]
            h.append('<div class="dist-row"><span class="lb">%s</span>'
                     '<span class="tr"><i style="width:%s%%;background:%s"></i></span>'
                     '<span class="ct">%s</span></div>' % (lb, w, color, n(c, 0)))
        h.append('</div>')

    # 连板梯队
    zl = zt.get("list") or []
    if zl:
        ladder = {}
        for r in zl:
            k = boards_of(r)[0]
            ladder.setdefault(k, []).append(r)
        h.append('<h3 class="sub">连板梯队</h3>')
        h.append('<div class="ladder">')
        for k in sorted(ladder.keys(), reverse=True):
            kk = intg(k)
            names = "、".join(
                ("%s（%s）" % (x["name"], boards_of(x)[1])
                 if boards_of(x)[1] != kk + "板" else x["name"])
                for x in ladder[k][:4])
            h.append('<div class="lad"><div class="h">%s板</div><div class="c">%d</div>'
                     '<div class="n" title="%s">%s</div></div>'
                     % (kk, len(ladder[k]), esc(names), esc(names)))
        h.append('</div>')

    if an.get("sentiment_reading"):
        h.append('<div class="note">%s</div>' % an["sentiment_reading"])
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- chapter 4
def ch4_zt(d, an):
    zt = d.get("zt") or {}
    rows = zt.get("list") or []
    h = ['<div class="card" id="c4">', '<h2><span class="n">4</span>涨停板与连板梯队</h2>']
    if not rows:
        h.append('<p>当日无涨停数据。</p></div>')
        return "\n".join(h)

    rows = sorted(rows, key=lambda r: (boards_of(r)[0], r.get("seal_amount") or 0),
                  reverse=True)
    h.append('<p>当日共 <b>%s</b> 只涨停，其中连板 <b>%s</b> 只、首板 <b>%s</b> 只。'
             '下表按连板高度与封单额排序，封成比 = 封单额 ÷ 成交额。'
             '<b>连板列采用「几天几板」口径</b>（N 天内累计涨停 M 次），'
             '与「连续涨停天数」不同，两者不一致时均已标注天数。</p>'
             % (n(zt.get("count"), 0),
                n(len([r for r in rows if boards_of(r)[0] > 1]), 0),
                n(len([r for r in rows if boards_of(r)[0] <= 1]), 0)))

    h.append('<div class="tw"><table><thead><tr>'
             '<th>#</th><th>个股</th><th class="num">收盘</th><th class="num">涨幅</th>'
             '<th class="num">连板</th><th class="num">首封时间</th>'
             '<th class="num">封单额(万)</th><th class="num">封成比</th>'
             '<th class="num">开板</th><th>行业</th></tr></thead><tbody>')
    for i, r in enumerate(rows[:80], 1):
        boards, board_txt = boards_of(r)
        h.append('<tr%s><td class="num">%d</td><td class="name">%s <span class="tag">%s</span></td>'
                 '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%s</td><td>%s</td></tr>'
                 % (" class=\"hl\"" if (boards or 0) >= 3 else "",
                    i, esc(r.get("name")), esc(r.get("code")),
                    n(r.get("close")), pctc(r.get("change_pct")), board_txt,
                    esc(r.get("first_seal_time") or "—"),
                    n(r.get("seal_amount") and r["seal_amount"] / 1e4),
                    n(r.get("seal_ratio")), n(r.get("broken_count"), 0),
                    esc(r.get("industry") or "—")))
    h.append('</tbody></table></div>')

    if len(rows) > 80:
        h.append('<div class="note">表格仅展示前 80 只（共 %d 只），完整数据见同目录 JSON。</div>'
                 % len(rows))
    if an.get("zt_reading"):
        h.append('<div class="note">%s</div>' % an["zt_reading"])
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- chapter 5
def ch5_dt(d, an):
    dt_ = d.get("dt") or {}
    rows = dt_.get("list") or []
    h = ['<div class="card" id="c5">', '<h2><span class="n">5</span>跌停股分析</h2>']
    if not rows:
        h.append('<p>当日无跌停数据。</p></div>')
        return "\n".join(h)

    h.append('<p>当日共 <b>%s</b> 只跌停。</p>' % n(dt_.get("count"), 0))
    h.append('<div class="tw"><table><thead><tr>'
             '<th>#</th><th>个股</th><th class="num">收盘</th><th class="num">跌幅</th>'
             '<th class="num">封单额(万)</th><th class="num">封成比</th>'
             '<th class="num">开板</th><th>行业</th></tr></thead><tbody>')
    for i, r in enumerate(rows, 1):
        h.append('<tr><td class="num">%d</td><td class="name">%s <span class="tag">%s</span></td>'
                 '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%s</td><td class="num">%s</td><td>%s</td></tr>'
                 % (i, esc(r.get("name")), esc(r.get("code")),
                    n(r.get("close")), pctc(r.get("change_pct")),
                    n(r.get("seal_amount") and r["seal_amount"] / 1e4),
                    n(r.get("seal_ratio")), n(r.get("broken_count"), 0),
                    esc(r.get("industry") or "—")))
    h.append('</tbody></table></div>')
    if an.get("dt_reading"):
        h.append('<div class="note">%s</div>' % an["dt_reading"])
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- sector table
def sector_table(rows, value_key="main_net"):
    h = ['<div class="tw"><table><thead><tr>'
         '<th>#</th><th>板块</th><th class="num">涨跌幅</th>'
         '<th class="num">主力净额(亿)</th><th>领涨股</th></tr></thead><tbody>']
    for i, r in enumerate(rows, 1):
        h.append('<tr><td class="num">%d</td><td class="name">%s</td>'
                 '<td class="num">%s</td><td class="num">%s</td><td>%s</td></tr>'
                 % (i, esc(r.get("name")), pctc(r.get("change_pct")),
                    yic(r.get(value_key)), esc(r.get("lead_name") or "—")))
    h.append('</tbody></table></div>')
    return "\n".join(h)


def bar_chart(rows, value_key="change_pct", n_items=10):
    if not rows:
        return ""
    sub = rows[:n_items]
    mx = max([abs(r.get(value_key) or 0) for r in sub] + [0.01])
    h = ['<div class="bars">']
    for r in sub:
        v = r.get(value_key) or 0
        w = abs(v) / mx * 100
        c = cls(v)
        h.append('<div class="bar"><span class="lb" title="%s">%s</span>'
                 '<span class="tr"><span class="fl %s" style="width:%.1f%%"></span></span>'
                 '<span class="vl %s">%s</span>'
                 '<span class="ex">%s</span></div>'
                 % (esc(r.get("name")), esc(r.get("name")), c, w, c, pct(v),
                    esc(r.get("lead_name") or "")))
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- chapter 6
def ch6_industry(d, an):
    top = d.get("industry_top") or []
    bot = d.get("industry_bottom") or []
    h = ['<div class="card" id="c6">', '<h2><span class="n">6</span>行业表现</h2>']
    if top:
        h.append('<h3 class="sub">领涨行业 TOP15</h3>')
        h.append(bar_chart(top, "change_pct", 15))
        h.append(sector_table(top))
    if bot:
        h.append('<h3 class="sub">领跌行业</h3>')
        h.append(bar_chart(list(reversed(bot)), "change_pct", 12))
        h.append(sector_table(list(reversed(bot))))
    if an.get("industry_reading"):
        h.append('<div class="note">%s</div>' % an["industry_reading"])
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- chapter 7
def ch7_concept(d, an):
    top = d.get("concept_top") or []
    bot = d.get("concept_bottom") or []
    h = ['<div class="card" id="c7">', '<h2><span class="n">7</span>概念题材热度榜</h2>']
    if top:
        h.append('<h3 class="sub">领涨概念 TOP20</h3>')
        h.append(bar_chart(top, "change_pct", 20))
        h.append(sector_table(top))
    if bot:
        h.append('<h3 class="sub">垫底概念</h3>')
        h.append(sector_table(list(reversed(bot))))
    if an.get("concept_reading"):
        h.append('<div class="note">%s</div>' % an["concept_reading"])
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- chapter 8
def ch8_fundflow(d, an):
    ff = d.get("fundflow_top") or []
    lhb = d.get("lhb") or []
    org = d.get("lhb_org") or []
    h = ['<div class="card" id="c8">', '<h2><span class="n">8</span>资金流向</h2>']

    if ff:
        h.append('<h3 class="sub">个股主力净流入 TOP20</h3>')
        has_break = any(r.get("super_net") is not None for r in ff)
        th = ('<th>#</th><th>个股</th><th class="num">收盘</th><th class="num">涨跌幅</th>'
              '<th class="num">主力净额(亿)</th>')
        if has_break:
            th += '<th class="num">超大单(亿)</th><th class="num">大单(亿)</th>'
        th += '<th class="num">换手率</th></tr>'
        h.append('<div class="tw"><table><thead><tr>' + th + '</thead><tbody>')
        for i, r in enumerate(ff[:20], 1):
            tds = ('<td class="num">%d</td><td class="name">%s <span class="tag">%s</span></td>'
                   '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                   % (i, esc(r.get("name")), esc(r.get("code")),
                      n(r.get("close")), pctc(r.get("change_pct")),
                      yic(r.get("main_net"))))
            if has_break:
                tds += ('<td class="num">%s</td><td class="num">%s</td>'
                        % (yic(r.get("super_net")), yic(r.get("large_net"))))
            tds += '<td class="num">%s</td>' % pct(r.get("turnover_rate"))
            h.append('<tr>%s</tr>' % tds)
        h.append('</tbody></table></div>')

    if org:
        buys = sorted([r for r in org if (r.get("net_buy") or 0) > 0],
                      key=lambda x: x["net_buy"], reverse=True)[:10]
        sells = sorted([r for r in org if (r.get("net_buy") or 0) < 0],
                       key=lambda x: x["net_buy"])[:10]
        h.append('<h3 class="sub">机构席位动向（龙虎榜机构榜，共 %d 条）</h3>' % len(org))
        h.append('<div class="cols">')
        if buys:
            h.append('<div><p><b>机构净买入 TOP10</b></p><div class="tw"><table><thead><tr>'
                     '<th>个股</th><th class="num">涨跌幅</th><th class="num">机构净额(万)</th>'
                     '</tr></thead><tbody>')
            for r in buys:
                h.append('<tr><td class="name">%s</td><td class="num">%s</td>'
                         '<td class="num">%s</td></tr>'
                         % (esc(r.get("name")), pctc(r.get("change_pct")),
                            n((r.get("net_buy") or 0) / 1e4)))
            h.append('</tbody></table></div></div>')
        if sells:
            h.append('<div><p><b>机构净卖出 TOP10</b></p><div class="tw"><table><thead><tr>'
                     '<th>个股</th><th class="num">涨跌幅</th><th class="num">机构净额(万)</th>'
                     '</tr></thead><tbody>')
            for r in sells:
                h.append('<tr><td class="name">%s</td><td class="num">%s</td>'
                         '<td class="num">%s</td></tr>'
                         % (esc(r.get("name")), pctc(r.get("change_pct")),
                            n((r.get("net_buy") or 0) / 1e4)))
            h.append('</tbody></table></div></div>')
        h.append('</div>')

    if lhb:
        h.append('<h3 class="sub">龙虎榜上榜个股（净买额 TOP15，共 %d 条）</h3>' % len(lhb))
        srt = sorted(lhb, key=lambda x: x.get("net_buy") or 0, reverse=True)[:15]
        h.append('<div class="tw"><table><thead><tr>'
                 '<th>个股</th><th class="num">涨跌幅</th><th class="num">净买额(万)</th>'
                 '<th class="num">成交额(亿)</th><th>上榜原因</th></tr></thead><tbody>')
        for r in srt:
            h.append('<tr><td class="name">%s</td><td class="num">%s</td>'
                     '<td class="num">%s</td><td class="num">%s</td><td>%s</td></tr>'
                     % (esc(r.get("name")), pctc(r.get("change_pct")),
                        n((r.get("net_buy") or 0) / 1e4), yi(r.get("total_amount")),
                        esc(r.get("reason") or "—")))
        h.append('</tbody></table></div>')

    if an.get("fund_reading"):
        h.append('<div class="note">%s</div>' % an["fund_reading"])
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- chapter 9
def ch9_news(d, an):
    news = an.get("news") or []
    h = ['<div class="card" id="c9">', '<h2><span class="n">9</span>消息面</h2>']
    if not news:
        h.append('<p>当日未采集到消息面数据。</p></div>')
        return "\n".join(h)
    good = [x for x in news if x.get("type") == "good"]
    bad = [x for x in news if x.get("type") == "bad"]
    other = [x for x in news if x.get("type") not in ("good", "bad")]
    for title, items, c2 in (("利多因素", good, "up"), ("利空 / 风险因素", bad, "down"),
                             ("其他", other, "flat")):
        if not items:
            continue
        h.append('<h3 class="sub">%s</h3><ul class="pt">' % title)
        for x in items:
            src = x.get("source")
            s = (' <span class="tag">%s</span>' % esc(src)) if src else ""
            h.append('<li><b>%s</b> —— %s%s</li>' % (esc(x.get("title", "")),
                                                     esc(x.get("detail", "")), s))
        h.append('</ul>')
    h.append('<div class="note">以上为公开财经媒体快讯，属<b>新闻线索性质</b>，'
             '非上市公司正式披露，未经独立核实；涉及公司重大事项的以正式公告为准。</div>')
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- chapter 10
def ch10_reading(d, an, date):
    h = ['<div class="card" id="c10">', '<h2><span class="n">10</span>复盘解读</h2>']
    if an.get("variant"):
        h.append('<h3 class="sub">变异认知（Variant Perception）</h3>')
        h.append('<p>%s</p>' % an["variant"])
    for sec in an.get("readings") or []:
        h.append('<h3 class="sub">%s</h3>' % esc(sec.get("title", "")))
        if sec.get("body"):
            h.append('<p>%s</p>' % sec["body"])
        if sec.get("points"):
            h.append('<ul class="pt">')
            for p in sec["points"]:
                h.append('<li>%s</li>' % p)
            h.append('</ul>')
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- chapter 11
def ch11_watch(d, an, date):
    h = ['<div class="card" id="c11">', '<h2><span class="n">11</span>次日观察清单</h2>']
    lv = an.get("levels") or []
    if lv:
        h.append('<h3 class="sub">关键价位（上证指数）</h3>')
        h.append('<div class="tw"><table><thead><tr><th>位置</th><th class="num">点位</th>'
                 '<th>含义</th></tr></thead><tbody>')
        for x in lv:
            h.append('<tr><td class="name">%s</td><td class="num">%s</td><td>%s</td></tr>'
                     % (esc(x.get("name")), n(x.get("value")), esc(x.get("note", ""))))
        h.append('</tbody></table></div>')
    if an.get("watch"):
        h.append('<h3 class="sub">重点跟踪方向</h3><ul class="pt">')
        for x in an["watch"]:
            h.append('<li>%s</li>' % x)
        h.append('</ul>')
    if an.get("playbook"):
        h.append('<h3 class="sub">操作框架建议</h3><ul class="pt">')
        for x in an["playbook"]:
            h.append('<li>%s</li>' % x)
        h.append('</ul>')
    h.append('<div class="note">以上为基于公开数据的<b>研究观点</b>，非投资建议。</div>')
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- chapter 12
def ch12_sources(d, an, date):
    h = ['<div class="card" id="c12">', '<h2><span class="n">12</span>数据来源与口径</h2>']
    src = an.get("sources") or []
    if src:
        h.append('<div class="tw"><table><thead><tr><th>数据项</th><th>来源</th>'
                 '<th>说明</th></tr></thead><tbody>')
        for x in src:
            h.append('<tr><td class="name">%s</td><td>%s</td><td>%s</td></tr>'
                     % (esc(x.get("item")), esc(x.get("source")), esc(x.get("note", ""))))
        h.append('</tbody></table></div>')

    h.append('<h3 class="sub">口径说明</h3>')
    h.append('<ul class="pt">')
    for x in (an.get("caliber") or []):
        h.append('<li>%s</li>' % x)
    h.append('<li><b>封成比</b> = 封单额 ÷ 当日成交额 × 100%，为本文计算口径，'
             '与部分行情软件的口径可能存在差异。</li>')
    h.append('</ul>')

    fb = d.get("fallbacks") or []
    if fb:
        h.append('<h3 class="sub">取数降级记录</h3><ul class="pt">')
        for x in fb:
            h.append('<li>%s：主源不可用，%s</li>' % (esc(x.get("item")), esc(x.get("action"))))
        h.append('</ul>')

    miss = d.get("missing") or []
    if miss:
        h.append('<h3 class="sub">本次未取到的数据项</h3>')
        h.append('<p>按「取不到即整条删除、不以标记占位、绝不编造」的原则，'
                 '以下条目已从报告中删除：</p><ul class="pt">')
        for x in miss:
            h.append('<li>%s（%s）</li>' % (esc(x.get("item")), esc(x.get("reason"))))
        h.append('</ul>')

    h.append('<div class="note">所有数字均来自公开数据接口，未做推算或补全。'
             '「复盘解读」「操作框架」等章节为基于公开数据的分析判断，非事实陈述。</div>')
    h.append('</div>')
    return "\n".join(h)


# ---------------------------------------------------------------- page
NAV = [("c1", "一句话复盘"), ("c2", "指数分析"), ("c3", "市场情绪"),
       ("c4", "涨停梯队"), ("c5", "跌停分析"), ("c6", "行业表现"),
       ("c7", "概念题材"), ("c8", "资金流向"), ("c9", "消息面"),
       ("c10", "复盘解读"), ("c11", "观察清单"), ("c12", "数据来源")]


def build_page(date, d, css_ver="1"):
    an = d.get("analysis") or {}
    idx = {i["name"]: i for i in d.get("indexes") or []}
    sh = idx.get("上证指数") or {}
    b = d.get("breadth") or {}
    zt = (d.get("zt") or {}).get("count")
    dtt = (d.get("dt") or {}).get("count")
    bi = idx.get("深证成指") or {}
    total = None
    if sh.get("amount_yi") and bi.get("amount_yi"):
        total = (sh["amount_yi"] + bi["amount_yi"]) / 10000

    title = "A股每日复盘 · %s（%s）" % (date, wd(date))
    parts = []
    parts.append('<!DOCTYPE html><html lang="zh-CN"><head>')
    parts.append('<meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    parts.append('<title>%s</title>' % esc(title))
    parts.append('<meta name="description" content="%s">' % esc(an.get("one_line", "")[:120]))
    parts.append('<link rel="stylesheet" href="../assets/style.css?v=%s">' % css_ver)
    parts.append('</head><body>')

    # hero
    parts.append('<div class="hero"><div class="hero-inner">')
    parts.append('<h2>%s</h2>' % esc(title))
    parts.append('<div class="date">数据截至 %s 收盘 ｜ 生成 %s</div>'
                 % (date, esc((d.get("generated_at") or "")[:16].replace("T", " "))))
    parts.append('<div class="hero-stats">')
    parts.append('<div class="hstat"><div class="k">上证指数</div>'
                 '<div class="v %s">%s</div><div class="x">%s</div></div>'
                 % (cls(sh.get("change_pct")), n(sh.get("close")),
                    pct(sh.get("change_pct"))))
    if total:
        parts.append('<div class="hstat"><div class="k">两市成交</div><div class="v">%s万亿</div>'
                     '<div class="x">沪 %s / 深 %s 亿</div></div>'
                     % (n(total), n(sh.get("amount_yi"), 0), n(bi.get("amount_yi"), 0)))
    if b:
        parts.append('<div class="hstat"><div class="k">涨 / 跌家数</div>'
                     '<div class="v">%s / %s</div><div class="x">共 %s 只</div></div>'
                     % (n(b["up"], 0), n(b["down"], 0), n(b.get("total"), 0)))
    if zt is not None:
        parts.append('<div class="hstat"><div class="k">涨停 / 跌停</div>'
                     '<div class="v">%s / %s</div><div class="x">比值 %s</div></div>'
                     % (n(zt, 0), n(dtt, 0),
                        n(round(zt / dtt, 2)) if dtt else "—"))
    parts.append('</div></div></div>')

    # nav
    parts.append('<nav class="nav"><div class="nav-inner">')
    parts.append('<a href="../index.html">← 归档</a>')
    for cid, nm in NAV:
        parts.append('<a href="#%s">%s</a>' % (cid, nm))
    parts.append('</div></nav>')

    parts.append('<div class="wrap">')
    parts.append(ch1_summary(d, an))
    parts.append(ch2_indexes(d, an))
    parts.append(ch3_sentiment(d, an))
    parts.append(ch4_zt(d, an))
    parts.append(ch5_dt(d, an))
    parts.append(ch6_industry(d, an))
    parts.append(ch7_concept(d, an))
    parts.append(ch8_fundflow(d, an))
    parts.append(ch9_news(d, an))
    parts.append(ch10_reading(d, an, date))
    parts.append(ch11_watch(d, an, date))
    parts.append(ch12_sources(d, an, date))
    parts.append('</div>')

    parts.append('<footer>'
                 '<div><b>A股每日复盘</b> · %s（%s）</div>'
                 '<div>数据来源：通达信 / 东方财富 / 腾讯行情 / 新浪财经</div>'
                 '<div><a href="../index.html">返回归档列表</a></div>'
                 '<div class="disc" style="max-width:820px;margin:14px auto 0;text-align:left">'
                 '免责声明：本站内容仅供研究参考，不构成个人投资建议。市场有风险，投资需谨慎。'
                 '所有数据来自公开数据接口，可能存在口径差异或延迟；分析判断类内容可能出错。'
                 '</div></footer>' % (date, wd(date)))

    parts.append('<button id="top" title="回到顶部">↑</button>')
    parts.append('<script src="../assets/app.js?v=%s"></script>' % css_ver)
    parts.append('</body></html>')
    return "\n".join(parts)


# ---------------------------------------------------------------- index
def build_index(dates, metas):
    parts = []
    parts.append('<!DOCTYPE html><html lang="zh-CN"><head>')
    parts.append('<meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    parts.append('<title>A股每日复盘 · 归档</title>')
    parts.append('<link rel="stylesheet" href="assets/style.css?v=1">')
    parts.append('</head><body>')

    parts.append('<div class="topbar"><div class="topbar-inner">'
                 '<div class="brand"><h1>A股每日复盘 · 归档</h1></div>'
                 '<div class="meta">数据来源：通达信 · 东方财富 · 腾讯行情 · 新浪财经<br>'
                 '涨红跌绿口径</div></div></div>')

    parts.append('<div class="hero"><div class="hero-inner">')
    parts.append('<h2>A股每日复盘 · 归档</h2>')
    parts.append('<div class="date">已归档 <b>%d</b> 篇 ｜ 模板化生成 ｜ 仅供研究参考</div>'
                 % len(dates))
    parts.append('<div class="hero-stats">')
    parts.append('<div class="hstat"><div class="k">归档篇数</div><div class="v">%d</div>'
                 '<div class="x">个交易日</div></div>' % len(dates))
    if dates:
        parts.append('<div class="hstat"><div class="k">最新复盘</div><div class="v">%s</div>'
                     '<div class="x">%s</div></div>' % (dates[0], wd(dates[0])))
    parts.append('</div></div></div>')

    parts.append('<div class="wrap">')
    parts.append('<div class="card"><h2><span class="n">·</span>复盘列表</h2>')
    if not dates:
        parts.append('<p>暂无复盘。</p>')
    else:
        parts.append('<div class="reviews">')
        for dt_ in dates:
            m = metas.get(dt_) or {}
            chips = []
            for c in (m.get("chips") or []):
                chips.append('<span class="chip %s">%s</span>' % (c.get("cls", ""), esc(c.get("text"))))
            parts.append('<a class="rev" href="reviews/%s.html">'
                         '<div class="hd"><span class="d">%s</span>'
                         '<span class="wd">%s</span></div>'
                         '<div class="ti">%s</div>'
                         '<div class="sm">%s</div>'
                         '<div class="chips">%s</div></a>'
                         % (dt_, dt_, wd(dt_), esc(m.get("title", "")),
                            esc(m.get("summary", "")), "".join(chips)))
        parts.append('</div>')
    parts.append('</div>')

    parts.append('<div class="card"><h2><span class="n">·</span>复盘方法与口径</h2>'
                 '<ul class="pt">'
                 '<li><b>确定交易日</b>：按沪深京交易日历确定，非交易日顺延至最近已收盘交易日。</li>'
                 '<li><b>取数</b>：指数行情、K线、技术指标取自东方财富 / 腾讯 / 新浪；'
                 '涨停·跌停·炸板明细取自东方财富涨跌停专题；'
                 '行业与概念板块、个股资金流、龙虎榜取自东方财富数据中心。</li>'
                 '<li><b>口径</b>：涨停 / 跌停以东财涨跌停专题为准；'
                 '连板数采用接口原始「几天几板」字段，不用「前一日+1」推算。</li>'
                 '<li><b>缺数处理</b>：查不到的数据一律整条删除，不以占位符标记，绝不编造；'
                 '主源不可用但已成功降级的，在第 12 章如实记录。</li>'
                 '</ul>'
                 '<div class="disc">本站内容仅供研究参考，不构成个人投资建议。'
                 '市场有风险，投资需谨慎。</div></div>')

    parts.append('</div>')
    parts.append('<footer>数据来自公开接口，可能存在口径差异或延迟。涨红跌绿口径。<br>'
                 '本站为纯静态站点，无外部依赖，可离线浏览。</footer>')
    parts.append('</body></html>')
    return "\n".join(parts)


# ---------------------------------------------------------------- meta for index
def make_meta(date, d):
    an = d.get("analysis") or {}
    idx = {i["name"]: i for i in d.get("indexes") or []}
    sh = idx.get("上证指数") or {}
    b = d.get("breadth") or {}
    zt = (d.get("zt") or {}).get("count")
    dtt = (d.get("dt") or {}).get("count")
    chips = []
    if sh.get("change_pct") is not None:
        chips.append({"text": "上证 %s" % pct(sh["change_pct"]), "cls": cls(sh["change_pct"])})
    if b:
        chips.append({"text": "涨%s / 跌%s" % (n(b["up"], 0), n(b["down"], 0)), "cls": ""})
    if zt is not None:
        chips.append({"text": "涨停 %s · 跌停 %s" % (n(zt, 0), n(dtt, 0)), "cls": ""})
    for t in (an.get("mainlines") or [])[:3]:
        chips.append({"text": t, "cls": "gold"})
    return {"title": an.get("index_title", an.get("one_line", "")[:40]),
            "summary": an.get("index_summary", an.get("one_line", "")[:160]),
            "chips": chips}


# ---------------------------------------------------------------- main
def build_one(date):
    src = os.path.join(DATA, "%s.json" % date)
    d = read_json(src)
    if not d:
        print("数据不存在: %s" % src, file=sys.stderr)
        return None
    # 合并人工/半自动撰写的分析段
    ana = read_json(os.path.join(DATA, "%s.analysis.json" % date))
    if ana:
        d["analysis"] = ana
    else:
        print("  [warn] 缺少 %s.analysis.json，第 1/9/10/11 章将为空白" % date,
              file=sys.stderr)
    os.makedirs(REVIEWS, exist_ok=True)
    out = os.path.join(REVIEWS, "%s.html" % date)
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(build_page(date, d))
    print("  [build] %s" % out)
    return d


def rebuild_index():
    dates, metas = [], {}
    for f in sorted(glob.glob(os.path.join(DATA, "*.json")), reverse=True):
        base = os.path.basename(f)[:-5]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", base):
            continue
        if not os.path.exists(os.path.join(REVIEWS, "%s.html" % base)):
            continue
        d = read_json(f, {})
        ana = read_json(os.path.join(DATA, "%s.analysis.json" % base))
        if ana:
            d["analysis"] = ana
        dates.append(base)
        metas[base] = make_meta(base, d)
    out = os.path.join(ROOT, "index.html")
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(build_index(dates, metas))
    print("  [build] %s（%d 篇）" % (out, len(dates)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    if a.all or not a.date:
        for f in sorted(glob.glob(os.path.join(DATA, "*.json")), reverse=True):
            base = os.path.basename(f)[:-5]
            if re.match(r"^\d{4}-\d{2}-\d{2}$", base):
                build_one(base)
    else:
        if not build_one(a.date):
            return 1
    rebuild_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())
