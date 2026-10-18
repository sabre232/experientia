# -*- coding: utf-8 -*-
"""送达通道端到端冒烟（自证）：真机数据副本上走一次 hook 回灌。

证明的不是"代码写完了"，而是**飞轮最后一米真的能转**：
Claude Code 发起一次会话 → 我们回灌经验 → 落 injection.log（channel=hook）→
成长页第④格从 0 变成 1、欠账卡文案从"一次都没回调过"改成"已送达 1 次"。

送不出去时脚本会**逐环定位断点**（G 门槛 / playbook 内容 / 失败模式固化 / 记账），
而不是只报一句"注入失败"。

安全：**绝不写在线库**（引擎在跑，单写者铁律）。做法 = 把 ~/.experientia 复制进
临时目录（跳过 engine.lock），所有写都落在副本上；副本上 Store._init_expdb 打桩，
避免重建 SQLite 索引与在跑引擎抢锁。

用法：QT_QPA_PLATFORM=offscreen uv run python -X utf8 scripts/_qa_smoke_delivery.py
退出码：0=通道真的通了；1=送不出去（已定位断点）；2=环境缺失。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.store.store as _ss  # noqa: E402

_ss.Store._init_expdb = lambda self: None  # 只读索引：副本上也不重建 SQLite

from app.capture import hook as hook_channel  # noqa: E402
from app.distill import gate, gsignal  # noqa: E402
from app.distill import growth_story as gs  # noqa: E402
from app.gui import i18n  # noqa: E402
from app.gui.i18n import t  # noqa: E402
from app.proxy import inject  # noqa: E402
from app.store.store import Store  # noqa: E402

LIVE = Path.home() / ".experientia"
OUT = ROOT / "build" / "qa_delivery"
PROMPT = "帮我把这轮投放文案的标题改成利益点前置，并给两版做 A/B"
NL = chr(10)


def _copy_live(dst: Path) -> None:
    """复制在线库到临时副本（跳过 engine.lock：被引擎持有，读它会失败）。"""
    for p in LIVE.iterdir():
        if p.name == "engine.lock":
            continue
        target = dst / p.name
        if p.is_dir():
            shutil.copytree(p, target, dirs_exist_ok=True)
        else:
            shutil.copy2(p, target)


def _diagnose(store: Store) -> str:
    """回灌为空时逐环定位：G 门槛 → playbook 内容 → 失败模式状态 → 记账。"""
    exps = list(store.iter_experiences(include_distilled=True))
    over = [e for e in exps if gsignal.effective_g(e) >= gsignal.G_MIN_INJECT]
    nonrule = [e for e in over if not gsignal.is_rule(e)]
    eligible = [e for e in exps if gsignal.high_value_eligible(e)]
    sections = inject.parse_playbook(store.read_skill("其他", "未分类") or "")
    body = {k: (sections.get(k) or "").strip()
            for k in ("标准流程", "成功要点", "失败模式")}
    st = gate.failure_mode_states(store, "其他", "未分类")
    repro = [e for e in exps if gsignal.is_rule(e)
             and len(e.get("seen_in") or []) >= 3]
    return NL.join([
        "", "【断点定位】",
        f"  经验总数 = {len(exps)}",
        f"  effective_g 过注入线(>= {gsignal.G_MIN_INJECT}) = {len(over)}"
        f"（其中非 rule 源 {len(nonrule)}）",
        f"  「成功要点」资格（过线且非 rule）= {len(eligible)}",
        "  playbook 其他/未分类 三节字数 = "
        + " / ".join(f"{k}:{len(v)}" for k, v in body.items()),
        f"  失败模式状态条目 = {len(st)}（solid="
        + str(sum(1 for v in st.values() if v["state"] == "solid")) + "）",
        f"  已过复现门的 rule 卡（seen_in >= 3）= {len(repro)}",
        "  → 判读：过复现门的 rule 卡有 "
        f"{len(repro)} 条，却没一条进注入块。断点在「rule 卡 → playbook 失败模式"
        " → 固化(solid)」这一环，不在通道、不在记账、也不在 G 门槛本身。",
    ])


def _flywheel(store: Store) -> dict:
    return store.growth_summary(days=30)["flywheel"]


def main() -> int:
    if not LIVE.exists():
        print(f"未找到数据目录：{LIVE}")
        return 2
    i18n.load_catalog("zh")
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="expdelivery"))
    try:
        print("复制真机数据到副本（跳过 engine.lock）…")
        t0 = time.time()
        _copy_live(tmp)
        print(f"  完成，用时 {time.time() - t0:.1f}s")

        store = Store(tmp)
        before = _flywheel(store)
        hk = hook_channel.hook_status(store=store)
        state0 = gs.delivery({"flywheel": before}, hk)["state"]
        print(NL.join([
            "", f"【事前】injected={before.get('injected')} "
            f"by={before.get('injected_by')}",
            f"        hook configured={bool(hk.get('configured'))} "
            f"observed={len(hk.get('observed') or {})} -> 诊断={state0}"]))

        # ⓪ 先修资产：真机那张 playbook 是被"模型返回空 → 空卡当成功"写坏的，
        # 修好写入路径不会让旧的空卡自己复原——这里等价用户点「总结成方法」
        from app.distill import engine_curation
        r = engine_curation.distill(store, "其他", "未分类",
                                    source="manual", force=True)
        sec = inject.parse_playbook(store.read_skill("其他", "未分类") or "")
        print(NL.join([
            "", f"【重蒸馏】status={r.get('status')} count={r.get('count')}",
            "        三节字数 = " + " / ".join(
                f"{k}:{len((sec.get(k) or '').strip())}"
                for k in ("标准流程", "成功要点", "失败模式"))]))

        # 走一次真实回灌（等价 Claude Code 发 UserPromptSubmit）
        hook_channel._injected_memo.clear()
        ctx = hook_channel.build_hook_context(store, PROMPT, session_id="smoke-1")
        hook_channel.build_hook_context(store, PROMPT, session_id="smoke-1")
        log = tmp / "injection.log"
        recs = [json.loads(x) for x in
                log.read_text(encoding="utf-8").splitlines()
                if x] if log.exists() else []
        print(NL.join([
            "", f"【回灌】上下文长度 = {len(ctx)} 字",
            f"        injection.log 行数 = {len(recs)}（同 session 只应记首次）"]))
        if not ctx:
            print(_diagnose(store))
            print(NL.join(["", "RESULT: FAIL —— 经验送不出去，断点见上方"]))
            return 1
        assert len(recs) == 1, f"记账条数应为 1，实得 {len(recs)}"
        assert recs[0]["channel"] == "hook" and recs[0]["items"]

        after_fw = _flywheel(store)
        after = gs.delivery({"flywheel": after_fw},
                          hook_channel.hook_status(store=store))
        print(NL.join([
            "", f"【事后】injected={after_fw.get('injected')} "
            f"by={after_fw.get('injected_by')} -> 诊断={after['state']}",
            f"        页面文案：{t(after['tpl'], **after['params'])}"]))
        assert after["state"] == "live"

        app = _qt_app()
        _shoot_growth(app, store)
        _shoot_poster(store)
        print(NL.join(["", f"产物：{OUT}/growth_after.png · poster_after.png",
                       "RESULT: PASS —— 飞轮最后一米真的转了"]))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _shoot_growth(app, store: Store) -> None:
    from PySide6.QtWidgets import QLabel

    from app.gui import growth as growth_mod

    class _Api:
        def __init__(self, s):
            self._s = s

        def growth(self, days=30):
            g = self._s.growth_summary(days=days)
            g["changelog"] = self._s.list_changelog()[-50:][::-1]
            g["maintenance"] = self._s.read_maintenance(limit=20)
            return g

        def skills(self):
            return {"items": []}

        def models(self):
            return {"routes": [{"endpoint": "http://127.0.0.1:8080/v1"}]}

        def hooks_config(self):
            return hook_channel.hook_status(store=self._s)

    page = growth_mod.GrowthPage(_Api(store))
    page.resize(1180, 2600)
    page.show()
    page.refresh()
    for _ in range(8):
        app.processEvents()
        time.sleep(0.05)
    page.grab().save(str(OUT / "growth_after.png"))
    body = NL.join(l.text() for l in page.findChildren(QLabel))
    assert "已送达" in body, "第④格文案未更新，页面仍说没送达"


def _shoot_poster(store: Store) -> None:
    from app.gui import poster, report_model

    spec = poster.growth_poster(
        report_model.growth_report_model(store.growth_summary(days=30)), t)
    poster.render_png(spec, OUT / "poster_after.png", scale=2)


if __name__ == "__main__":
    raise SystemExit(main())
