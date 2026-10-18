"""写入面红线守卫：产品不联网检查更新、不下载、不安装（AGENTS.md  / 方案  ⑥）。

这条红线此前只有人工确认，没有守卫——"人工确认过"和"改不坏"是两件事。
这里把它变成可证伪的三条：

1. `app/` 下能发起出网请求的文件只允许一个白名单（`semantic/model_dl.py`，
   首启拉 embedding 模型、流式校验 sha256）。多一个就红；
2. 白名单文件必须是**没接线**的：全项目没有别处 import 它。谁把它接上，
   红线就破了——这条测试会先红，逼人显式决定而不是悄悄联网；
3. 自动更新包（`app/updater/`）保持不存在，且没有任何模块 import 它。

回环 HTTP（127.0.0.1）不算出网，由 `tests/test_net_util.py` 单独守。
"""

from __future__ import annotations

import ast
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

# 唯一允许出网的模块（相对 app/ 的 posix 路径）
ALLOW_OUTBOUND = {"semantic/model_dl.py"}

# 出网调用的函数名（urllib / socket 侧）
OUTBOUND_FUNCS = {"urlopen", "urlretrieve", "create_connection"}
# 第三方 HTTP 客户端的模块名（`httpx.get(...)` 这种顶层调用）
HTTP_MODULES = {"requests", "httpx", "urllib3", "aiohttp"}
# 连接器/会话构造：这些类构造即出网（FTP/SMTP 构造时连接）或只为 HTTP 而存在
NET_MODULES = HTTP_MODULES | {"http.client", "ftplib", "smtplib",
                              "urllib.request", "asyncio"}
_CONNECTORS = {"HTTPConnection", "HTTPSConnection", "FTP",
               "SMTP", "SMTP_SSL", "Session", "ClientSession"}
# socket 对象的出网动作（构造不出网——本机 bind 探测是合法用法，见
# gui/api_client.py 的 local_api_listening；所以认变量不认构造）
_SOCKET_FACTORIES = {"socket.socket", "socket.create_connection",
                     "socket.fromfd", "socket.socketpair"}
_OUTBOUND_METHODS = {"connect", "connect_ex", "sendto", "sendmsg"}
# 外壳下载器：不 import 任何 HTTP 库也能出网
_DOWNLOADERS = {"curl", "wget"}
_SUBPROC_FUNCS = {"run", "call", "check_call", "check_output", "Popen"}


def _app_files() -> list[pathlib.Path]:
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in p.parts)


def _dotted(node: ast.AST) -> str:
    """Name / Attribute 链 → 点分名（`http.client` → "http.client"）。"""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _import_bindings(tree: ast.AST) -> dict[str, str]:
    """`from X import y [as z]` → {z: "X.y"}。

    from-import 后调用名 lookup 不到模块（`get(url)` 的 func 是裸 Name），
    必须回 import 表认亲—— H6 之前不认，红线被一行 import 绕过。
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _callee_target(func_node: ast.AST, bindings: dict[str, str]) -> str:
    """Call.func → 规范目标名：裸 Name 经 import 绑定解析（`socket` →
    "socket.socket"），Attribute 链直接点分。"""
    d = _dotted(func_node)
    if "." not in d and d in bindings:
        return bindings[d]
    return d


def _socket_var_names(tree: ast.AST, bindings: dict[str, str]) -> set[str]:
    """`x = socket.socket(...)` 的变量名集合。

    后续 `x.connect(...)` 才是出网动作。不能见 `.connect` 就报——Qt 信号槽
    的 `clicked.connect(...)` 满地都是，误报一次这个守卫就会被当成狼威放弃。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if _callee_target(node.value.func, bindings) not in _SOCKET_FACTORIES:
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                names.add(tgt.id)
    return names


def _first_arg_str(node: ast.Call) -> str:
    """第一个参数里的字面量（字符串本体或列表/元组首元素），拿不到返回空串。"""
    if not node.args:
        return ""
    a = node.args[0]
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        return a.value
    if isinstance(a, (ast.List, ast.Tuple)) and a.elts:
        e = a.elts[0]
        if isinstance(e, ast.Constant) and isinstance(e.value, str):
            return e.value
    return ""


def _outbound_calls(tree: ast.AST) -> set[str]:
    """找出像"发起出网请求"的调用名。

    覆盖形态（H6 补全；此前只认 `requests.get(...)` 属性调用与三个
    裸函数名，`from requests import get` 即可让整条红线静默失效）：
    - `mod.get/post/...(...)`：HTTP 客户端顶层调用；
    - `urlopen/urlretrieve/create_connection(...)`：裸名或属性；
    - 连接器/会话构造：`HTTPConnection()` / `FTP()` / `SMTP()` /
      `requests.Session()`，含 from-import 后的裸名；
    - socket 出网动作：`socket.socket(...)` 赋给的变量上 `.connect/.sendto`；
    - 外壳下载器：`subprocess.run(["curl", ...])` / `os.system("curl …")`。

    不报的：`socket.socket()` 裸构造（本机 bind 探测合法，
    `gui/api_client.py` 在用）、Qt 信号槽 `.connect`、非网络模块的同名方法。
    """
    found: set[str] = set()
    bindings = _import_bindings(tree)
    sock_vars = _socket_var_names(tree, bindings)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            attr = func.attr
            mod = _dotted(func.value)
            if attr in OUTBOUND_FUNCS:
                found.add(attr)
            elif (attr in {"get", "post", "put", "delete", "request", "stream"}
                  and isinstance(func.value, ast.Name)
                  and func.value.id in HTTP_MODULES):
                found.add(f"{func.value.id}.{attr}")
            elif attr in _CONNECTORS and mod in NET_MODULES:
                found.add(f"{mod}.{attr}")
            elif attr == "open_connection" and mod == "asyncio":
                found.add("asyncio.open_connection")
            elif (attr in _OUTBOUND_METHODS
                  and ((isinstance(func.value, ast.Name)
                        and func.value.id in sock_vars)
                       or (isinstance(func.value, ast.Call)
                           and _callee_target(func.value.func, bindings)
                           in _SOCKET_FACTORIES))):
                found.add(f"socket.{attr}")
            elif attr in _SUBPROC_FUNCS and mod == "subprocess":
                head = _first_arg_str(node).split()[0:1]
                if head and head[0] in _DOWNLOADERS:
                    found.add(f"subprocess.{attr}({head[0]})")
            elif attr in {"system", "popen"} and mod == "os":
                head = _first_arg_str(node).split()[0:1]
                if head and head[0] in _DOWNLOADERS:
                    found.add(f"os.{attr}({head[0]})")
        elif isinstance(func, ast.Name):
            if func.id in OUTBOUND_FUNCS:
                found.add(func.id)
                continue
            target = bindings.get(func.id, "")
            if "." in target:
                mod, _, name = target.rpartition(".")
                if mod in NET_MODULES and (name in _CONNECTORS
                                           or name in OUTBOUND_FUNCS
                                           or name in {"get", "post"}):
                    found.add(target)
    return found


def test_only_allowlisted_module_can_go_out():
    """白名单之外，app/ 里不许有任何出网调用点。"""
    offenders: dict[str, list[str]] = {}
    for path in _app_files():
        rel = path.relative_to(APP).as_posix()
        if rel in ALLOW_OUTBOUND:
            continue
        hits = _outbound_calls(ast.parse(path.read_text(encoding="utf-8")))
        if hits:
            offenders[rel] = sorted(hits)
    assert not offenders, f"这些文件会出网，但不在白名单：{offenders}"


def test_outbound_detector_catches_bypass_forms():
    """：检测器必须认出这些绕过形态。

    补检之前只认 `requests.get(...)` 属性调用——下面每一种写法都能让
    红线守卫全绿的同时真的联网。
    """
    forms = [
        "from requests import get\nget('http://x')\n",
        "from httpx import post\npost('http://x')\n",
        "from socket import socket\nsocket().connect(('h', 80))\n",
        "import socket\nsocket.socket().connect(('h', 80))\n",
        "import socket\ns = socket.socket()\ns.connect(('h', 80))\n",
        "import socket\ns = socket.create_connection(('h', 80))\n",
        "import asyncio\nasyncio.open_connection('h', 80)\n",
        "from http.client import HTTPConnection\nHTTPConnection('h')\n",
        "import http.client\nhttp.client.HTTPConnection('h')\n",
        "from ftplib import FTP\nFTP('h')\n",
        "from smtplib import SMTP\nSMTP('h')\n",
        "import requests\nrequests.Session()\n",
        "import aiohttp\naiohttp.ClientSession()\n",
        "import subprocess\nsubprocess.run(['curl', 'http://x'])\n",
        "import subprocess\nsubprocess.check_output('curl http://x', shell=True)\n",
        "import os\nos.system('curl http://x')\n",
        "import os\nos.popen('wget http://x')\n",
        "from urllib.request import urlopen\nurlopen('http://x')\n",
    ]
    for src in forms:
        hits = _outbound_calls(ast.parse(src))
        assert hits, f"漏检出网形态：{src!r}"


def test_outbound_detector_ignores_innocent_forms():
    """反向：正常代码不许被误报（否则守卫会被当成狼威放弃）。"""
    forms = [
        "import os\nos.path.join('a', 'b')\n",
        "from app.store.store import Store\nStore()\n",
        "self.api.get('/x')\n",
        "session.get('key')\n",
        "client.request('POST', 'x')\n",
        "import subprocess\nsubprocess.run(['git', 'status'])\n",
        "import os\nos.system('echo hi')\n",
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.bind(('127.0.0.1', 8101))\ns.close()\n",
        "from PySide6.QtCore import Signal\n"
        "btn.clicked.connect(lambda: None)\n",
        "sock = make_socket()\nsock.bind(('127.0.0.1', 0))\n",
        "from app.proxy import inject\ninject.estimate_tokens('x')\n",
    ]
    for src in forms:
        assert not _outbound_calls(ast.parse(src)), f"误报：{src!r}"


def test_allowlisted_downloader_is_sha256_pinned():
    """白名单的下载器必须"无校验和不下载"（源内容被替换就丢弃重下）。"""
    src = (APP / "semantic" / "model_dl.py").read_text(encoding="utf-8")
    digests = re.findall(r'["\']([0-9a-f]{64})["\']', src)
    assert digests, "下载器里找不到 sha256 摘要——校验和被绕过就等于允许装任意文件"


def test_allowlisted_downloader_is_not_wired():
    """白名单下载器保持"未接线"：接上它等于产品首启自动下载。

    这条不是洁癖——它会拦住"顺手加个自动下载模型"的改动，让那种决定
    必须走显式改红线，而不是混在某个功能提交里悄悄发生。
    """
    wired: list[str] = []
    for path in _app_files():
        if path.name == "model_dl.py":
            continue
        rel = path.relative_to(APP).as_posix()
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bmodel_dl\b", text):
            wired.append(rel)
    assert not wired, (
        f"有模块引用了下载器：{wired}。产品红线是不下载、不安装——"
        "如果确实要接，先改写入面红线与联网策略，并把本测试一起改，别只改代码。"
    )


def test_updater_package_stays_removed():
    """自动更新整块移除后不得复活。"""
    assert not (APP / "updater").exists(), "app/updater/ 又出现了"

    imported: list[str] = []
    for path in _app_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any("updater" in a.name for a in node.names):
                    imported.append(path.relative_to(APP).as_posix())
            elif isinstance(node, ast.ImportFrom):
                if node.module and "updater" in node.module:
                    imported.append(path.relative_to(APP).as_posix())
    assert not imported, f"这些文件还在 import 更新模块：{imported}"
