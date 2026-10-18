"""i18n：gettext 封装。

- 所有用户可见字符串走 t("key")，禁止硬编码进组件；key = 中文源串
  （zh 为源语言，pybabel extract 自动提取 t("…") 调用生成 pot）
- locale 存 config.json 的 `locale` 字段；默认 = 系统 locale 检测
  （zh*→zh ja*→ja ko*→ko fr*→fr de*→de es*→es 其余→en）
- 切换语言 = load_catalog() 重新加载 .mo + GUI 外壳重建页面
- 加语言 = 加一个 locales/<lang>/LC_MESSAGES/ 目录 + SUPPORTED 加一项，不改结构
- 资产/经验/导出内容不翻译，本模块只管 UI 层
"""

from __future__ import annotations

import gettext
import logging
import os
from pathlib import Path

logger = logging.getLogger("experientia.i18n")

LOCALES_DIR = Path(__file__).parent / "locales"
DOMAIN = "messages"

SUPPORTED = ("zh", "en", "ja", "ko", "fr", "de", "es")
_PREFIX = {c[:2]: c for c in SUPPORTED}

_current = "zh"
_catalog: gettext.NullTranslations | gettext.GNUTranslations | None = None


def detect_system_locale() -> str:
    """系统 locale → 支持语言码。"""
    import locale as _locale_mod

    loc: str | None = None
    try:
        loc = (_locale_mod.getlocale()[0] or _locale_mod.getdefaultlocale()[0])
    except Exception:
        loc = None
    if not loc:
        for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
            val = os.environ.get(var)
            if val:
                loc = val
                break
    if loc:
        code = loc.split(".")[0].split("-")[0].split("_")[0].lower()
        return _PREFIX.get(code[:2], "en")
    return "en"


def load_catalog(lang: str | None = None) -> str:
    """加载语言目录，返回实际生效的语言码（.mo 缺失 → 回退 en）。"""
    global _current, _catalog
    if not lang:
        lang = _current
    if lang not in SUPPORTED:
        lang = "en"
    mo = LOCALES_DIR / lang / "LC_MESSAGES" / (DOMAIN + ".mo")
    if mo.exists():
        try:
            with open(mo, "rb") as fh:
                _catalog = gettext.GNUTranslations(fh)
            _current = lang
            return lang
        except Exception as exc:
            logger.warning("i18n: 加载 %s 目录失败，回退 en: %s", mo, exc)
    _catalog = gettext.NullTranslations()
    _current = "en"
    return "en"


def current_language() -> str:
    return _current


def t(key: str, **kwargs) -> str:
    """取词：key 为中文源串；支持 {name} 占位符。

    目录未加载也要完成占位符替换——早先直接 return key，带参模板会把
    "{en} 次任务" 原样打到界面上（占位符泄漏比缺翻译更难看）。"""
    if _catalog is None:
        return key.format(**kwargs) if kwargs else key
    out = _catalog.gettext(key)
    if kwargs:
        try:
            out = out.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return out
