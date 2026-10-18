"""GUI 模块可导入性冒烟：app/gui/ 下 Qt 栈模块（qt_* 工厂/控件 + 各页面）逐一 import，
保证无语法/导入错误。依赖 PySide6（未装则整组跳过，与 test_qt_pages.py 同款守卫）。"""

import importlib

import pytest

pytest.importorskip("PySide6")

GUI_MODULES = [
    "app.gui.i18n",
    "app.gui.api_client",
    "app.gui.layout",
    "app.gui.theme",
    "app.gui.qt_icons",
    "app.gui.qt_theme",
    "app.gui.qt_widgets",
    "app.gui.qt_splash",
    "app.gui.page_base",
    "app.gui.onboarding",
    "app.gui.home",
    "app.gui.models_page",
    "app.gui.experiences",
    "app.gui.methods",
    "app.gui.failure_modes",
    "app.gui.preferences_page",
    "app.gui.growth",
    "app.gui.hooks_page",
    "app.gui.skill_organize",
    "app.gui.inject_preview",
    "app.gui.my_experience",
    "app.gui.experience_edit",
    "app.gui.export_page",
    "app.gui.report_model",
    "app.gui.report_view",
    "app.gui.poster",
    "app.gui.refutation",
    "app.gui.connect_page",
    "app.gui.settings_page",
    "app.gui.qt_dialogs",
    "app.gui.agent_proc",
    "app.gui._mdi_map",
    "app.gui.main_window",
    # 在飞工作新增的 5 个模块此前不在清单里（靠主模块
    # 间接导入，本守卫漏检它们的语法/导入错误）
    "app.gui.timeline",
    "app.gui.connect_probe",
    "app.gui.template_library",
    "app.gui._ago",
    "app.gui._name_map",
]


@pytest.mark.parametrize("mod", GUI_MODULES)
def test_gui_module_imports(mod):
    importlib.import_module(mod)


def test_theme_tokens_stable():
    """token 层冒烟：核心 token 类/常量可访问（theme.py 现为纯 token 模块）。"""
    from app.gui import theme

    assert theme.F.body == 14
    assert theme.R.lg == 16
    assert theme.S.s4 == 16
    assert theme.SIZES.NAV_WIDTH == 120
    assert theme.ANIMATION.EASE == "ease"
    assert theme.THRESHOLDS.BAR_LABEL_MIN_RATIO == 0.30
    assert len(theme.HEAT_SCALE) == 6
    assert theme.C.primary_fill == "#C2410C"
