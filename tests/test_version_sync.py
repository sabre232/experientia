"""版本一致性护栏：app/version.py 与 pyproject.toml 不许漂移。

发版链：tag 用 semver，`app/version.py` 的 VERSION 必须与 pyproject 一致——
两处手写各改各的曾真实发生过（local_api/设置页各写一份 1.0.0 的历史），
这里用测试钉死唯一来源。
"""

import re
from pathlib import Path

from app.version import VERSION

ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m, "pyproject.toml 无 version 字段"
    assert m.group(1) == VERSION, (
        f"版本漂移：pyproject {m.group(1)} != app/version.py {VERSION}")


def test_version_shape():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)
