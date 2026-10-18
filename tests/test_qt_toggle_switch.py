"""P2-4：ToggleSwitch 旋钮过渡（150ms 动画）+ reduced-motion 直落目标态。

离屏渲染（QT_QPA_PLATFORM=offscreen）下验证两条路径：
- motion_ok()=True：setChecked 启动 QPropertyAnimation（progress 0↔1，时长 ANIM_MS）；
- motion_ok()=False：setChecked 同步直落目标进度，动画不启动。
"""
import os

import pytest
from PySide6.QtCore import QAbstractAnimation

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app.gui.qt_widgets as qw  # noqa: E402
from app.gui.qt_widgets import ToggleSwitch  # noqa: E402


def test_switch_initial_progress_matches_state(qapp):
    off = ToggleSwitch(False)
    on = ToggleSwitch(True)
    assert off._progress == 0.0
    assert on._progress == 1.0


def test_switch_normal_path_animates(qapp, monkeypatch):
    monkeypatch.setattr(qw, "motion_ok", lambda: True)
    sw = ToggleSwitch(False)
    sw.setChecked(True)
    # 动画目标属性是 progress，时长取设计系统 DURATION_NORMAL（150-200ms 档）
    assert sw._anim.propertyName() == "progress"
    assert sw._anim.duration() == ToggleSwitch.ANIM_MS
    assert 150 <= ToggleSwitch.ANIM_MS <= 200
    assert sw._anim.state() == QAbstractAnimation.Running
    assert sw._anim.endValue() == 1.0
    sw._anim.stop()


def test_switch_reduced_motion_jumps(qapp, monkeypatch):
    monkeypatch.setattr(qw, "motion_ok", lambda: False)
    sw = ToggleSwitch(False)
    sw.setChecked(True)
    # reduced-motion：进度同步直落到 1.0，动画不启动
    assert sw._progress == 1.0
    assert sw._anim.state() == QAbstractAnimation.Stopped
    sw.setChecked(False)
    assert sw._progress == 0.0
