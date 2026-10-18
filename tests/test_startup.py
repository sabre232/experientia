"""启动与外壳 · 归属测试（任务书）。

三条验收：
1. `import app.gui.qt_icons` 不拉 `app.gui._mdi_map`（MDI 表惰性加载）；
2. `MainWindow` 的页面容器是 `AnimatedStack`（页面过渡接线）；
3. 启动/切页打点函数可调用且不抛（打点）。

依赖 PySide6（未装则整组跳过，与 test_qt_pages.py 同款守卫）。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApi, LocalApiError  # noqa: E402


class _DeadApi(LocalApi):
    """一切请求立即失败（模拟引擎未运行），零网络、确定性。"""

    def _request(self, method, path, json=None, params=None, timeout=None):
        raise LocalApiError(0, "本地 API 未连接")


@pytest.fixture(autouse=True)
def _dead_api(monkeypatch):
    """MainWindow.__init__ 内部 `self.api = CachedApi()` 指向真实 8101（沙箱里
    每请求 ~2s）。换成 _DeadApi，让构建/刷新零网络。"""
    import app.gui.main_window as mw

    monkeypatch.setattr(
        mw, "CachedApi",
        lambda *a, **k: _DeadApi(base_url="http://127.0.0.1:8101"))


class _Store:
    """MainWindow 所需的最小 store 桩。"""

    def __init__(self):
        self.data_dir = str(Path(__file__).resolve().parent / "data-test-tmp")

    def load_config(self) -> dict:
        return {"locale": "zh"}

    def ensure_layout(self) -> None:
        pass


# ----------  MDI 表惰性加载 ----------

def test_qt_icons_does_not_import_mdi_map_at_import_time():
    """`import app.gui.qt_icons` 后 `app.gui._mdi_map` 不在 sys.modules。

    同进程内其它测试（如 test_gui_import 会显式导入 _mdi_map）可能已把表拉进
    sys.modules，故先把 qt_icons 与 _mdi_map 一并摘出再重新导入——量到的是
    "qt_icons 自身导入期是否整表解析"，不受测试执行顺序污染。
    """
    saved = {n: sys.modules.pop(n) for n in
             ("app.gui.qt_icons", "app.gui._mdi_map") if n in sys.modules}
    try:
        mod = importlib.import_module("app.gui.qt_icons")
        assert "app.gui._mdi_map" not in sys.modules, \
            "qt_icons 导入期不应整表解析 _mdi_map（233KB 字典）"
        # 惰性触发：取字形时才加载并缓存
        glyph = mod.icon_glyph("cog")
        assert isinstance(glyph, str) and len(glyph) == 1
        assert "app.gui._mdi_map" in sys.modules, "取字形后应已惰性加载 _mdi_map"
    finally:
        for name in ("app.gui.qt_icons", "app.gui._mdi_map"):
            sys.modules.pop(name, None)
        sys.modules.update(saved)
        import app.gui as _pkg

        for name, module in saved.items():
            setattr(_pkg, name.rsplit(".", 1)[1], module)


# ----------  页面过渡接线 ----------

def test_main_window_uses_animated_stack(qapp):
    """页面容器是 AnimatedStack（QStackedWidget 子类，切页带过渡）。"""
    from app.gui.main_window import MainWindow
    from app.gui.qt_widgets import AnimatedStack

    win = MainWindow(_Store())
    try:
        assert isinstance(win._stack, AnimatedStack)
    finally:
        win._allow_quit = True
        win.close()


# ----------  打点 ----------

def test_phase_timing_helpers_callable():
    """启动/切页/首刷打点函数可调用且不抛（只写日志）。"""
    import main as entry
    from app.gui.main_window import _phase_page

    _phase_page("切页 测试", 12.3)
    _phase_page("首刷 测试", 4.5)
    entry._phase("测试打点")