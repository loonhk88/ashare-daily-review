#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 GitHub Contents API 上传文件（绕过被封的 git 协议）。

背景：本机 github.com 的 git 端点被网络阻断（TLS 中断/超时），
但 api.github.com 正常。故改用 REST Contents API 逐个提交文件。

用法:
    GH_TOKEN=ghp_xxx python3 api_push.py <owner> <repo> [--branch main]
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"

# 需要上传的文件（相对仓库根）；目录会被递归展开
INCLUDE_DIRS = ["assets", "reviews", "scripts", "data", ".github"]
INCLUDE_FILES = ["index.html", "README.md", "run.sh", "publish.sh",
                 ".gitignore", ".nojekyll"]
SKIP_NAMES = {"__pycache__", ".git", "tools", "node_modules"}
SKIP_EXT = {".pyc", ".pyo", ".log"}


def collect_files(root):
    out = []
    for name in INCLUDE_FILES:
        p = os.path.join(root, name)
        if os.path.isfile(p):
            out.append(name)
    for d in INCLUDE_DIRS:
        base = os.path.join(root, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in SKIP_NAMES]
            for fn in filenames:
                if fn in SKIP_NAMES or os.path.splitext(fn)[1] in SKIP_EXT:
                    continue
                full = os.path.join(dirpath, fn)
                out.append(os.path.relpath(full, root))
    return sorted(set(out))


def req(method, url, token, data=None):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, method=method)
    r.add_header("Authorization", "Bearer %s" % token)
    r.add_header("Accept", "application/vnd.github+json")
    r.add_header("User-Agent", "ashare-review-publisher")
    if body:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {"message": str(e)}
    except Exception as e:
        return None, {"message": "%s: %s" % (type(e).__name__, e)}


def get_sha(owner, repo, path, branch, token):
    url = "%s/repos/%s/%s/contents/%s?ref=%s" % (API, owner, repo, path, branch)
    st, d = req("GET", url, token)
    if st == 200 and isinstance(d, dict):
        return d.get("sha")
    return None


def put_file(owner, repo, path, branch, token, message):
    full = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", path)
    full = os.path.normpath(full)
    with open(full, "rb") as fp:
        raw = fp.read()
    payload = {
        "message": message,
        "content": base64.b64encode(raw).decode(),
        "branch": branch,
    }
    sha = get_sha(owner, repo, path, branch, token)
    if sha:
        payload["sha"] = sha
    url = "%s/repos/%s/%s/contents/%s" % (API, owner, repo, path)
    return req("PUT", url, token, payload)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("owner")
    ap.add_argument("repo")
    ap.add_argument("--branch", default="main")
    a = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("缺少 GH_TOKEN", file=sys.stderr)
        return 1

    root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    files = collect_files(root)
    print("待上传 %d 个文件" % len(files))

    ok = fail = 0
    for i, rel in enumerate(files, 1):
        msg = "Add %s" % rel
        for attempt in range(3):
            st, d = put_file(a.owner, a.repo, rel, a.branch, token, msg)
            if st in (200, 201):
                ok += 1
                print("  [%d/%d] ✓ %s" % (i, len(files), rel))
                break
            if st in (409, 422) and attempt == 0:
                time.sleep(1)      # 并发的 sha 冲突，重试
                continue
            if st is None:
                time.sleep(2)
                continue
            fail += 1
            print("  [%d/%d] ✗ %s -> HTTP %s %s"
                  % (i, len(files), rel, st, str(d.get("message"))[:70]))
            break
        time.sleep(0.15)           # 轻微限速，避免触发 abuse 检测

    print()
    print("完成: 成功 %d, 失败 %d" % (ok, fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
