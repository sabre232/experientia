# -*- mode: python ; coding: utf-8 -*-
"""Experientia — PyInstaller 打包配置（迁移清单）。

用法（在仓库根，激活 .venv）：
    pyinstaller --noconfirm --clean experientia.spec
产物：dist/Experientia/Experientia.exe（onedir，windowed，无控制台窗口）。

要点：
- console=False：无控制台窗口
- datas：assets/（mascot/图标/字体/启动图）+ app/gui/locales/（7 语 .mo）
- PySide6 依赖由 PyInstaller 内置 hook 自动收集（Qt 插件/平台 dll）
- Qt 版不依赖 flet（gui 层无任何 flet 导入），excludes 兜底排除，包体不含 Flutter 引擎
- 引擎（fastapi/uvicorn/httpx/keyring/babel/zstandard/PIL）均为静态导入，自动分析
- A2 在 Analysis 之后过滤 a.binaries，去掉 opengl32sw.dll（19.7 MB，软件渲染后备）
"""

from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "assets"), "assets"),
        (str(ROOT / "app" / "gui" / "locales"), "app/gui/locales"),
        # 规则模板库（350 个 .md 内容资产）：registry 按包相对路径 glob 加载，
        # PyInstaller 不自动收集非 import 资源，须显式打入，否则 frozen 构建下模板库为空。
        (str(ROOT / "app" / "rules" / "templates"), "app/rules/templates"),
    ],
    hiddenimports=[
        # PySide6 显式声明（迁移清单）
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        # app/gui/_mdi_map.py：qt_icons._mdi() 用 importlib.import_module 动态加载
        # （的启动优化——把 233KB 码点表的解析推迟到首个图标落地时），
        # 而 PyInstaller 只做静态分析，**看不见运行期导入** → 模块不会进包。
        #  实测后果（此前一直存在，只是没人从"装出来的包"里跑过）：
        # 装完启动 → MainWindow 初始化即 ModuleNotFoundError('app.gui._mdi_map')
        # → 主窗口永远出不来；又因 console=False 没有 stderr，异常只剩 PyInstaller
        # 的错误对话框，进程"看着还活着"、日志停在闪屏，极难排查。
        # 谁再新增动态导入，务必同步在此声明（tests/test_packaging_dynamic_imports.py
        # 会把这条契约钉住）。
        "app.gui._mdi_map",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Qt 版不需要 flet；即便意外安装也不打入（体积 +400MB）
        "flet",
        "flet_core",
        "tkinter",
        # Qt6Pdf：全仓零 PDF 引用（无 QPdfDocument / QPrinter-PDF / toPdf 用法），
        # 排除后包体少 4.4 MB。已 grep 复核 app/ 全目录。
        "PySide6.QtPdf",
        # Qml/Quick 集群：同上，导入表实测无核心 Qt 模块依赖它们。
        "PySide6.QtQml",
        "PySide6.QtQuick",
    ],
    noarchive=False,
)

# ---------- A2（轻量方案）：去掉 Qt 自带的 Software OpenGL 后备 ----------
# opengl32sw.dll（19.7 MB）是 Qt 在无 GPU / 驱动被拉黑时的软件渲染回落实现。
# 本项目是纯 Widgets 应用，全仓未设 Qt::AA_UseSoftwareOpenGL，运行时不会加载它。
# 注意：excludes= 只对 Python 模块生效，DLL 必须在这里对 a.binaries 做过滤。
# ---------- A3（轻量方案）：去掉用不到的 Qt 组件 ----------
# 三批，每批动手前都用 pefile 解析过 PE 导入表确认「谁依赖它」：
#
# 1) opengl32sw.dll（19.7 MB）：Qt 的 Software OpenGL 后备。纯 Widgets 应用、
# 未设 Qt::AA_UseSoftwareOpenGL，运行时不会加载。
# 2) qt6pdf（4.4 MB）：全仓 grep 复核零 PDF 引用（无 QPdfDocument/QPrinter-PDF/toPdf）。
# 3) Qml/Quick 集群（12.9 MB）：Qt6Qml / Qt6Quick / Qt6QmlMeta / Qt6QmlModels /
# Qt6QmlWorkerScript / Qt6VirtualKeyboard。导入表实测：**导入它们的全部是
# Qml 家族自己的成员**，Qt6Core / Qt6Gui / Qt6Widgets / Qt6Network 一个都不
# 依赖它们——是自成一体的集群。Qt6Qml.dll 自身只依赖 Qt6Network + Qt6Core。
# （Qt6Network 被 Widgets 需要，保留。）
_EXCLUDED_NAMES = ("opengl32sw", "qt6pdf", "qt6qml", "qt6quick",
                   "qt6qmlmeta", "qt6qmlmodels", "qt6qmlworkerscript",
                   "qt6virtualkeyboard",
                   # 上面几批 dll 的**插件**也要一起排：plugins/ 下的
                   # qpdf.dll（imageformats，读 PDF 图像）与
                   # qtvirtualkeyboardplugin.dll（虚拟键盘输入法）会 import
                   # 已排除的 Qt6Pdf/Qt6VirtualKeyboard，留着就是悬空依赖。
                   # 排查方法：对 _internal 下**所有** dll/pyd（含 plugins/）
                   # 解析 PE 导入表——只扫 PySide6/*.pyd 会漏掉这两个。
                   "qpdf", "qtvirtualkeyboardplugin")


def _keep(item) -> bool:
    """item = (dest_name, src_path, typecode)。

    Qt hook 既可能把它收进 binaries、也可能收进 datas（实测是后者），
    所以两个通道都要过滤，只滤一处会静默失效。
    """
    return not any(n in item[0].lower() for n in _EXCLUDED_NAMES)


_n_before = (len(a.binaries), len(a.datas))
a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]
print("[A2] binaries %d->%d, datas %d->%d, 去除 %d 项" % (
    _n_before[0], len(a.binaries), _n_before[1], len(a.datas),
    _n_before[0] + _n_before[1] - len(a.binaries) - len(a.datas)))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Experientia",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 启动优化：关闭 UPX——压缩段会被杀软逐段扫描/解压，
    # 拖慢冷启动并易误报；现代磁盘下体积收益 < 启动损耗
    console=False,  # 无控制台窗口
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "icon_windows.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Experientia",
)
