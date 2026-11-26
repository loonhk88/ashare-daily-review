#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书群机器人推送（A股复盘通知）

复用 ashare/config 中既有的飞书 webhook（与其它定时任务同一个群机器人）。

推送格式（用户指定）：
    📊 A股复盘 · 2026-10-14
    <一句话摘要>
    主线：PCB覆铜板 · 冰雪经济
    🔗 <页面链接>

用法:
    python3 notify_feishu.py --date 2026-10-14
    python3 notify_feishu.py --date 2026-10-14 --url https://... --dry-run
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

WEBHOOK = ("https://open.feishu.cn/open-apis/bot/v2/hook/"
           "46ae6c2f-da79-4aab-840a-f82dcab47e2a")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.expanduser("~/.ashare-review.env")
DEFAULT_SITE = "https://loonhk88.github.io/ashare-daily-review"


def load_env():
    """从 ~/.ashare-review.env 读取配置（可选覆盖 webhook）。"""
    cfg = {}
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip().strip('"').strip("'")
        except Exception as e:
            print("[notify] 读取 %s 失败: %s" % (ENV_FILE, e), file=sys.stderr)
    return cfg


def build_text(date, summary, mainlines, url):
    lines = ["📊 A股复盘 · %s" % date]
    if summary:
        lines.append(summary)
    if mainlines:
        lines.append("主线：%s" % " · ".join(mainlines))
    lines.append("🔗 %s" % url)
    return "\n".join(lines)


def send(webhook, text, retries=3, timeout=15):
    body = json.dumps({"msg_type": "text", "content": {"text": text}}).encode()
    last = None
    for i in range(retries):
        req = urllib.request.Request(
            webhook, data=body,
            headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read().decode() or "{}")
                if resp.get("code") in (0, None) or resp.get("StatusCode") == 0:
                    return True, resp
                last = resp
        except urllib.error.HTTPError as e:
            last = "HTTP %s %s" % (e.code, e.read()[:200])
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
    return False, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--url", default=None)
    ap.add_argument("--data", default=None, help="data/YYYY-MM-DD.json 路径")
    ap.add_argument("--dry-run", action="store_true", help="只打印不发送")
    a = ap.parse_args()

    # 链接
    url = a.url or "%s/reviews/%s.html" % (DEFAULT_SITE, a.date)

    # 摘要与主线：优先取 data JSON → analysis JSON
    summary, mainlines = "", []
    data_path = a.data or os.path.join(BASE, "data", "%s.json" % a.date)
    ana_path = os.path.join(BASE, "data", "%s.analysis.json" % a.date)
    for p in (ana_path, data_path):
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as fp:
                d = json.load(fp)
        except Exception:
            continue
        if not summary and d.get("index_summary"):
            summary = d["index_summary"]
        if not summary and d.get("one_line"):
            summary = d["one_line"]
        if not mainlines and d.get("mainlines"):
            mainlines = d["mainlines"]
        if summary and mainlines:
            break

    text = build_text(a.date, summary, mainlines, url)
    cfg = load_env()
    webhook = cfg.get("FEISHU_WEBHOOK") or WEBHOOK

    print("[notify] 将要推送的内容:")
    print("-" * 52)
    print(text)
    print("-" * 52)

    if a.dry_run:
        print("[notify] --dry-run，未实际发送")
        return 0

    ok, resp = send(webhook, text)
    if ok:
        print("[notify] ✓ 飞书推送成功")
        return 0
    print("[notify] ✗ 飞书推送失败: %s" % resp, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
