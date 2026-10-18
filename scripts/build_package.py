"""打包脚本（迁移清单）：PyInstaller onedir/windowed 三平台。

用法（仓库根，激活 .venv）：
    python scripts/build_package.py          # 当前平台
    python scripts/build_package.py --clean  # 先清 dist/build

产物：dist/Experientia/（Windows 为 Experientia.exe，macOS 为 .app，Linux 为可执行文件）。

依赖约定：**PyInstaller 必须常驻 `.venv`**（`uv pip install "pyinstaller>=6.0"` 或
`uv sync --extra build`）。曾尝试把它挪出 `.venv`（用 `uv run --with`
按需拉取，省 3.7 MB 磁盘），**已回滚**，原因记在下面，别再试第二次：

1. `uv run --with pyinstaller` 走的是 **ephemeral overlay，该模式不包含项目依赖**——
   只有 `--with` 列出的包。实测 `import httpx` 直接 ModuleNotFound，而 httpx 是
   pyproject 的主依赖。用这条命令打出来的包**缺 fastapi/httpx/pydantic/keyring/
   zstandard/cryptography**，体积会凭空小 25 MB，看着像"优化成功"，实际跑不起来。
   （当时的冒烟抓出来的：GUI 连数据目录都没创建就退出。）
2. 想让 overlay 带上项目依赖，只能把主依赖逐个 `--with` 列一遍——脆且易漏，
   pyproject 一改就得同步。
3. 独立的构建 venv 也不划算：PySide6 一个包 632 MB，复制一遍只为省 3.7 MB。
4. `pygments` 看着像构建期依赖，实测 `import fastapi` 会连带导入它，是运行时依赖，
   也不能拆。

结论：这 3.7 MB 不值得花这些代价，PyInstaller 留在 `.venv` 里。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    args = ["--noconfirm"]
    if "--clean" in sys.argv:
        args.append("--clean")
    cmd = [sys.executable, "-m", "PyInstaller", *args,
           str(ROOT / "experientia.spec")]
    print(">", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)


if __name__ == "__main__":
    main()
