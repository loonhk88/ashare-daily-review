#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 MCP 工具返回结果（spill 文本 / 原始 JSON）导入为 cache 文件。

用途：push2.eastmoney.com 被限流时，板块与个股资金流改由东财 MCP 连接器提供。
把工具返回值保存成文本文件后，用本脚本规范化到 tools/cache/。

用法:
    python3 import_mcp.py <spill.txt> --as industry
    python3 import_mcp.py <spill.txt> --as concept
    python3 import_mcp.py <spill.txt> --as fundflow
"""
import argparse
import json
import os
import re
import sys

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "cache")


def parse_loose(text):
    """容忍 Python repr 风格（工具输出常见）与标准 JSON。"""
    text = text.strip()
    # 去掉 spill 文件头部的说明行
    start = min([i for i in (text.find("["), text.find("{")) if i >= 0] or [-1])
    if start > 0:
        text = text[start:]
    try:
        return json.loads(text)
    except Exception:
        pass
    # Python repr: True/False/None 与 json 不兼容
    fixed = re.sub(r"\bNone\b", "null", text)
    fixed = re.sub(r"\bTrue\b", "true", fixed)
    fixed = re.sub(r"\bFalse\b", "false", fixed)
    return json.loads(fixed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--as", dest="kind", required=True,
                    choices=["industry", "concept", "fundflow"])
    a = ap.parse_args()

    if not os.path.exists(a.src):
        print("源文件不存在: %s" % a.src, file=sys.stderr)
        return 1
    with open(a.src, encoding="utf-8") as fp:
        raw = fp.read()

    try:
        obj = parse_loose(raw)
    except Exception as e:
        print("解析失败: %s" % e, file=sys.stderr)
        return 1

    # 有些工具返回 {"data": [...]} 包一层
    if isinstance(obj, dict):
        for k in ("data", "result", "list", "items"):
            if isinstance(obj.get(k), list):
                obj = obj[k]
                break
    if not isinstance(obj, list):
        print("期望 list，实际 %s" % type(obj), file=sys.stderr)
        return 1

    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, "%s.json" % a.kind)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=1)
    print("[import] %s -> %s (%d 条)" % (a.kind, out, len(obj)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
