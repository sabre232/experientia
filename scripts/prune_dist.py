"""PyInstaller 产物瘦身（启动优化配套，pyinstaller 之后调用）：

    uv run python scripts/prune_dist.py

纯 Widgets 应用用不到的 Qt 运行时资产一律删除，减少 onedir 冷启动时
DLL/文件扫描（含杀软实时防护）数量与体积：
- plugins/networkinformation —— QtNetwork 用；本应用不 import QtNetwork
- plugins/tls             —— QtNetwork SSL 后端；httpx 走纯 Python ssl
- translations            —— Qt 内置控件词条；本应用自带 i18n(.mo)，无原生对话框

布局兼容 PyInstaller 6 onedir（dist/Experientia/_internal/…）；路径缺失
静默跳过，不视为失败。
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "dist" / "Experientia"

_RELATIVE = (
    "_internal/PySide6/plugins/networkinformation",
    "_internal/PySide6/plugins/tls",
    "_internal/PySide6/translations",
)


def _dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> int:
    if not TARGET.exists():
        print(f"dist 不存在：{TARGET}（先跑 pyinstaller experientia.spec）")
        return 0
    before = _dir_bytes(TARGET)
    removed = 0
    for rel in _RELATIVE:
        p = TARGET / rel
        if p.exists():
            removed += _dir_bytes(p)
            shutil.rmtree(p)
            print(f"removed {rel}")
    after = _dir_bytes(TARGET)
    print(f"dist size: {before/1e6:.1f} MB -> {after/1e6:.1f} MB "
          f"(省 {max(0, before-after)/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
