#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""强制 IPv4 优先（导入即生效）。

背景（2026-11-26 实测）：
  本机多个行情/API 域名（push2.eastmoney.com、vip.stock.finance.sina.com.cn、
  qt.gtimg.cn、api.github.com）的 DNS 均返回 IPv6 地址，但本机 IPv6 路由
  不通——IPv6 直连失败，IPv4 强制连接仅 0.008s。
  Python 默认按 getaddrinfo 顺序优先 IPv6，于是每次请求都要先等满 timeout
  才回退 IPv4：单页 30.2s，新浪分页 60 页 = 30 分钟，直接卡死采集。

用法：在任何发起网络请求的脚本最顶部 `import netfix` 即可。
"""
import socket

_orig = socket.getaddrinfo
_patched = False


def install():
    """全局强制 IPv4 优先（幂等）。"""
    global _patched
    if _patched:
        return
    def _ipv4_first(host, port, family=0, type=0, proto=0, flags=0):
        # 调用方明确要求 IPv6 时不干预
        if family == socket.AF_INET6:
            return _orig(host, port, family, type, proto, flags)
        try:
            res = _orig(host, port, socket.AF_INET, type, proto, flags)
            if res:
                return res
        except Exception:
            pass
        return _orig(host, port, family, type, proto, flags)
    socket.getaddrinfo = _ipv4_first
    _patched = True


install()
