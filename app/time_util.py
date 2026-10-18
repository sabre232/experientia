"""统一时间口径（去重 R1：全仓 19 处 `fromisoformat` 收口）。

背景
----
一九处调用点各自写了一遍「把外部时间戳变成熟 datetime」，并演化出至少 5 种
口径（`[:19]` 截断、`[:26]` 截断、`[:10]` 截断、`replace("Z","")`、`replace("Z",
"+00:00")`、完全不处理）。同形代码反复写是小事，真正的风险是**口径分叉**：

- 有的模块产出 aware datetime、有的产出 naive datetime，两边一比较直接
  `TypeError`（只在特定数据上炸，测试很难覆盖全）；
- 有的模块对带毫秒/微秒的输入会容、有的会抛 `ValueError`（取决于是否截断）；
- 「尾 Z 按 UTC」这条约定在各处靠字面量实现，漏写就静默变成本地时间。

统一规则
--------
1. **naive 一律按 UTC 解释**（全库既有约定，也是 naive 分支最多的写法）；
2. 输出统一为 `%Y-%m-%dT%H:%M:%SZ`（秒级，`utc_str`）；
3. 解析失败一律返回 `None` / 空串，由**调用方**决定失败语义
   （有的要 False、有的要 None、有的要跳过），本模块不替调用方做这个决定；
4. Python 3.11+ 的 `datetime.fromisoformat` 已原生支持尾 `Z` 与任意位小数秒，
   因此本模块**不做任何字符串截断**——以前那些截断是 3.11 之前的 workaround，
   现在既多余又会丢精度。requires-python >= 3.11 已锁。

对外只有四个函数：`parse_ts` / `utc_str` / `day_of` / `week_start`。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

__all__ = ["parse_ts", "utc_str", "day_of", "week_start"]

_ISO_OUT = "%Y-%m-%dT%H:%M:%SZ"

# base_jsonl 的既有判定沿用：< 1e12 视为秒级 epoch，否则视为毫秒级
_EPOCH_MS_BOUNDARY = 1e12


def parse_ts(value) -> datetime | None:
    """宽松解析时间戳 → **aware UTC** datetime；无法解析 → ``None``。

    接受的输入：
    - ``datetime``：naive 按 UTC，aware 转 UTC；
    - ``int`` / ``float``：epoch，秒或毫秒自动判定（沿用既有的 1e12 边界）；
    - ``str``：ISO 8601，尾 ``Z``、带 ``+08:00`` 偏移、裸 naive 都接受，
      小数秒位数不限（Python 3.11+ 原生能力）；
    - 其余类型走 ``str(value)`` 兜底；空串 / ``None`` → ``None``。

    注意：``bool`` 是 ``int`` 子类，被显式排除，避免 ``True`` 被当成 1 秒 epoch。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, bool):
        return None
    elif isinstance(value, (int, float)):
        v = float(value)
        if abs(v) < _EPOCH_MS_BOUNDARY:  # 秒级 → 毫秒级统一
            v *= 1000.0
        try:
            return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        # 兼容既有口径（原 base_jsonl._ts_to_iso）：纯数字 / 科学计数串按 epoch
        # 解释，不当 ISO 基本格式日期——"20260101" 若喂给 fromisoformat 会被
        # 吃成一个远古日期，这才是真正的坑。
        try:
            num = float(text)
        except ValueError:
            pass
        else:
            return parse_ts(num)
        try:
            # 3.11+：原生吃尾 Z 与任意位小数秒，不需要任何截断/替换
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utc_str(value) -> str:
    """任意可接受输入 → ``YYYY-MM-DDTHH:MM:SSZ``；无法解析 → 空串。

    秒级输出，天然丢弃微秒——这与原先各调用点 `[:19]` 截断的效果一致，
    但输入侧不再丢精度。
    """
    dt = parse_ts(value)
    return dt.strftime(_ISO_OUT) if dt is not None else ""


def day_of(value) -> str | None:
    """→ ``YYYY-MM-DD``；无法解析 → ``None``。

    取代原先各处 ``str(ts)[:10]`` 取日期前缀再拼的写法。
    """
    dt = parse_ts(value)
    return dt.date().isoformat() if dt is not None else None


def week_start(value) -> date | None:
    """该时刻所属**自然周起点**（周一）的日期；无法解析 → ``None``。

    取代原先分叉的两份实现：`store/growth.py` 的 `_week_of`（返回 str）与
    `distill/weekly_report.py` 的 `_week_start`（返回 datetime）。
    返回 `date`：需要字符串就自行 `.isoformat()`，需要 datetime 就自行
    `datetime.combine(...)`——避免本模块再替调用方选一种类型。
    """
    dt = parse_ts(value)
    if dt is None:
        return None
    d = dt.date()
    return d - timedelta(days=d.weekday())
