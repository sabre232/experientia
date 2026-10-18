"""i18n 测试：zh 源语言恒等、en 翻译、占位符、回退、系统检测。"""

import re
from pathlib import Path

import pytest

from app.gui import i18n

GUI_DIR = Path(__file__).resolve().parent.parent / "app" / "gui"


@pytest.fixture(autouse=True)
def _reset():
    i18n.load_catalog("zh")
    yield
    i18n.load_catalog("zh")


def test_zh_identity():
    assert i18n.load_catalog("zh") == "zh"
    assert i18n.t("越用越懂你的 AI 搭档") == "越用越懂你的 AI 搭档"
    assert i18n.t("运行中") == "运行中"


def test_en_translation():
    assert i18n.load_catalog("en") == "en"
    assert i18n.t("越用越懂你的 AI 搭档") == "The AI partner that knows you better with every use"
    assert i18n.t("经验库") == "Experiences"


def test_placeholder_formatting():
    i18n.load_catalog("en")
    out = i18n.t("文件捕获已就绪：{n} 个 agent 会话目录已探测，零配置直接开始记", n=4)
    assert "4" in out and "{n}" not in out
    i18n.load_catalog("zh")
    out = i18n.t("「{name}」连续 {n} 轮解析失败，可能格式已变", name="trae", n=3)
    assert "trae" in out and "3" in out


def test_unknown_language_falls_back_en():
    assert i18n.load_catalog("xx") == "en"
    assert i18n.t("越用越懂你的 AI 搭档") == "The AI partner that knows you better with every use"


def test_missing_mo_falls_back_en(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "LOCALES_DIR", tmp_path)
    assert i18n.load_catalog("zh") == "en"
    assert i18n.t("越用越懂你的 AI 搭档") == "越用越懂你的 AI 搭档"  # NullTranslations 恒等


def test_detect_system_locale(monkeypatch):
    monkeypatch.setattr("locale.getlocale", lambda *a, **k: ("en_US", "UTF-8"))
    monkeypatch.setattr("locale.getdefaultlocale", lambda *a, **k: ("en_US", "UTF-8"))
    assert i18n.detect_system_locale() == "en"
    monkeypatch.setattr("locale.getlocale", lambda *a, **k: ("zh_CN", "UTF-8"))
    monkeypatch.setattr("locale.getdefaultlocale", lambda *a, **k: ("zh_CN", "UTF-8"))
    assert i18n.detect_system_locale() == "zh"


def test_current_language_tracks_load():
    assert i18n.load_catalog("en") == "en"
    assert i18n.current_language() == "en"
    assert i18n.load_catalog("zh") == "zh"
    assert i18n.current_language() == "zh"


# ---------- 覆盖守卫：防"英文环境漏中文"残留 ----------

def _all_t_keys() -> set[str]:
    """AST 提取 GUI 源码里 t("字面量") 的键（docstring/注释不算）。"""
    import ast

    keys: set[str] = set()
    for py in sorted(GUI_DIR.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "t"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
    return keys


def _read_po(lang: str) -> dict[str, tuple[str, bool]]:
    from babel.messages.pofile import read_po

    path = GUI_DIR / "locales" / lang / "LC_MESSAGES" / "messages.po"
    return {m.id: (m.string or "", bool(m.fuzzy))
            for m in read_po(open(path, "rb")) if m.id}


def _growth_story_templates() -> set[str]:
    """叙事展示串：`app/distill/growth_story.py` 的模块级模板常量。

    为什么单列一检：这些串不以 `t("字面量")` 形式出现（模块只存模板 + 参数，
    由 `localize()` 套 `t()`），`_all_t_keys()` 抓不到——漏补译文不会让任何测试
    变红，只会在非中文界面静默回落中文（周报引导段即此型）。
    """
    import ast

    src = (GUI_DIR.parent / "distill" / "growth_story.py").read_text(encoding="utf-8")
    out = set()
    for node in ast.parse(src).body:
        if not (isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.isupper()):
            continue
        try:
            val = ast.literal_eval(node.value)
        except ValueError:
            continue
        if isinstance(val, str) and any("\u4e00" <= c <= "\u9fff" for c in val):
            out.add(val)
    return out


def test_growth_story_templates_translated_in_all_catalogs():
    """叙事模板全语有译文（非空、非模糊）——防"引擎侧加串、词典没跟上"。"""
    keys = _growth_story_templates()
    assert keys, "叙事模板常量扫描为空，测试环境异常"
    for lang in i18n.SUPPORTED:
        cat = _read_po(lang)
        missing = keys - set(cat)
        assert not missing, f"{lang} 缺叙事模板词条: {sorted(missing)[:6]}"
        bad = {k for k in keys & set(cat) if not cat[k][0] or cat[k][1]}
        assert not bad, f"{lang} 叙事模板未翻译/模糊: {sorted(bad)[:6]}"


def _connect_page_dynamic_keys() -> set[str]:
    """接入页的动态 t() 键：`_TOOL_DESC` 的值（各工具接入指引长文）与
    `_TOOL_GUIDE` 的 kind 标签（环境变量 / 配置文件 / 软件内设置）。

    为什么单列一检：与叙事模板同型——这些串以"字典存 msgid + 运行时
    `t(字典值)`"出现，`_all_t_keys()` 抓不到（connect_page.py 的注释自己
    写着"AST 抓不到须手工登记 i18n"）。漏补译文不会让任何测试变红，只会在
    非中文界面静默回落中文。
    `_TOOL_GUIDE` 的 target（文件名）/ code（配置片段）是数据不译，只取 kind。
    """
    import ast

    src = (GUI_DIR / "connect_page.py").read_text(encoding="utf-8")
    out: set[str] = set()
    for node in ast.parse(src).body:
        if not (isinstance(node, ast.Assign) and node.targets
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("_TOOL_DESC", "_TOOL_GUIDE")):
            continue
        try:
            val = ast.literal_eval(node.value)
        except ValueError:
            continue
        if not isinstance(val, dict):
            continue
        if node.targets[0].id == "_TOOL_DESC":
            out |= {v for v in val.values() if isinstance(v, str)}
        else:  # (kind, target, code) 三元组
            out |= {v[0] for v in val.values()
                    if isinstance(v, tuple) and v and isinstance(v[0], str)}
    return out


def test_connect_page_dynamic_keys_translated_in_all_catalogs():
    """接入页动态键全语有译文（非空、非模糊）。

    这 18 条（10 条接入指引长文 + 8 个 kind 标签）实测**已全部登记且已译**——
    本测试把"已成立的事实"钉住：将来任何人往 `_TOOL_DESC` 加新工具的指引
    长文而忘记补 7 语译文时，这里会红，而不是让英文用户对着中文长文抓瞎。
    """
    keys = _connect_page_dynamic_keys()
    assert keys, "接入页动态键扫描为空，测试环境异常"
    # 10 条接入指引长文 + 3 个去重后的 kind 标签（环境变量/配置文件/软件内设置）
    assert len(keys) >= 13, f"接入页动态键数量异常变少：{len(keys)}"
    for lang in i18n.SUPPORTED:
        cat = _read_po(lang)
        missing = keys - set(cat)
        assert not missing, f"{lang} 缺接入页词条: {sorted(missing)[:6]}"
        bad = {k for k in keys & set(cat) if not cat[k][0] or cat[k][1]}
        assert not bad, f"{lang} 接入页词条未翻译/模糊: {sorted(bad)[:6]}"


def test_achievement_display_names_are_localized():
    """成就展示名以 params 塞进 tpl（"{name}解锁了：…"），必须单独过 tf。

    否则英文界面会出现 "老练 unlocked" 这种半中半英——`_slot` 只翻 tpl，
    坑位里的值得自己去查词。类别名（{who}）是用户数据，不翻译，本例不校验。
    """
    from app.distill import growth_story as gs

    g = {"stage": {"sessions": 3}}
    story = gs.build(g, unlocked=[
        {"type": "veteran", "scope": "codex/营销/文案写作"},
        {"type": "legacy", "scope": "global"}])
    zh_lines = gs.localize(story, i18n.t)["milestones"]["unlocked"]
    assert "老练" in zh_lines[0] and "传承" in zh_lines[1]

    i18n.load_catalog("en")
    lines = gs.localize(story, i18n.t)["milestones"]["unlocked"]
    assert "Seasoned" in lines[0] and "Legacy" in lines[1]
    assert "老练" not in lines[0] and "传承" not in lines[1]


def test_every_t_key_translated_in_all_catalogs():
    """zh 恒等 + 其余 6 语：键齐全、非空、非模糊。"""
    keys = _all_t_keys()
    assert keys, "GUI 源码里应能找到 t() 调用"
    for lang in i18n.SUPPORTED:
        cat = _read_po(lang)
        missing = keys - set(cat)
        assert not missing, f"{lang} 目录缺键: {sorted(missing)[:10]}"
        if lang == "zh":
            continue
        bad = {k for k in keys & set(cat) if not cat[k][0] or cat[k][1]}
        assert not bad, f"{lang} 未翻译/模糊: {sorted(bad)[:10]}"


def test_compiled_mo_is_fresh():
    """直接加载编译产物 .mo（运行时真实路径）：键齐全且非空，防 .po 更新后忘记重编译。"""
    import gettext

    keys = _all_t_keys() | _growth_story_templates()
    for lang in i18n.SUPPORTED:
        mo_path = GUI_DIR / "locales" / lang / "LC_MESSAGES" / "messages.mo"
        assert mo_path.exists(), f"{lang} 缺编译产物 .mo"
        with open(mo_path, "rb") as fh:
            cat = gettext.GNUTranslations(fh)._catalog
        missing = [k for k in keys if k not in cat]
        assert not missing, f"{lang} 的 .mo 缺键: {sorted(missing)[:10]}"
        if lang == "zh":
            bad = [k for k in keys if cat[k] != k]
            assert not bad, f"zh 的 .mo 应恒等，异常: {sorted(bad)[:5]}"
        else:
            empty = [k for k in keys if not cat[k]]
            assert not empty, f"{lang} 的 .mo 有空译文: {sorted(empty)[:10]}"


def test_all_placeholders_are_subset_of_zh():
    """任何语言翻译里出现的 {占位符} 必须在 zh 源串里都有——否则调用方按源串传参会 KeyError。"""
    zh = _read_po("zh")
    for lang in i18n.SUPPORTED:
        if lang == "zh":
            continue
        cat = _read_po(lang)
        for key in zh.keys() & cat.keys():
            zh_ph = set(re.findall(r"\{(\w+)\}", key))  # key 即 zh 源串
            extra = set(re.findall(r"\{(\w+)\}", cat[key][0])) - zh_ph
            assert not extra, f"{lang} 翻译多出占位符 {key!r}: {sorted(extra)}"


# ---------- "照抄源串"护栏（漏翻最后形态：非 zh 语言 msgstr 原样等于中文 msgid，
# 等于没翻译；R1 六语接入段即此型） ----------
#
# 例外仅开放给 ja 的「日文汉字同形合法词」（msgid=msgstr 在日语里就是正确译文，
# 见  ja 保留说明：保存/通知/生成中…/粒度/生成/方法/使用/管理/v{v}·更新{d}/万/正常）。
_ZH_SAME_ALLOW: dict[str, set[str]] = {
    "en": set(),
    "fr": set(),
    "de": set(),
    "es": set(),
    "ja": {"保存", "通知", "生成中…", "粒度", "生成", "方法",
           "使用", "管理", "v{v} · 更新 {d}", "万", "正常", "結果",
           "成功", "操作"},
    "ko": set(),
}


def test_locale_translation_not_equal_zh_source():
    """非 zh 语言禁止 msgstr == 中文源串（照抄源=没翻）；ja 汉字同形词白名单例外。

    只查含中文的 msgid——纯英文专名键（Hooks/Anthropic API/accounting…）
    msgstr=msgid 属"生态词保留"，不是照抄中文源串。"""
    for lang in i18n.SUPPORTED:
        if lang == "zh":
            continue
        allow = _ZH_SAME_ALLOW.get(lang, set())
        cat = _read_po(lang)
        bad = [mid for mid, (s, _f) in cat.items()
               if s and s == mid and mid not in allow
               and any("\u4e00" <= ch <= "\u9fff" for ch in mid)]
        assert not bad, f"{lang} 有照抄源串（未翻）: {sorted(bad)[:12]}"


# ---------- "复制英文"护栏（事故：非 en 语言多条 msgstr 直接等于 en 译文，
# fr 48 / de 43 / es 43 / ja 19 / ko 33 条，R4/R7 已清理） ----------

# 允许 msgstr == en 的例外（跨语言技术词/同形词/占位，各语白名单独立维护）。
_EN_COPY_ALLOW: dict[str, set[str]] = {
    "fr": {
        "类型", "端点", "版本", "{n} 个", "{n} 个 agent", "{n} 个会话",
        "通知", "（{n} 条）",
        "采集", "做法", "全局", "溯源", "万", "正常",  # 技术词/惯用借词（sessions=会话）
        "助手",  # 法语本词即 assistant（与 en 同形，非漏翻）
    },
    "de": {
        "Claude Code：ANTHROPIC_BASE_URL={url}", "版本", "{n} 个", "（{n} 条）",
        "名称", "系统", "全局", "万", "正常", "详情", "详情：{name}",
        "状态：正常",  # 德语本词即 Version/System/Normal/Details/Status
        "{q}？{a}",  # 纯标点模板：德语问句同样用 "? " 连接，无可译内容
    },
    "es": {
        "端点", "Claude Code：ANTHROPIC_BASE_URL={url}", "{n} 个", "（{n} 条）",
        "全局", "万", "正常",
    },
    "ja": set(),
    "ko": {
        "Claude Code：ANTHROPIC_BASE_URL={url}",  # 专名（环境变量）
        "{q}？{a}",  # 纯标点模板：韩语问句同样用 "? " 连接，无可译内容
    },
}


def _find_en_copy(cat: dict[str, tuple[str, bool]],
                  en: dict[str, tuple[str, bool]],
                  allow: set[str]) -> list[str]:
    """返回 lang 目录里 msgstr 原样等于 en 译文、且不在白名单的 msgid。"""
    en_map = {mid: s for mid, (s, _) in en.items() if s}
    bad = []
    for mid, (s, _fuzzy) in cat.items():
        e = en_map.get(mid)
        # 跳过源语言同形/空/中文未译：仅当 en 有译文、本语译文=占位同形词且 mid!=msgstr 才查
        if s and e and s == e and mid != s and mid not in allow:
            # 再排除整条都是技术符文的（e.g. 两端都是英文专名，en 本就不翻译）
            if mid.isascii() and e.isascii():
                continue
            bad.append(mid)
    return bad


def test_locale_translation_not_plain_en_copy():
    """非 zh/en 语言不得直接复用 en 译文（防批量翻译把 en 当目标语；事故）。"""
    en = _read_po("en")
    for lang in i18n.SUPPORTED:
        if lang in ("zh", "en"):
            continue
        cat = _read_po(lang)
        bad = _find_en_copy(cat, en, _EN_COPY_ALLOW.get(lang, set()))
        assert not bad, f"{lang} 直接复用了 en 译文: {sorted(bad)[:12]}"


def test_en_copy_guard_catches_samples():
    """护栏自检：漏译（msgstr==en）必须被抓，白名单例外与原文同形必须放过。"""
    en = {"保存失败，请重试": ("Save failed, please retry", False),
          "正常": ("Normal", False),
          "Anthropic API": ("Anthropic API", False)}
    # 应命中：不在白名单的整句英文
    cat = {"保存失败，请重试": ("Save failed, please retry", False)}
    assert _find_en_copy(cat, en, set()) == ["保存失败，请重试"]
    # 白名单放过
    cat2 = {"正常": ("Normal", False)}
    assert _find_en_copy(cat2, en, {"正常"}) == []
    # 原文同形（en 不翻译的英文专名）放过
    cat3 = {"Anthropic API": ("Anthropic API", False)}
    assert _find_en_copy(cat3, en, set()) == []


# ---------- 拼接损坏护栏（事故：AI 批量翻译把多个候选写进同一条 msgstr，
# gettext 原样输出成"RoundsroundsNo preference…"，6 语约 58 条）。三种特征：----------
# ① 重复前缀（候选连写：相邻重复如 "표준 절차표준 절차…"，或首段在文中复现）
# ② 超长比（拉丁语译文 >5 倍 msgid 且 >150 字符）
# ③ CJK 译文混入 ≥6 连续英文词（ja/ko 句尾拼英文候选）

_LATIN_RUN = re.compile(
    r"[A-Za-z][A-Za-z'’]*(?:[ ,.;:—\-]+[A-Za-z][A-Za-z'’]*){5,}")


def _dup_prefix(s: str) -> bool:
    if len(s) < 8:
        return False
    half = len(s) // 2
    # 相邻重复：s 开头 k(≥4) 字符立刻重现（短候选连写，允许大小写变体，
    # 如 fr "Allers-retoursallers-retours…"）
    if any(s[:k].casefold() == s[k:2 * k].casefold() for k in range(4, half + 1)):
        return True
    # 首段复现：前 20+ 字符在文中再次出现（多候选连拼，如"RoundsroundsNo…"）
    if len(s) > 40:
        return any(s.count(s[:L]) >= 2 for L in range(20, half + 1))
    return False


def _overlong(mid: str, s: str) -> bool:
    return len(s) > 150 and len(s) > 5 * max(len(mid), 1)


def test_locale_no_concatenation_corruption():
    """全目录扫描三种拼接特征，命中即红（防下次 AI 批量翻译再引入）。"""
    for lang in i18n.SUPPORTED:
        for mid, (s, _fuzzy) in _read_po(lang).items():
            sig = []
            if _dup_prefix(s):
                sig.append("重复前缀")
            if lang in ("en", "fr", "de", "es") and _overlong(mid, s):
                sig.append("超长比")
            if lang in ("ja", "ko", "zh") and _LATIN_RUN.search(s):
                sig.append("混入英文句")
            assert not sig, f"{lang}: {mid[:24]}… 命中 {'+'.join(sig)}: {s[:60]}…"


def test_guards_catch_known_incident_samples():
    """护栏自检：检测器必须抓得住本次事故真实样本，放过正常长短句。"""
    # 正例（应命中）
    assert _dup_prefix("Standard procedureStandard procedureTemplate library coming")
    assert _dup_prefix("표준 절차표준 절차템플릿 라이브러리는 Phase 5에 오픈: 템플릿 선택")
    assert _dup_prefix("Allers-retoursallers-retoursPas encore de profil de préférences")
    assert _dup_prefix("RoundsroundsNo preference profile yet — auto-inducted")
    assert _overlong("轮数", "RoundsroundsNo preference profile yet — auto-inducted "
                     "from your corrections / low-G experiences during distillation"
                     "No failure modes yet — once experiences are distilled, your "
                     "pitfalls settle hereNo rules yet — rules work from day one")
    assert _LATIN_RUN.search("削除後は自動で付与されません。記録は残ります"
                             "Once deleted it won't be attached again; it stays")
    assert _LATIN_RUN.search("삭제 후 자동으로 첨부되지 않으며 기록은 남습니다 "
                             "Once deleted it won't be attached again")
    # 反例（合法译文不得误伤）
    assert not _dup_prefix("It grows with every session, so next time you ask, "
                           "the experience is already at hand")
    assert not _overlong("Hooks 开箱即用：无需等经验积累，添加一个或从模板库导入",
                         "Hooks work from day one (no need to wait for experiences) "
                         "— add one or import from the template library")
    assert not _LATIN_RUN.search("テンプレート本文は中国語の原版を AI で翻訳したもので、"
                                 "表現が不正確な場合があります")
    assert not _LATIN_RUN.search("카테고리별 원클릭 내보내기, 또는 항목 선택"
                                 "(카테고리 간) → 표준 스킬 파일 생성")


def test_rule_tags_have_translations_in_all_langs():
    """规则模板的 tags（Hooks 页领域下拉的数据源）必须全语有词条。

    新增规则 tag 后若忘补 7 语 .po，这里直接给出缺失清单——避免 UI 回退英文。
    """
    import re
    from pathlib import Path

    tpl_root = Path(__file__).resolve().parents[1] / "app" / "rules" / "templates"
    tags: set[str] = set()
    for lang_dir in tpl_root.iterdir():
        if not lang_dir.is_dir():
            continue
        for f in lang_dir.glob("*.md"):
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            m = re.search(r"^tags\s*:\s*(.+)$", text, re.MULTILINE)
            if not m:
                continue
            for tag in m.group(1).split(";"):
                tag = tag.strip()
                if tag:
                    tags.add(tag)
    assert tags, "没扫到任何规则 tag，测试环境异常"
    for lang in i18n.SUPPORTED:
        cat = _read_po(lang)
        missing = sorted(
            tag for tag in tags
            if not cat.get(tag) or not (cat.get(tag) or ("", False))[0])
        assert not missing, f"{lang} 缺规则 tag 词条: {missing}"
