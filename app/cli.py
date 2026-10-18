"""命令入口：init / scan / status / model / daemon（开发与排障用）。

正式入口：main.py（桌面端，GUI 外壳 + 内嵌引擎）、daemon.py（headless，只跑引擎）。
model 子命令是模型路由的用户入口（GUI 模型管理页落地前的 CLI 等价物）：
- 添加路由（本地/云端/Anthropic），API Key 存系统钥匙串不落 config
- set-distill 指定蒸馏/复盘专用模型（可与代理默认模型不同）
daemon 子命令 = README 承诺的 headless 入口（只跑引擎不启 GUI）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import models_service as models
from .capture import scan as capture_scan
from .store.store import Store


def _daemon_cmd() -> int:
    """experientia daemon：headless 引擎（代理+捕获+蒸馏，无 GUI）。

    实现在仓库根 daemon.py（README/文档口径）。按 app 包位置定位仓库根并
    以绝对路径运行——不依赖 cwd；安装模式（wheel 只打包 app 包）给明确提示。
    """
    repo_root = Path(__file__).resolve().parents[1]
    daemon_py = repo_root / "daemon.py"
    if not daemon_py.exists():
        print("未找到仓库根 daemon.py：安装模式不含仓库根入口，"
              "请在源码目录运行 python <仓库>/daemon.py")
        return 1
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import daemon as engine
    engine.main()
    return 0


def _models_cmd(args: argparse.Namespace) -> int:
    """CLI 入口薄壳：逻辑在 models_service（本地 API / GUI 共用同一份）。"""
    store = Store()
    store.ensure_layout()
    cmd = args.model_cmd

    if cmd == "list":
        info = models.list_routes(store)
        if not info["routes"]:
            print("（未配置模型。添加: experientia model add <名> --endpoint URL --model 模型名 [--key KEY]）")
            return 0
        for r in info["routes"]:
            marks = []
            if r["is_default"]:
                marks.append("默认")
            if r["is_distill"]:
                marks.append("蒸馏")
            tag = f"  [{'/'.join(marks)}]" if marks else ""
            key = {"keyring": "(keyring)", "plaintext": "(明文)", "none": "(无 key)"}[r["key_source"]]
            print(f"{r['name']}{tag}  type={r['type']}  endpoint={r['endpoint']}  "
                  f"model={r['model']}  {key}")
        return 0

    if cmd == "add":
        ok, msg = models.add_route(store, args.name, args.endpoint, args.model_name,
                                   args.type, args.key)
    elif cmd == "set-distill":
        ok, msg = models.set_route(store, args.name, "distill")
    elif cmd == "set-default":
        ok, msg = models.set_route(store, args.name, "default")
    elif cmd == "rm":
        ok, msg = models.remove_route(store, args.name)
    else:
        return 1
    print(msg)
    return 0 if ok else 1


def _stats_cmd(store) -> int:
    """聚合账本 Markdown（OSS 无遥测的自报式激活度量）。

    只含计数与聚合，不含任何会话内容——用户自愿复制到 Issue 即反馈。"""
    from . import ledger
    from .distill import mining
    from .version import VERSION

    led = ledger.compute(store)
    st = mining.rule_stats(store)
    pend = store.load_pending_review_records()
    gov = store.injection_governed_items()
    hits = store.load_injection_hits()
    effects = []
    for key, cat in hits.items():
        for iid, e in ((cat or {}).get("items") or {}).items():
            if isinstance(e, dict) and isinstance(e.get("effect"), dict):
                effects.append((key, e))
    improved = [x for x in effects
                if float((x[1]["effect"] or {}).get("delta") or 0) > 0]
    prob = [x for x in effects
            if x[1].get("probation_left") is not None]
    lines = [
        "## Experientia stats（本地自报 · 无遥测 · 仅聚合计数）",
        f"- 版本：{VERSION} · 数据目录版本：{store.load_meta().get('data_version', 0)}",
        f"- 账本：会话 {led['sessions']} · 轮次 {led['rounds']} · "
        f"token {led['tokens']} · 花费估算 ${led['cost_usd_est']}（计价覆盖 "
        f"{led['cost_priced_share']:.0%}）",
        f"- 坑卡：{led['rule_cards']} 张（可注入 {led['rule_injectable']}）· "
        f"分布 {st['by_kind'] or '无'}",
        f"- 证据队列：{len(pend)} 条待提炼（冷存 {len(store.load_pending_archive_records())}）",
        f"- 注入治理：受限/移出 {len(gov)} 条 · 试用期条目 {len(prob)} 条",
        f"- 逐条判据：{len(effects)} 条有判据，其中 {len(improved)} 条"
        f"被注入会话修正轮数低于类别基线",
    ]
    print("\n".join(lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="experientia", description="Local experience flywheel for AI agents"
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("init", help="创建 ~/.experientia 数据目录")
    sub.add_parser("scan", help="执行一次文件捕获扫描")
    sub.add_parser("status", help="显示数据目录与积累状况")
    sub.add_parser("stats", help="导出聚合账本 Markdown（自愿贴 Issue 的自报反馈，无遥测）")
    sub.add_parser("daemon", help="运行 headless 引擎（代理+捕获+蒸馏，无 GUI）")

    model_p = sub.add_parser("model", help="模型路由管理（本地/云端，蒸馏模型选择）")
    model_sub = model_p.add_subparsers(dest="model_cmd")
    model_sub.add_parser("list", help="列出模型路由")
    add_p = model_sub.add_parser("add", help="添加模型路由（key 存系统钥匙串）")
    add_p.add_argument("name", help="路由名（如 local-27b / gpt-4o）")
    add_p.add_argument("--endpoint", required=True, help="端点 URL（如 http://127.0.0.1:8080/v1）")
    add_p.add_argument("--model", required=True, dest="model_name", help="上游真实模型名")
    add_p.add_argument("--type", choices=["local", "cloud", "anthropic"], default="cloud",
                       help="local=本地（长超时） cloud=OpenAI 兼容云端 anthropic=Anthropic API")
    add_p.add_argument("--key", default=None, help="API Key（存系统钥匙串；本地模型无需）")
    sd_p = model_sub.add_parser("set-distill", help="设置蒸馏/复盘专用模型（可与默认模型不同）")
    sd_p.add_argument("name")
    sdef_p = model_sub.add_parser("set-default", help="设置默认模型（代理主路由）")
    sdef_p.add_argument("name")
    rm_p = model_sub.add_parser("rm", help="删除模型路由（连带删除钥匙串里的 key）")
    rm_p.add_argument("name")

    args = parser.parse_args(argv)

    store = Store()
    store.ensure_layout()

    if args.cmd == "init":
        print(f"数据目录就绪: {store.data_dir}")
        return 0
    if args.cmd == "daemon":
        return _daemon_cmd()
    if args.cmd == "scan":
        result = capture_scan.run_scan(store)
        print(f"新增会话: {result.new_sessions}")
        print(f"跳过(未变化): {result.skipped}  解析失败: {result.parse_failures}")
        stats = store.stats()
        print(f"累计: 经验 {stats['experiences']} 条(待蒸馏 {stats['pending']}) "
              f"归档会话 {stats['archived_sessions']} playbook {stats['skills']}")
        return 0
    if args.cmd == "model":
        return _models_cmd(args)
    if args.cmd == "stats":
        return _stats_cmd(store)
    # 默认 status
    for key, value in store.stats().items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
