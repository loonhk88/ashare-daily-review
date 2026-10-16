#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 GitHub Git Data API 做「单次原子提交」（替代逐文件 Contents API）。

为什么需要它：
  原 api_push.py 用 Contents API 逐文件提交，28 个文件会产生 28 次 commit，
  每次 commit 都触发一次 GitHub Pages 构建 —— 直接击穿 legacy 构建配额
  （10 次/小时），导致 Pages 报 "Page build failed."（实测 2026-10-16）。

  本脚本改用 Git Data API：
    GET  /git/refs/heads/<branch>       取当前 commit
    GET  /git/commits/<sha>             取 base tree
    POST /git/blobs                     逐文件建 blob（不触发构建）
    POST /git/trees                     建一棵新树（一次）
    POST /git/commits                   建一个 commit（一次）
    PATCH /git/refs/heads/<branch>      更新分支引用
  → 只产生 1 次 commit、1 次 Pages 构建。

用法:
    GH_TOKEN=xxx python3 git_push.py loonhk88 ashare-daily-review
    GH_TOKEN=xxx python3 git_push.py ... --dry-run
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"

# 注意：不包含 .github/workflows —— 上传工作流需要 token 具备 workflow scope，
# 缺失时 GitHub 返回 404 导致整批提交失败；且工作流文件内的 ${{ }} 会被
# Jekyll(Liquid) 误解析。本站用 branch 模式部署，无需工作流文件。
INCLUDE_DIRS = ["assets", "reviews", "scripts", "data"]
INCLUDE_FILES = ["index.html", "README.md", "run.sh", "publish.sh", "run_daily.sh",
                 ".gitignore", ".nojekyll"]
SKIP_NAMES = {"__pycache__", ".git", "tools", "node_modules", "logs", "backups"}
SKIP_EXT = {".pyc", ".pyo", ".log"}


def req(method, url, token, data=None, timeout=60):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, method=method)
    r.add_header("Authorization", "Bearer %s" % token)
    r.add_header("Accept", "application/vnd.github+json")
    r.add_header("User-Agent", "ashare-review-publisher")
    if body:
        r.add_header("Content-Type", "application/json")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                raw = resp.read().decode() or "{}"
                return resp.status, json.loads(raw)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode() or "{}")
            except Exception:
                return e.code, {"message": str(e)}
        except Exception as e:
            if attempt == 2:
                return None, {"message": "%s: %s" % (type(e).__name__, e)}
            time.sleep(1.5 * (attempt + 1))
    return None, {"message": "unreachable"}


def collect(root):
    out = []
    for name in INCLUDE_FILES:
        if os.path.isfile(os.path.join(root, name)):
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
                out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("owner")
    ap.add_argument("repo")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("缺少 GH_TOKEN", file=sys.stderr)
        return 1

    root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    files = collect(root)
    print("待提交 %d 个文件（单次原子提交）" % len(files))
    if a.dry_run:
        for f in files:
            print("   ", f)
        return 0

    # 1) 当前分支指向的 commit
    st, ref = req("GET", "%s/repos/%s/%s/git/ref/heads/%s" % (API, a.owner, a.repo, a.branch), token)
    if st != 200:
        print("取分支引用失败: HTTP %s %s" % (st, ref.get("message")), file=sys.stderr)
        return 1
    base_commit = ref["object"]["sha"]
    print("  当前 commit: %s" % base_commit[:12])

    # 2) base tree
    st, commit = req("GET", "%s/repos/%s/%s/git/commits/%s" % (API, a.owner, a.repo, base_commit), token)
    if st != 200:
        print("取 commit 失败: %s" % commit.get("message"), file=sys.stderr)
        return 1
    base_tree = commit["tree"]["sha"]

    # 3) 逐文件建 blob（不触发构建）
    tree_items = []
    for i, rel in enumerate(files, 1):
        full = os.path.join(root, rel)
        with open(full, "rb") as fp:
            raw = fp.read()
        import base64
        st, blob = req("POST", "%s/repos/%s/%s/git/blobs" % (API, a.owner, a.repo), token,
                       {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        if st not in (200, 201):
            print("  [%d/%d] ✗ blob %s -> %s" % (i, len(files), rel, blob.get("message")), file=sys.stderr)
            return 1
        tree_items.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        if i % 10 == 0 or i == len(files):
            print("  [%d/%d] blob 已建" % (i, len(files)))

    # 4) 建新 tree
    st, tree = req("POST", "%s/repos/%s/%s/git/trees" % (API, a.owner, a.repo), token,
                   {"base_tree": base_tree, "tree": tree_items})
    if st not in (200, 201):
        print("建 tree 失败: %s" % tree.get("message"), file=sys.stderr)
        return 1
    print("  新 tree: %s" % tree["sha"][:12])

    # 5) 建 commit
    import datetime as dt
    msg = a.message or ("更新复盘 %s" % dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    st, newc = req("POST", "%s/repos/%s/%s/git/commits" % (API, a.owner, a.repo), token,
                   {"message": msg, "tree": tree["sha"], "parents": [base_commit]})
    if st not in (200, 201):
        print("建 commit 失败: %s" % newc.get("message"), file=sys.stderr)
        return 1
    print("  新 commit: %s" % newc["sha"][:12])

    # 6) 更新分支引用（一次 push → 一次 Pages 构建）
    st, upd = req("PATCH", "%s/repos/%s/%s/git/refs/heads/%s" % (API, a.owner, a.repo, a.branch), token,
                  {"sha": newc["sha"], "force": False})
    if st not in (200, 201):
        print("更新分支失败: %s" % upd.get("message"), file=sys.stderr)
        return 1

    print()
    print("✓ 单次提交完成（仅触发 1 次 Pages 构建）")
    print("  commit: %s" % newc["sha"][:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
