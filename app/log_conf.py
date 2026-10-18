"""唯一 logging 配置入口（重构报告  SYS-1）。

全仓日志配置只允许走这里，禁止散落的 logging.basicConfig：
- main.py（GUI/headless 入口）
- daemon.py（headless 引擎入口）

口径：
- 默认 INFO，格式与历史各入口 basicConfig 完全一致（%(asctime)s %(name)s %(message)s），
  不改变现有日志可读性；
- 可选文件轮转（RotatingFileHandler，按字节 + 保留份数）；不传 log_file = 纯控制台；
- 幂等：已配置过 root handler 即短路，防多入口/重复 import 叠加重复输出。

    扩展（OBS-1）约定：结构化为 `logger.info("event", extra={"k": v})` + 统一 key 前缀，
    本模块提供 _fmt 时保留 %(name)s 便于按模块过滤。

线程异常兜底：配置时装上 `app/thread_util.install_thread_excepthook`——windowed
打包态（console=False）stderr 不存在，线程未捕获异常会被静默吞掉（
打包事故的教训：引擎进程活着、端口没起、日志零报错）。
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .thread_util import install_thread_excepthook

# 历史口径的格式串（main/daemon 两处原样）
_DEFAULT_FORMAT = "%(asctime)s %(name)s %(message)s"
_SETUP_ATTR = "_experientia_configured"

# 纵深防御：本项目自身不把密钥写进日志，但第三方库（httpx/uvicorn 等）
# 可能把请求头/URL 透传进日志。格式化阶段统一打码常见凭据形态，兜底防泄漏。
# 每条 = (正则, 替换串)：正则的 \1 组是要保留的标签/前缀，凭据本体落在替换里打码。
_REDACTED = "[REDACTED]"
_TOKEN = r"[^\s,;\"']+"  # 凭据本体：到空白/分隔符为止
_SECRET_PATTERNS = (
    # Authorization 头（可带 Bearer/自定义 scheme），整值打码
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*)(?:bearer\s+)?" + _TOKEN),
     r"\1" + _REDACTED),
    # 独立 Bearer token（非 authorization: 前缀场景）
    (re.compile(r"(?i)\b(bearer\s+)" + _TOKEN), r"\1" + _REDACTED),
    # key=value / key: value 形态的凭据
    (re.compile(r"(?i)\b((?:api[_-]?key|access[_-]?token|auth[_-]?token"
                r"|refresh[_-]?token|proxy[_-]?token|secret|token|password|passwd)"
                r"\s*[=:]\s*)" + _TOKEN), r"\1" + _REDACTED),
    # 裸 key= / key: 形态：hook 事件令牌以 ?key=<token> 附在
    # 上报 URL 上，不匹配上面任何一种 alternation，可漏进日志——补齐这一形态。
    (re.compile(r"(?i)\b((?:api[_-]?)?key)\s*[=:]\s*" + _TOKEN),
     r"\1" + _REDACTED),
    # OpenAI 风格裸密钥
    (re.compile(r"\b(sk-)[A-Za-z0-9_\-]{12,}"), r"\1" + _REDACTED),
)


def _mask_secrets(text: str) -> str:
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


class _MaskingFormatter(logging.Formatter):
    """在标准格式化结果之上做凭据打码（覆盖控制台 + 文件所有 handler）。"""

    def format(self, record: logging.LogRecord) -> str:
        return _mask_secrets(super().format(record))


def setup_logging(
    level: int = logging.INFO,
    *,
    log_file: str | Path | None = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """配置根 logger（幂等）。log_file 非空时同时挂控制台 + 轮转文件。

    三处入口在进程启动早期调用一次即可；重复调用（含 import 复用）不叠加 handler。
    """
    root = logging.getLogger()
    if getattr(root, _SETUP_ATTR, False):
        return
    fmt = _MaskingFormatter(_DEFAULT_FORMAT)

    if not log_file:
        h = logging.StreamHandler()
        h.setFormatter(fmt)
        root.addHandler(h)
    else:
        p = Path(log_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            str(p), maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    root.setLevel(level)
    setattr(root, _SETUP_ATTR, True)
    # 线程未捕获异常写进日志（幂等；windowed 打包态 stderr 不存在，见模块 docstring）
    install_thread_excepthook()
