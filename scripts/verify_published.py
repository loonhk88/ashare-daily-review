#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确认指定复盘页已成功发布到 GitHub（远端实际状态校验）。

api_push.py 逐文件上传时，个别文件（如需要 workflow scope 的工作流）
可能被跳过而返回非 0。本脚本以「远端仓库中是否存在该日期的复盘页、
且内容非空」作为发布成功的权威判据，避免误报失败。

用法:
    GH_TOKEN=xxx python3 verify_published.py 2026-10-14
    GH_OWNER=loonhk88 GH_REPO=ashare-daily-review python3 verify_published.py 2026-10-14
退出码: 0 = 已发布; 1 = 未发布/无法确认
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"


def get(url, token):
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer %s" % token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "ashare-review-verify")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {"message": str(e)}
    except Exception as e:
        return None, {"message": "%s: %s" % (type(e).__name__, e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--owner", default=os.environ.get("GH_OWNER", "loonhk88"))
    ap.add_argument("--repo", default=os.environ.get("GH_REPO", "ashare-daily-review"))
    ap.add_argument("--retries", type=int, default=3)
    a = ap.parse_args()

    token = os.environ.get("GH_TOKEN")
    if not token:
        print("[verify] 缺少 GH_TOKEN", file=sys.stderr)
        return 1

    path = "reviews/%s.html" % a.date
    url = "%s/repos/%s/%s/contents/%s" % (API, a.owner, a.repo, path)

    for i in range(a.retries):
        st, d = get(url, token)
        if st == 200:
            size = d.get("size") or 0
            if size > 10000:          # 正常复盘页 ~90KB
                print("[verify] ✓ 远端已存在 %s（%d bytes）" % (path, size))
                return 0
            print("[verify] ⚠ %s 存在但过小（%d bytes），可能未上传完整" % (path, size))
            return 1
        if st == 404:
            print("[verify] · 第 %d 次：远端暂无 %s" % (i + 1, path))
        else:
            print("[verify] · 第 %d 次：HTTP %s %s"
                  % (i + 1, st, str(d.get("message"))[:60]))
        if i < a.retries - 1:
            time.sleep(3)

    print("[verify] ✗ 未能在远端确认 %s" % path, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
