"""无头 Chromium CDP 截图：对已加载页面的标签页拍一张 PNG（视口范围）。

前置：Chromium/Edge 已带 --remote-debugging-port=9222 --window-size=1200,800 启动，
并打开了目标 URL。本脚本只负责等页面稳定 + Page.captureScreenshot。

用法：uv run --with websocket-client python scripts/cdp_shot.py out.png [--wait 30]
"""
from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request

import websocket


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--cdp", default="127.0.0.1:9222")
    ap.add_argument("--wait", type=int, default=30,
                    help="等待页面渲染完成的秒数（重页面首启偏慢，留足余量）")
    a = ap.parse_args()

    host, port = a.cdp.split(":")
    targets = json.load(urllib.request.urlopen(
        f"http://{host}:{port}/json", timeout=10))
    pages = [t for t in targets
             if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not pages:
        raise SystemExit("没有可截图的 page 标签页")
    ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=60)

    _mid = 0

    def send(method, **params):
        nonlocal _mid
        _mid += 1
        ws.send(json.dumps({"id": _mid, "method": method, "params": params}))
        deadline = time.time() + 60
        while time.time() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("id") == _mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)

    send("Page.enable")
    time.sleep(a.wait)
    r = send("Page.captureScreenshot", format="png")
    with open(a.out, "wb") as f:
        f.write(base64.b64decode(r["data"]))
    print(f"已存 {a.out}")


if __name__ == "__main__":
    main()
