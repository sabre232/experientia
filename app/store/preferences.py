"""`Store` 的「偏好画像」域 mixin。

从 `store.py` 的 `class Store`（2796 行 / 148 方法）拆出的
**第一个域**，只做不动语义的搬家。约定：

1. 方法体逐字搬移，签名与返回值一律不变；
2. 共享状态（`data_dir`、`read_text_cached` / `invalidate_cache`、`_write_lock`）
   留在 `Store` 主体，mixin 通过 `self` 访问，**不复制状态**；
3. 需要模块级小工具时从 `._shared` 取，不 import `store.py`（避免循环导入）。
"""

from __future__ import annotations

from pathlib import Path

from ._shared import _safe


class PreferencesMixin:
    """偏好画像 md 的路径 / 读 / 写 / 列主干。"""

    def preferences_path(self, trunk: str) -> Path:
        """偏好 md 的路径句柄（溯源要读它的最后写入时刻，故给路径而非内容）。"""
        return self.data_dir / "preferences" / (_safe(trunk) + ".md")

    def read_preferences(self, trunk: str) -> str | None:
        return self.read_text_cached(self.preferences_path(trunk))

    def write_preferences(self, trunk: str, md: str) -> Path:
        path = self.preferences_path(trunk)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写——原地 write_text 崩在中间会留下半截
        # 偏好画像，而读侧不跳过坏 md，直接展示半个文件给用户
        self._write_tmp_rename(path, md)
        self.invalidate_cache(path)
        return path

    def list_preference_trunks(self) -> list[str]:
        root = self.data_dir / "preferences"
        if not root.is_dir():
            return []
        return sorted(f.stem for f in root.glob("*.md"))
