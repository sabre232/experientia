"""E-2：记忆 skill 模板生成（SKILL.md 结构完整性）。"""

from app import memory_skill as ms


def test_skill_has_standard_frontmatter_and_sections(tmp_path):
    p = ms.write_memory_skill(tmp_path)
    assert p.parent.name == ms.SKILL_DIRNAME
    md = p.read_text(encoding="utf-8")
    assert md.startswith("---\nname: experientia-memory")
    assert "description:" in md
    for section in ("## When to Use", "## Procedure", "## Pitfalls",
                    "## Verification"):
        assert section in md
    # 只操作 .repo_memory/ 且不复制正文/不写凭据的约束必须显式出现
    assert ".repo_memory/" in md
    assert "NEVER" in md


def test_skill_write_idempotent(tmp_path):
    p1 = ms.write_memory_skill(tmp_path)
    p2 = ms.write_memory_skill(tmp_path)
    assert p1 == p2
    assert p1.read_text(encoding="utf-8") == ms.SKILL_MD


def test_memory_reminder_no_project_or_shallow(tmp_path):
    assert ms.memory_reminder({}) is None
    assert ms.memory_reminder({"project": "/w", "req_count": 1}) is None


def test_memory_reminder_deep_without_repo_memory(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    text = ms.memory_reminder({"project": str(proj), "req_count": 5})
    assert text is not None and ".repo_memory/" in text


def test_memory_reminder_suppressed_when_repo_memory_exists(tmp_path):
    proj = tmp_path / "proj2"
    (proj / ".repo_memory").mkdir(parents=True)
    assert ms.memory_reminder({"project": str(proj), "req_count": 5}) is None


def test_memory_reminder_correction_counts_as_signal(tmp_path):
    proj = tmp_path / "proj3"
    proj.mkdir()
    assert ms.memory_reminder(
        {"project": str(proj), "req_count": 1, "correction_hits": 1}) is not None


def test_maybe_remind_off_by_default(tmp_path, monkeypatch):
    """E-2 推送默认关（config.features.memory_reminder=False）。"""
    from app.store.store import Store

    s = Store(data_dir=tmp_path / "data1")
    s.ensure_layout()
    called = []
    monkeypatch.setattr("app.notify.push",
                        lambda store, ntype, title, body="", target="": called.append(ntype))
    proj = tmp_path / "proj_off"
    proj.mkdir()
    ms.maybe_remind_store(s, {"project": str(proj), "req_count": 3})
    assert not called


def test_maybe_remind_pushes_when_enabled(tmp_path, monkeypatch):
    from app.store.store import Store

    s = Store(data_dir=tmp_path / "data2")
    s.ensure_layout()
    s.save_config({"features": {"memory_reminder": True}})
    called = []
    monkeypatch.setattr("app.notify.push",
                        lambda store, ntype, title, body="", target="": called.append(ntype))
    proj = tmp_path / "proj_on"
    proj.mkdir()
    ms.maybe_remind_store(s, {"project": str(proj), "req_count": 3})
    assert called == ["system_notice"]
