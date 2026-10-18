"""安装包脚本（scripts/installer.iss）的收口契约。

为什么值得单独把这几条钉住：安装包脚本的错误有个共同特征——**编译期不报错、
当天安装也成功**，只在"已经发给用户之后"才暴露：

- AppId 写错 → 旧版卸不掉、新版装成两份，两个副本还会共抢 ~/.experientia。
- [Files] 源指错 → 打出一个空壳安装包（或把源码目录当产物发出去）。
- 引用的文件不存在 → 只有跑构建时才失败，而不是提交时。
- 中文语言文件丢了 → 向导**静默**退回纯英文（FileExists 守卫会兜住，代价是没人发现）。

所以这几条按"能静默出错"的标准写成断言。实际踩过 AppId 那条。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISS = ROOT / "scripts" / "installer.iss"


def _text() -> str:
    return ISS.read_text(encoding="utf-8")


def _value(name: str) -> str:
    """取 [Setup] 段里 `name=` 的值（脚本里这些键都写在行首、独占一行）。"""
    prefix = f"{name}="
    for line in _text().splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    raise AssertionError(f"installer.iss 里找不到 {name}=")


def test_app_id_brace_escaping():
    """AppId 必须写成 `{{GUID}` —— 首尾花括号数**不对称**才对。

    Inno 把 `{{` 当转义（转成一个字面 `{`），而单个 `}` 本身就是字面量。
    所以 `{{GUID}` 才等于 `{GUID}`；写成 `{{GUID}}` 会得到 `{GUID}}`，
    注册表卸载键变成 `{GUID}}_is1`——编译不报错、安装也成功，但身份已歪。

    这条断言的存在意义就是挡住"顺手把它修对称"的下一次编辑。
    """
    app_id = _value("AppId")
    assert app_id.startswith("{{"), f"缺少转义左花括号：{app_id}"
    assert not app_id.endswith("}}"), f"多了一个右花括号：{app_id}"
    assert not app_id.endswith("{{"), f"转义写反了：{app_id}"

    guid = app_id[2:-1]
    assert len(guid) == 36 and guid.count("-") == 4, f"不是 GUID 形态：{app_id}"
    assert guid.upper() == guid, f"AppId 里的 GUID 应为大写：{app_id}"


def test_app_id_is_a_guid_not_a_name():
    """AppId 必须是 GUID 而非可读名字——可读名字改一次就断代。"""
    guid = _value("AppId")[2:-1]
    assert all(c in "0123456789ABCDEF-" for c in guid), guid


def test_payload_source_is_build_output():
    """[Files] 的源必须是 PyInstaller 的 onedir 产物，不能指到源码目录。"""
    assert r"..\dist\Experientia\*" in _text()


def test_referenced_repo_files_exist():
    """脚本引用的每一份仓库文件都要真实存在（否则只有构建时才炸）。"""
    for rel in ("LICENSE", "LICENSE-AGPL", "README_zh.md",
                "assets/icon_windows.ico",
                "scripts/languages/ChineseSimplified.isl"):
        assert (ROOT / rel).exists(), f"installer.iss 引用了不存在的文件：{rel}"


def test_chinese_language_is_wired_behind_guard():
    """简体中文必须接线，且用 FileExists 守卫住。

    这份 .isl 不是 Inno 自带的（winget 那个包只装了 29 种语言、恰好没有中文），
    是从官方仓库收进仓库跟着版本走的——所以它有可能在别处丢失，守卫让那种情况
    退回英文向导而不是直接编译失败。
    """
    text = _text()
    assert "compiler:Default.isl" in text, "英文基线语言缺失"
    assert r"languages\ChineseSimplified.isl" in text, "中文语言未接线"
    assert "FileExists" in text, "中文语言缺少 FileExists 守卫"


def test_excludes_bytecode():
    """产物里不该混进 .pyc（打包机上的字节码进用户机器只会让人困惑）。"""
    assert "*.pyc" in _text()
