"""experientia-wrap 仓库根启动器（实现见 app/wrap.py，保证 wheel 打包同源）。

用法（仓库内源码运行）：
    python experientia_wrap.py --target deepseek-harness -- deepseek
安装后（pyproject console script）直接用：experientia-wrap …
"""

from __future__ import annotations

import sys

from app.wrap import main  # noqa: E402  # 需在项目根可 import app


if __name__ == "__main__":
    raise SystemExit(main())
