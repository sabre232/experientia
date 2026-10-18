"""网络层共用设定：回环直连——系统代理不劫持本机/回环端点。

背景：httpx 默认 trust_env=True，会读取 HTTP_PROXY /
HTTPS_PROXY 与系统代理设置。明文 HTTP 经代理转发时，请求行被改写成绝对
URI，本机端点被劫持后上游收到的 path 变成
`/http://127.0.0.1:PORT/v1/chat/completions` 这种形态 —— 路由不匹配 → 404，
表现为"第一轮请求正常、第二轮就 404"的诡异故障（开着 Clash 之类系统代理
的机器上必现，且因代理探测时序而显得随机）。

mounts 里 pattern → None 表示该 pattern 不走代理（httpx 语义）。只列回环：
云端 endpoint 仍尊重用户代理（访问云端 API 常依赖它）。
"""

from __future__ import annotations

DIRECT_LOOPBACK = {
    "all://127.0.0.1": None,
    "all://localhost": None,
    "all://[::1]": None,
}
