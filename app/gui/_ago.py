"""相对时间文案（接入页的探针/采集/向导三区共用，去重时抽出）。

原在 `app/gui/connect_page.py` 模块级，被 capture 区（L841）、probe 区
（L1347/1401）、工具向导区（L1816）三处共用。抽成独立模块后，接入页与
connect_probe mixin 都从这里 import——mixin 不能反向 import 接入页主模块
（会与 class ConnectPage 的组装形成循环导入），共用的叶子函数必须单独放。
"""

from __future__ import annotations

from .i18n import t
from ..time_util import parse_ts


def _ago_text(seconds: float) -> str:
    """秒数 → 人类可读「刚刚 / N 分钟前 / N 小时前 / N 天前」（zh 源串 key）。"""
    s = int(seconds)
    if s < 90:
        return t("刚刚")
    if s < 5400:
        return t("{n} 分钟前", n=max(1, s // 60))
    if s < 129600:
        return t("{n} 小时前", n=max(1, s // 3600))
    return t("{n} 天前", n=max(1, s // 86400))


def _ts_ago(ts: str) -> tuple[str, str]:
    """时间戳 → (相对文案, 绝对文案)。ISO → 与 now 的秒差 → _ago_text。

    相对时间（「2 天前」）做正文，绝对时间（「 10:00」）留给 tooltip，
    两者都不给用户看裸 ISO 串。解析失败给空串。
    """
    if not ts:
        return "", ""
    raw = str(ts)
    abs_text = raw[:16].replace("T", " ")
    from datetime import datetime, timezone

    from ..time_util import parse_ts

    dt = parse_ts(raw)
    if dt is None:  # 去重 R1：解析失败语义不变——给"刚刚"而不是裸 ISO 串
        return t("刚刚"), abs_text
    secs = max(0, (datetime.now(timezone.utc) - dt).total_seconds())
    return _ago_text(secs), abs_text
