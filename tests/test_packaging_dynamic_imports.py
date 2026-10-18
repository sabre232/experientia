"""打包收口守卫：**动态 import 的模块必须在 spec 的 hiddenimports 里声明**。

PyInstaller 只做静态分析——`importlib.import_module("x.y")` 这类运行期导入它
看不见，模块不会进包。这类缺失有个共同特征：**本机（源码模式）永远测不出来**，
只在"装到干净机器上跑"时才炸，而且炸得很难看：

   实测：`app/gui/_mdi_map.py`（233KB 图标码点表，`qt_icons._mdi()`
  为推迟首帧开销而动态加载）没进包 → 安装后启动即
  `ModuleNotFoundError: No module named 'app.gui._mdi_map'` → MainWindow 初始化
  失败、主窗口永远出不来。又因 `console=False` 没有 stderr，异常只变成
  PyInstaller 的错误对话框：进程"看着还在跑"、日志停在闪屏、两个 HTTP 端口
  也一直没绑定（主线程一死，daemon 服务线程被立刻掐掉）——排查成本极高。

所以把"动态导入点"与"spec 声明"绑成契约：谁新增一处动态导入，谁就得同步声明，
否则本测试失败。当前全仓 `app/` 下只有 `qt_icons.py` 一处。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "experientia.spec"


def _spec_hiddenimports() -> set[str]:
    """spec 里 hiddenimports=[...] 块中声明过的模块名。"""
    text = SPEC.read_text(encoding="utf-8")
    block = re.search(r"hiddenimports\s*=\s*\[(.*?)\]", text, re.S)
    assert block, "experientia.spec 里找不到 hiddenimports=[...] 块"
    return set(re.findall(r'"([\w.]+)"', block.group(1)))


def _package_of(path: Path) -> str:
    """某文件的所属包名（用于解析 `f"{__package__}.x"` 写法）。

    app/gui/qt_icons.py → app.gui；app/gui/__init__.py → app.gui
    """
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    else:
        parts = parts[:-1]
    return ".".join(parts)


def _resolve(node: ast.AST, package: str) -> str | None:
    """把 import_module 的实参解析成模块全名；解析不了返回 None（不误报）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        raw = node.value
        return package + raw if raw.startswith(".") else raw
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            elif (isinstance(part, ast.FormattedValue)
                  and isinstance(part.value, ast.Name)
                  and part.value.id == "__package__"):
                out.append(package)
            else:
                return None  # 拼接方式我们解析不了，交给人工判断
        name = "".join(out)
        return package + name if name.startswith(".") else name
    return None


def _dynamic_imports() -> dict[Path, set[str]]:
    """app/ 下所有 importlib.import_module 的目标模块 → 出现在哪些文件。"""
    found: dict[Path, set[str]] = {}
    for py in sorted((ROOT / "app").rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        package = _package_of(py)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            is_import_module = (
                (isinstance(fn, ast.Attribute) and fn.attr == "import_module")
                or (isinstance(fn, ast.Name) and fn.id == "import_module")
            )
            if not is_import_module or not node.args:
                continue
            name = _resolve(node.args[0], package)
            if name:
                found.setdefault(py, set()).add(name)
    return found


def test_every_dynamic_import_is_declared_in_spec():
    """动态导入的模块必须写进 spec 的 hiddenimports，否则装了跑不起来。"""
    declared = _spec_hiddenimports()
    missing: list[str] = []
    for py, names in _dynamic_imports().items():
        for name in sorted(names):
            if name not in declared:
                missing.append(f"{py.relative_to(ROOT)} 动态导入 {name}，"
                               f"但 experientia.spec 的 hiddenimports 未声明")
    assert not missing, "\n".join(missing)


def test_mdi_map_is_the_known_dynamic_import():
    """把已知的那一处钉住：守卫本身若因重构失效，这条会先响。"""
    found = {n for names in _dynamic_imports().values() for n in names}
    assert "app.gui._mdi_map" in found, (
        "没扫到 app.gui._mdi_map 的动态导入——qt_icons 的惰性加载被改了？"
        "若已改成静态 import，可删除 spec 里对应的 hiddenimports 及本测试"
    )


def test_declared_hiddenimports_resolve_to_real_files():
    """声明的模块必须真实存在（防拼写错误：写错了 PyInstaller 只 warning）。"""
    for name in sorted(_spec_hiddenimports()):
        rel = name.replace(".", "/")
        if (ROOT / f"{rel}.py").exists() or (ROOT / rel / "__init__.py").exists():
            continue
        # PySide6.* 等第三方模块不在仓库里，跳过
        if not name.startswith("app."):
            continue
        raise AssertionError(f"spec 声明了不存在的模块：{name}")
