#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 取数工具：带重试、GBK 解码、JSON 容错。

设计要点（实测结论，勿随意改动）：
- push2.eastmoney.com 偶发 RemoteDisconnected，必须重试。
- 新浪 hq.sinajs.cn 必须带 Referer 且为 GBK。
- 腾讯 qt.gtimg.cn 为 GBK。
- 所有请求默认 12s 超时，最多 3 次指数退避重试。
"""
import json
import time
import urllib.request
import urllib.error

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

DEFAULT_HEADERS = {"User-Agent": UA}


def fetch(url, headers=None, enc="utf-8", retries=3, timeout=12, referer=None):
    """GET 一个 URL，返回 (status, text)。失败返回 (None, errmsg)。"""
    hdrs = dict(DEFAULT_HEADERS)
    if referer:
        hdrs["Referer"] = referer
    if headers:
        hdrs.update(headers)

    last_err = "unknown"
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, raw.decode(enc, "ignore")
        except urllib.error.HTTPError as e:
            last_err = "HTTP %s" % e.code
            # 4xx 不重试（除 429）
            if 400 <= e.code < 500 and e.code != 429:
                return None, last_err
        except Exception as e:
            last_err = "%s: %s" % (type(e).__name__, e)
        if attempt < retries - 1:
            time.sleep(0.6 * (2 ** attempt))
    return None, last_err


def fetch_json(url, headers=None, retries=3, timeout=12, referer=None):
    """GET 并解析 JSON。返回 (obj, None) 或 (None, errmsg)。"""
    st, body = fetch(url, headers=headers, retries=retries,
                     timeout=timeout, referer=referer)
    if st is None:
        return None, body
    try:
        return json.loads(body), None
    except Exception as e:
        return None, "JSON decode error: %s | head=%s" % (e, body[:160])
