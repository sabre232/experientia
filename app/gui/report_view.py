"""应用内报告弹层（Qt 版，对应 Flet 源 report_view.py）：成长报告 / 方法论报告。

海报形态：成长报告 / 方法论报告。一份 spec 两个渲染器
（gui/poster.py）：弹层 = Qt 海报（主展示），PNG = PIL 同布局渲染（导出分享），
md = 降级版（distill/export.py，固定中文）；溯源两边都有（方案 A）。

设计口径（frontend-design / taste-skill / ui-ux-pro-max 三 skill 收敛）：
- 海报有主角：改善最大的类别 display 级大数字（方向色配数字+箭头，不只靠颜色）
- 单一品牌色点缀，中性灰支撑；结构即信息（眉条→主角→佐证→溯源），无装饰
- 每弹层两个导出（md / PNG）+ 打开文件夹 + 关闭；无动画；字号只走 F 五档
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from . import poster
from .api_client import LocalApi, LocalApiError
from .i18n import t
from .page_base import ApiWorker
from .qt_dialogs import info_dialog
from .qt_theme import btn_primary, btn_secondary, mascot_image, status_text, txt
from .report_model import growth_report_model, parse_playbook
from .theme import C, D, F, S, SIZES


def _report_dialog(api, title: str, body_widget: QWidget, export_args,
                   spec: dict, kind: str, parent: QWidget | None = None) -> QDialog:
    """海报弹层外壳：标题 + 可滚动海报正文 + 双导出（md / PNG）。

    export_args = (位置参数, 关键字参数)，供 api.export（md）调用；
    PNG 走 poster 直接渲染（GUI 进程内 PIL，不绕 API）。
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    lay.setSpacing(S.s3)
    lay.setContentsMargins(S.s4, S.s4, S.s4, S.s4)

    # 标题行（标题 + 右上 smile 宇航员）
    head = QHBoxLayout()
    head.setSpacing(S.s2)
    head.addWidget(txt(title, F.h1, 800))
    head.addStretch(1)
    head.addWidget(mascot_image("smile", SIZES.MASCOT_DIALOG_TITLE))
    lay.addLayout(head)

    # 可滚动正文：内容高 = min(海报定高, 父窗高 70% 或 620)，小窗不溢出靠 scroll
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    p_h = parent.height() if parent is not None else 0
    body_h = min(D.REPORT_H, int(p_h * 0.7) if p_h else 620)
    scroll.setFixedHeight(body_h)
    scroll.setWidget(body_widget)
    lay.addWidget(scroll)

    # 状态行
    msg = status_text("", tone="ok")
    lay.addWidget(msg)

    export_btn = btn_primary(t("导出 md"))
    png_btn = btn_secondary(t("导出 PNG"))
    # 导出后能立刻打开产物所在文件夹（导出后立即能打开）；
    # 还没导出过 = 没得开 → 先禁用，免得点了不知道会打开哪儿
    folder_btn = btn_secondary(t("打开文件夹"))
    folder_btn.setEnabled(False)
    close_btn = QPushButton(t("关闭"))
    close_btn.clicked.connect(dlg.reject)

    btns_row = QHBoxLayout()
    btns_row.setSpacing(S.s2)
    btns_row.addWidget(close_btn)
    btns_row.addStretch(1)
    btns_row.addWidget(folder_btn)
    btns_row.addWidget(png_btn)
    btns_row.addWidget(export_btn)
    lay.addLayout(btns_row)

    # 后台导出（QThread），期间禁用按钮避免共用状态行冲突（H-N5 / U11）
    workers: list = []
    dlg._report_workers = workers
    last_out: dict[str, str | None] = {"dir": None}

    def _remember(path) -> None:
        """记住产物所在目录（导出成功才有得开）。"""
        try:
            last_out["dir"] = str(Path(path).parent)
        except Exception:  # noqa: BLE001 路径异常不该影响「已保存到」的展示
            last_out["dir"] = None

    def _set_msg(text: str, tone: str) -> None:
        color = {"ok": C.ok_fg, "err": C.err_fg, "info": C.info_fg}[tone]
        msg.setText(text)
        msg.setStyleSheet(f"color: {color}; background: transparent; border: none;")

    def _on_done(text: str, *btns) -> None:
        _set_msg(text, "ok")
        for b in btns:
            b.setEnabled(True)
        folder_btn.setEnabled(bool(last_out["dir"]))

    def _on_error(err: str, *btns) -> None:
        _set_msg(str(err), "err")
        for b in btns:
            b.setEnabled(True)

    def _run(work_fn, btns: list[QPushButton]) -> None:
        for b in btns:
            b.setEnabled(False)
        _set_msg(t("正在导出…"), "info")
        worker = ApiWorker(work_fn, dlg)
        workers.append(worker)
        worker.finished.connect(lambda r, b=btns: _on_done(r, *b))
        worker.error.connect(lambda e, b=btns: _on_error(e, *b))
        # 导出 worker 完成即释放 C++ 对象并从**本弹窗的**
        # 局部清单摘除（模块级 _report_workers 是 _async_open 用的，别摘错列表）
        def _rel(*_a):
            try:
                workers.remove(worker)
            except ValueError:
                pass

        worker.finished.connect(_rel)
        worker.error.connect(_rel)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        worker.start()

    def do_export() -> None:
        btns = [export_btn, png_btn]
        png_btn.setEnabled(False)  # U11：导出 md 时禁用 PNG 按钮，避免共用 msg 冲突

        def work() -> str:
            r = api.export(*export_args[0], **export_args[1])
            _remember(r["path"])
            return t("已保存到 {path}", path=r["path"])

        _run(work, btns)

    def do_png() -> None:
        btns = [export_btn, png_btn]
        export_btn.setEnabled(False)  # U11：导出 PNG 时禁用 md 按钮

        def work() -> str:
            data_dir = api.status().get("data_dir")
            if not data_dir:
                raise LocalApiError(0, t("数据目录不可用"))
            p = poster.render_png_to_spec(spec, data_dir, kind)
            _remember(p)
            return t("已保存到 {path}", path=str(p))

        _run(work, btns)

    def do_open_folder() -> None:
        d = last_out["dir"]
        if not d:
            _set_msg(t("先导出一次，再打开文件夹"), "info")
            return
        if not Path(d).is_dir():
            _set_msg(t("文件夹已不在了：{path}", path=d), "err")
            return
        from .settings_page import _open_folder  # 懒导入防循环依赖
        _open_folder(d)
        _set_msg(t("已打开文件夹：{path}", path=d), "ok")

    export_btn.clicked.connect(do_export)
    png_btn.clicked.connect(do_png)
    folder_btn.clicked.connect(do_open_folder)

    dlg.resize(D.REPORT_W, body_h + 140)
    return dlg


def _three_layer_body(spec: dict) -> QWidget:
    """三层结构容器：layer_1（眉条）+ layer_2（主角）+ layer_3（佐证）。"""
    l1, l2, l3 = poster.to_controls(spec)
    body = QWidget()
    lay = QVBoxLayout(body)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    def _pack(items: list, bg: str, pad: int, spacing: int) -> QWidget:
        box = QWidget()
        box.setObjectName("posterLayer")
        # #id 限定：裸 QWidget 会级联到层内子控件
        box.setStyleSheet(f"QWidget#posterLayer {{ background: {bg}; }}")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(pad, pad, pad, pad)
        bl.setSpacing(spacing)
        for it in items:
            bl.addWidget(it)
        return box

    if l1:
        lay.addWidget(_pack(l1, C.surface, 0, S.s1))
    if l2:
        lay.addWidget(_pack(l2, C.surface_hero, D.POSTER_PAD, S.s3))
    if l3:
        lay.addWidget(_pack(l3, C.surface, D.POSTER_PAD, S.s3))
    lay.addStretch(1)
    return body


def _fail(parent: QWidget | None, message: str) -> None:
    """打开失败提示（模块函数无页面状态行，用信息弹层）。"""
    info_dialog(t("报告"), message, parent)


# 后台打开中的 worker 引用（防 GC；finish/error 后移除）
_report_workers: list = []


def _release_worker(w) -> None:
    try:
        _report_workers.remove(w)
    except ValueError:
        pass


def _async_open(work, on_ok, on_err) -> None:
    """后台取数（不碰 widget），就绪后由 on_ok/on_err 在主线程构建/提示。"""
    worker = ApiWorker(work)
    _report_workers.append(worker)
    # 元组写法会让 on_ok 的异常吞掉 _release_worker，worker
    # 永久留在模块级清单；try/finally 保证释放，异常照旧逃逸给 Qt 事件循环。
    def _cb(r):
        try:
            on_ok(r)
        finally:
            _release_worker(worker)

    def _eb(e):
        try:
            on_err(e)
        finally:
            _release_worker(worker)

    worker.finished.connect(_cb)
    worker.error.connect(_eb)
    worker.start()


# ---------- 成长报告 ----------

def _milestone_overlay(parent: QWidget) -> None:
    """里程碑遮罩：本轮结算**解锁了新成就**才弹（数字变大不激励，
    具象变身才激励）——旧文案写"超过 30% 的明显进步"，与判定口径已经不符。"""
    ov = QDialog(parent)
    ov.setModal(True)
    ov.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
    ov.setStyleSheet(f"QDialog {{ background: {C.surface}; }}")
    lay = QVBoxLayout(ov)
    lay.setSpacing(S.s3)
    lay.setAlignment(Qt.AlignCenter)
    lay.addWidget(mascot_image("celebrate", SIZES.MASCOT_MILESTONE),
                  0, Qt.AlignHCenter)
    lay.addWidget(txt(t("恭喜！解锁新里程碑"), F.h1, 800, C.ink_700),
                  0, Qt.AlignHCenter)
    lay.addWidget(txt(t("这轮结算里有成就达成——点开报告看是哪一项"), F.caption,
                      color=C.ink_500), 0, Qt.AlignHCenter)
    lay.addSpacing(S.s4)
    cont = btn_primary(t("继续看报告"))
    cont.clicked.connect(ov.accept)
    lay.addWidget(cont, 0, Qt.AlignHCenter)
    ov.resize(parent.size() if parent is not None else (720, 620))
    ov.exec()


def open_growth_report(api, days: int = 30, parent: QWidget | None = None) -> None:
    """成长海报：后台取数，主线程构建弹层，避免 growth 全扫拖住 UI 线程。

    大幅改善超过阈值时先弹 celebrate 遮罩，点「继续看报告」再进海报
    （庆祝只挂在用户主动生成的动作上，不进页自动弹）。
    """
    def work() -> dict:
        return api.growth(days=days)

    def on_ok(g: dict) -> None:
        spec = poster.growth_poster(growth_report_model(g), t)
        dlg = _report_dialog(api, spec["title"], _three_layer_body(spec),
                             (("growth",), {"days": days}), spec, "growth", parent)
        # 里程碑遮罩：大幅改善超过阈值 → 先显示 celebrate，点「继续看报告」再进报告
        if spec.get("has_significant_improvement"):
            _milestone_overlay(dlg)
        dlg.exec()

    _async_open(work, on_ok,
                lambda err: _fail(parent, t("报告打开失败：{err}", err=err)))


# ---------- 方法论报告 ----------

def open_methodology_report(api, trunk: str, category: str,
                            parent: QWidget | None = None) -> None:
    """方法论海报：品牌眉条 + meta（置信度/版本/来源）+ 正文节 + 溯源脚注。

    M13：取数走后台线程（同成长报告），主线程不冻结；失败统一 _fail 弹窗，
    不再同步吞异常按空报告渲染。
    """
    def work() -> tuple[str, list[dict]]:
        md = api.read_skill(trunk, category).get("md")
        if md is None:
            raise LocalApiError(404, t("这个方法已不存在（可能已被删除）"))
        return md, _category_exps(api, trunk, category)

    def on_ok(result: tuple) -> None:
        md, exps = result
        spec = poster.method_poster(parse_playbook(md), exps, t,
                                    fallback=f"{trunk} / {category}")
        dlg = _report_dialog(api, spec["title"], _three_layer_body(spec),
                             (("playbook",), {"playbooks": [
                                 {"trunk": trunk, "category": category}]}),
                             spec, "method", parent)
        dlg.exec()

    _async_open(work, on_ok,
                lambda err: _fail(parent, t("报告打开失败：{err}", err=err)))


def _category_exps(api: LocalApi, trunk: str, category: str) -> list[dict]:
    """溯源的沉淀依据：该类别全部经验（成功/踩坑拆分，与 md 同口径）。"""
    try:
        return api.experiences(trunk=trunk, category=category,
                               limit=500).get("items", [])
    except LocalApiError:
        return []
