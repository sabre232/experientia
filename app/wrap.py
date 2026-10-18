"""experientia-wrap：命令包装通道（路线图 D）。

适用：读"base_url 环境变量"的 CLI agent，用户想不经手动改配置就让它走本地 8100
代理（① 端点改写体验）——例如 Claude Code（ANTHROPIC_BASE_URL）与
DeepSeek Harness（DEEPSEEK_BASE_URL，见 connect 页分工具口径，不发明变量名）。

用法（安装后 / 仓库内）：
    experientia-wrap --target deepseek-harness -- deepseek
    experientia-wrap --target claude-code -- claude
    experientia-wrap --target deepseek-harness --url http://127.0.0.1:8100 \
        --env EXTRA=1 -- deepseek

行为：给子进程注入对应 base_url 环境变量后 exec（子进程替换当前进程），
并打印注入说明。目标表之外的工具不做任何 env 改动（避免误伤官方直连），
仅原样转发并提示"该工具不走环境变量，wrap 不适用，请用文件捕获/代理配置"。
无命令参数 → 打印用法返回 2（不 exec、无副作用）。

退出码 = 子进程退出码（os.exec 语义）；失败/被拦日志走 stderr，静默不吞。
"""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_PROXY_URL = "http://127.0.0.1:8100"

# 只收录"官方接口 = 环境变量 base_url"的客户端（connect 页分工具口径已核）。
# 其余（Codex/CodeBuddy 配置文件、Cursor/Gemini 不支持自定义地址、WorkBuddy UI）
# 不走 env，不在此表。
WRAP_ENV: dict[str, dict[str, str]] = {
    "claude-code": {"ANTHROPIC_BASE_URL": DEFAULT_PROXY_URL},
    "deepseek-harness": {"DEEPSEEK_BASE_URL": DEFAULT_PROXY_URL},
}

_NOTICE_PREFIX = "[experientia-wrap] "


def build_env(target: str | None, url: str = DEFAULT_PROXY_URL,
              extra: dict[str, str] | None = None) -> tuple[dict | None, list[str]]:
    """返回 (注入后的 env 增量, 说明行列表)；未知 target → (None, 说明行)。

    增量 None = 调用方保持子进程环境原样（不设任何 wrap 变量）。
    """
    notes: list[str] = []
    if not target:
        notes.append("未指定 --target，不注入任何环境变量（原样转发）")
        return None, notes
    mapping = WRAP_ENV.get(target)
    if mapping is None:
        notes.append(
            f"工具 '{target}' 不走环境变量 base_url（配置文件/官方直连），"
            "wrap 不适用——请用文件捕获或按其配置接入 8100")
        return None, notes
    merged: dict[str, str] = {}
    for key in mapping:
        merged[key] = url  # 映射定 key，值恒用（可被 --url 覆盖的）目标地址
    if extra:
        merged.update(extra)
    notes.append(f"目标={target} 已注入 {list(merged)} → 走 {url} 代理")
    return merged, notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="experientia-wrap", description=__doc__.splitlines()[0])
    ap.add_argument("--target", default=None,
                    help=f"wrap 目标：{', '.join(WRAP_ENV)}")
    ap.add_argument("--url", default=DEFAULT_PROXY_URL, help="本地代理地址")
    ap.add_argument("--env", action="append", default=[], metavar="K=V",
                    help="额外注入的环境变量（可多次）")
    ap.add_argument("command", nargs=argparse.REMAINDER,
                    help="要启动的命令（-- 之后）")
    a = ap.parse_args(argv)

    if not a.command:
        ap.print_help(sys.stderr)
        return 2

    extra: dict[str, str] = {}
    for item in a.env:
        if "=" in item:
            k, v = item.split("=", 1)
            extra[k.strip()] = v
        else:
            print(f"{_NOTICE_PREFIX}忽略无效 --env（缺 =）: {item}", file=sys.stderr)

    delta, notes = build_env(a.target, a.url, extra or None)
    for note in notes:
        print(f"{_NOTICE_PREFIX}{note}", file=sys.stderr)

    env = dict(os.environ)
    if delta:
        env.update(delta)
    try:
        os.execvpe(a.command[0], list(a.command), env)
    except OSError as exc:
        print(f"{_NOTICE_PREFIX}启动失败：{a.command[0]} — {exc}", file=sys.stderr)
        return 127
    return 0  # exec 成功后不可达


if __name__ == "__main__":
    raise SystemExit(main())
