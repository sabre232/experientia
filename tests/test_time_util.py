"""app/time_util.py：全项目时间解析的收口点（去重 R1）。

钉两类契约：
1. 行为契约——尾 Z / 偏移 / naive / 毫秒微秒 / epoch 的解析口径，以及失败一律为 None；
2. 收口契约——业务层不许再各写一遍 `datetime.fromisoformat` 的字符串加工。
   第 2 条防的是"下次有人图省事又手写一遍 `ts[:19].replace('Z','+00:00')`"，
   口径会重新分叉，靠 review 记不住，靠测试。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from app.time_util import day_of, parse_ts, utc_str, week_start

ROOT = Path(__file__).resolve().parents[1]


class TestParseTs:
    def test_z_suffix_treated_as_utc(self):
        dt = parse_ts("2026-01-01T00:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0
        assert (dt.year, dt.month, dt.day) == (2026, 1, 1)

    def test_offset_converted_to_utc(self):
        """+08:00 的早上 8 点 = UTC 的零点。"""
        assert utc_str("2026-01-01T08:00:00+08:00") == "2026-01-01T00:00:00Z"

    def test_naive_treated_as_utc(self):
        """全库既有约定：naive 一律按 UTC 解释，不是按机器本地时区。"""
        dt = parse_ts("2026-01-01T00:00:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_fractional_seconds_not_truncated(self):
        """微秒必须保留。

        原先各调用点用 `[:19]` / `[:26]` 截断，会把 `.123456` 悄悄吃掉。
        3.11 的 fromisoformat 原生支持任意位小数，不该再截。
        """
        assert parse_ts("2026-01-01T00:00:00.123456Z").microsecond == 123456
        assert parse_ts("2026-01-01T00:00:00.1Z").microsecond == 100000

    def test_epoch_seconds_and_millis(self):
        """沿用 base_jsonl 的既有判定：< 1e12 视为秒级 epoch，否则毫秒级。"""
        expected = "2023-11-14T22:13:20Z"
        assert utc_str(1700000000) == expected
        assert utc_str(1700000000000) == expected

    def test_digit_string_is_epoch_not_date(self):
        """兼容既有口径（原 base_jsonl._ts_to_iso）：纯数字串按 epoch 解释。

        "20260101" 若喂给 fromisoformat 会被解析成这个**日期**，
        而采集到的时间戳实际是 epoch 秒——这条差异会让会话时间整体错位。
        """
        assert utc_str("1700000000") == "2023-11-14T22:13:20Z"
        assert utc_str("20260101") == utc_str(20260101)

    def test_datetime_passthrough(self):
        naive = datetime(2026, 1, 1)
        assert parse_ts(naive) == datetime(2026, 1, 1, tzinfo=timezone.utc)
        aware = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
        assert parse_ts(aware) == aware

    def test_bool_rejected(self):
        """bool 是 int 子类，`True` 不该被当成 1 秒 epoch。"""
        assert parse_ts(True) is None
        assert parse_ts(False) is None

    def test_failures_return_none(self):
        for bad in (None, "", "   ", "not-a-date", "2026-13-45T00:00:00Z", {}, []):
            assert parse_ts(bad) is None, f"坏值 {bad!r} 应返回 None"

    def test_epoch_overflow_returns_none(self):
        assert parse_ts(1e300) is None


class TestUtcStr:
    def test_output_shape(self):
        assert utc_str("2026-01-02T10:30:00Z") == "2026-01-02T10:30:00Z"

    def test_drops_microseconds(self):
        """秒级输出，天然丢微秒——与原先 `[:19]` 截断后的输出一致。"""
        assert utc_str("2026-01-02T10:30:00.987Z") == "2026-01-02T10:30:00Z"

    def test_bad_value_is_empty_string(self):
        assert utc_str(None) == ""
        assert utc_str("junk") == ""


class TestDayOfWeek:
    def test_day_of(self):
        assert day_of("2026-01-02T10:30:00Z") == "2026-01-02"
        assert day_of("junk") is None

    def test_day_of_crosses_utc_boundary(self):
        """+08:00 的早上 8 点属于 UTC 的前一天——按 UTC 归属，不是按本地。"""
        assert day_of("2026-01-02T04:00:00+08:00") == "2026-01-01"

    def test_week_start_is_monday(self):
        # 是星期二，所属周起点为周一 11-13
        assert week_start("2023-11-14T22:13:20Z") == date(2023, 11, 13)

    def test_week_start_idempotent(self):
        """再取一次周起点必须还是同一天（防 off-by-one 累积）。"""
        d = week_start("2026-01-04T00:00:00Z")  # 周日
        assert week_start(d.isoformat()) == d

    def test_week_start_bad_value(self):
        assert week_start("junk") is None


class TestNoAdHocParsing:
    def test_no_hand_rolled_fromisoformat(self):
        """收口契约：业务层不许再自己加工时间戳字符串。

        app/time_util.py 是唯一允许调用 `fromisoformat` 的地方（它已排除在本扫描
        之外）。业务层一律走 parse_ts / utc_str / day_of / week_start，不许自己
        喂字符串给 fromisoformat——一旦散落，naive/aware 就会重新分叉。
        """
        offenders: list[str] = []
        roots = [ROOT / "app" / sub for sub in
                 ("store", "capture", "gui", "distill", "proxy", "semantic",
                  "insight", "platform", "rules", "local_api_routers")]
        files: list[Path] = []
        for base in roots:
            if not base.exists():
                continue
            files.extend(p for p in base.rglob("*.py")
                         if "__pycache__" not in p.parts)
        files.extend(p for p in (ROOT / "app").glob("*.py")
                     if p.name != "time_util.py")
        for py in files:
            for i, line in enumerate(
                    py.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if "fromisoformat" in line:
                    offenders.append(f"{py.relative_to(ROOT)}:{i}")
        assert not offenders, (
            "发现手写的时间戳字符串加工，改用 app.time_util.parse_ts/utc_str/"
            "day_of/week_start: " + ", ".join(offenders))
