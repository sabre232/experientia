# -*- coding: utf-8 -*-
"""报告弹层真机自证：按钮行含「打开文件夹」，且导出成功后才可用。

为什么不用离屏：离屏渲染缺 CJK 字体，中文全成方块（方案）——本次交付物就是
按钮行的中文，必须走真实平台插件渲染。脚本只 grab 自己的弹层窗口，不碰数据目录；
`_open_folder` 打桩记录调用（不真的弹系统文件管理器）。

用法：uv run python -X utf8 scripts/_qa_render_report_dialog.py [输出目录]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.store.store as _ss  # noqa: E402

_ss.Store._init_expdb = lambda self: None  # 只读：不重建 SQLite 索引

from PySide6.QtWidgets import (QApplication, QLabel, QPushButton,  # noqa: E402
                               QVBoxLayout, QWidget)

from app.gui import i18n, report_view, settings_page  # noqa: E402
from app.gui.i18n import t  # noqa: E402

OUT = (Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1]
       else ROOT / "build" / "qa_report")


class _Api:
    """弹层只用到 export / status —— 假 API 钉死返回，不碰真数据。"""

    def __init__(self, out_dir: Path):
        self._out = out_dir

    def export(self, kind, **kw) -> dict:
        return {"path": str(self._out / "成长报告-30天.md")}

    def status(self) -> dict:
        return {"data_dir": str(self._out)}


def _btn(dlg, name: str):
    return next((b for b in dlg.findChildren(QPushButton) if b.text() == name), None)


def _labels(dlg) -> list[str]:
    return [l.text() for l in dlg.findChildren(QLabel)]


def main() -> int:
    i18n.load_catalog("zh")
    app = QApplication.instance() or QApplication([])
    OUT.mkdir(parents=True, exist_ok=True)

    opened: list[str] = []
    settings_page._open_folder = lambda p: opened.append(str(p))  # type: ignore[assignment]

    body = QWidget()
    lay = QVBoxLayout(body)
    lay.addWidget(QLabel(t("海报正文占位（自证只看按钮行）")))
    api = _Api(OUT)
    dlg = report_view._report_dialog(
        api, t("成长报告"), body, (("growth",), {"days": 30}),
        {"title": "成长报告", "blocks": []}, "growth")
    dlg.show()
    for _ in range(6):
        app.processEvents()

    problems: list[str] = []
    texts = [b.text() for b in dlg.findChildren(QPushButton)]
    for want in ("关闭", "打开文件夹", "导出 PNG", "导出 md"):
        if want not in texts:
            problems.append(f"按钮行缺「{want}」：{texts}")

    folder = _btn(dlg, "打开文件夹")
    if folder is None:
        print("RESULT: FAIL —— 没找到「打开文件夹」按钮")
        return 1
    if folder.isEnabled():
        problems.append("还没导出过，「打开文件夹」不该可用（点了不知道开哪儿）")
    dlg.grab().save(str(OUT / "report_dialog_before_export.png"))

    _btn(dlg, "导出 md").click()
    for _ in range(300):  # 等后台 worker 回来（QThread）
        app.processEvents()
        time.sleep(0.02)
        if folder.isEnabled():
            break
    if not folder.isEnabled():
        problems.append("导出 md 成功后「打开文件夹」仍未启用")

    folder.click()
    for _ in range(4):
        app.processEvents()
    if opened != [str(OUT)]:
        problems.append(f"点「打开文件夹」没按产物目录调用系统打开：{opened}")
    if not any("已打开文件夹" in s for s in _labels(dlg)):
        problems.append(f"没回执：{_labels(dlg)}")
    dlg.grab().save(str(OUT / "report_dialog_after_export.png"))

    print("按钮行:", texts)
    print("打开文件夹调用:", opened)
    print("状态行:", [s for s in _labels(dlg) if s][-1:])
    print("产物:", "report_dialog_before_export.png", "report_dialog_after_export.png")
    print("问题:", problems or "无")
    print("RESULT:", "PASS" if not problems else "FAIL")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
