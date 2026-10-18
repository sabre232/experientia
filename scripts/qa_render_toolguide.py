# -*- coding: utf-8 -*-
"""交付自证（分工具向导 C 方案）：离屏真实渲染「分工具接入说明」卡。

抓四个状态：① 默认选中 Claude Code（环境变量类）② Codex（配置文件类，
代码块最长）③ Cursor（仅官方：无代码块、长句解释）④ 英文语切 Codex
（验拉丁文案不破版）。工具卡是静态内容（无异步数据），show 后直接 grab。
用法：QT_QPA_PLATFORM=offscreen uv run python -X utf8 scripts/_qa_render_toolguide.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApi, LocalApiError  # noqa: E402

i18n.load_catalog("zh")

OUT = ROOT / "build" / "qa_toolguide_win"
OUT.mkdir(parents=True, exist_ok=True)


class _DeadApi(LocalApi):
    def _request(self, method, path, json=None, params=None, timeout=None):
        raise LocalApiError(0, "本地 API 未连接")


def settle(app, ms=350):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    from app.gui.connect_page import ConnectPage
    page = ConnectPage(_DeadApi())
    page.resize(1080, 900)
    page._toggle_tools()          # 展开高级设置
    page.show()
    settle(app, 600)

    def snap(name):
        card = page._tools_card
        assert not card.isHidden(), "分工具卡不应被隐藏"
        pix = card.grab()
        path = OUT / f"{name}.png"
        pix.save(str(path))
        print("saved", path, pix.width(), "x", pix.height())

    snap("1_default_claude_env")
    page._select_guide("Codex")
    settle(app, 200)
    snap("2_codex_file")
    page._select_guide("Cursor")
    settle(app, 200)
    snap("3_cursor_official")

    # 英文：整卡重建路径（retranslateUi → _rebuild_tools_inner）
    i18n.load_catalog("en")
    page.retranslateUi()
    settle(app, 300)
    page._select_guide("Codex")
    settle(app, 200)
    snap("4_en_codex")
    i18n.load_catalog("zh")
    page.deleteLater()
    return 0


if __name__ == "__main__":
    sys.exit(main())
