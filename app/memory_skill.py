"""记忆 skill 模板生成（路线图 E-2 第一刀：让 agent 主动读写飞轮/仓库记忆）。

背景（memorax 借鉴 + Agent Skills 开放标准 agentskills.io/anthropics）：
文件捕获把 agent 会话都吸进来，但"agent 下次要不要主动想起/主动写"取决于可安装
的 SKILL.md——纯 markdown、跨 Claude Code/Codex/Gemini 通用，agent 按需调用。

本模块只产出可安装的 skill 包：
  <target>/experientia-memory/SKILL.md
内容约定：
- 前件 "When to Use"：完成一个仓库内任务 / 需要回顾本仓库上次怎么做；
- 动作 "Procedure"：读/写 `.repo_memory/`（架构地图、模块归属、issue 证据），
  把"踩过的坑/做对的做法"用一句话沉淀——Experientia 随后从会话文件自动吸收，
  不依赖 agent 直接调 Experientia 的 API（文件捕获即通道）。
- 反例/边界：绝不把仓库文件内容整段复制进记忆；绝不写凭据；`_fixes.md` 是坑。

真实会话提醒钩子（"任务完成时提示写记忆"）属于 E-2 第二刀——本文件提供判定纯函数
（memory_reminder）与受控推送入口（maybe_remind_store，默认关：config.features.memory_reminder），
推送频率与渠道由通知开关裁决，防噪音。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("experientia.memory_skill")

SKILL_DIRNAME = "experientia-memory"

SKILL_MD = """---
name: experientia-memory
description: 在完成一个仓库/工作区任务后主动沉淀或回顾仓库记忆（.repo_memory），
  让同仓库的后续任务少踩坑。用于"刚干完活该记一笔"与"开始前回顾同类做法"。
---

## When to Use
- 刚在一个仓库里完成一轮需要试错/有结论的任务；
- 开始任务前，若仓库根存在 `.repo_memory/`，先扫一眼同类条目；
- 用户说"记住这次做法 / 这个仓库的结构"。

## Procedure
1. 回顾仓库记忆目录 `.repo_memory/`：
   - `architecture.md`：模块地图、目录职责、关键入口；
   - `module-notes.md` 或 `issues.md`：某模块的坑、issue 证据（含日期）。
2. 只写"对下一次有用的最小事实"（每条 ≤3 句）：
   - 架构事实：`X 模块由 Y 负责，入口在 Z`；
   - 踩坑：`做 A 时别用 B，因为 C（失败时间戳）`；
   - 做法：`任务 T 的正确顺序是 1→2→3`。
3. 用追加/原地小改，不整篇重写；`git` 里的 commit 当证据索引，不复制正文。

## Pitfalls
- NEVER 把代码/文档整段复制进记忆——只留指针与结论；
- NEVER 写入密钥/令牌/内部地址；
- 只改 `.repo_memory/` 下的 markdown，不动仓库其它文件。
- 不要为"还没验证"的做法写结论（验证 = 跑通过/用户确认过）。

## Verification
- 任务收尾自查：本次踩过的坑/确定的架构事实是否已落到 `.repo_memory/`？
- 条目 ≤3 句、无正文大段复制、无凭据。
"""


def write_memory_skill(target_dir: str | Path) -> Path:
    """把记忆 skill 写到 <target_dir>/experientia-memory/SKILL.md（幂等覆盖）。"""
    root = Path(target_dir) / SKILL_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    p = root / "SKILL.md"
    p.write_text(SKILL_MD, encoding="utf-8")
    return p


def memory_reminder(session_dict: dict) -> str | None:
    """E-2 第二刀：会话结束的"写仓库记忆"提醒判定（纯函数，不自动推送）。

    返回提醒文案当且仅当：
    - 会话有 project（cwd）可定位工作区；
    - 该工作区还没有 `.repo_memory/`（建了就说明用户在维护，别烦）；
    - 会话有深度（≥2 轮）或有纠正信号——空转/闲聊不提醒。
    推送由调用方按通知开关/频率执行（防止每轮都打扰）。
    """
    session_dict = session_dict or {}
    proj = str(session_dict.get("project") or "").strip()
    if not proj:
        return None
    if (Path(proj) / ".repo_memory").is_dir():
        return None
    if int(session_dict.get("req_count") or 0) < 2 and not session_dict.get("correction_hits"):
        return None
    return (
        f"本轮在 {proj} 已积累可复用结论——可在仓库根建 .repo_memory/ 记一笔，"
        "experientia-memory skill 可帮你保持格式（架构事实 ≤3 句、坑与做法）。")


def maybe_remind_store(store, session_dict: dict) -> None:
    """E-2 受控推送：会话结束钩子入口（review.maybe_review_session 调用）。

    默认关——先过 config.features.memory_reminder（缺省 False），再过判定与
    通知开关（notify.push 自身裁决 system_notice）。任何异常都不影响复盘主流程。
    """
    try:
        from app import notify
        from app.config_schema import feature_enabled

        if not feature_enabled(store.load_config(), "memory_reminder"):
            return
        text = memory_reminder(session_dict)
        if text:
            notify.push(store, "system_notice", "仓库记忆提醒", text)
    except Exception as exc:
        logger.warning("仓库记忆提醒推送失败（不影响复盘）: %s", exc)
