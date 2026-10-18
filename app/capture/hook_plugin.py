"""Claude Code 官方插件包生成（阶段 C：.claude-plugin 形态，取代改全局 settings.json）。

按官方文档（code.claude.com/docs/zh-CN/plugins-reference）：
- 插件根目录：`.claude-plugin/plugin.json`（name 必填，kebab-case）+ 组件目录；
- hooks 组件默认位置 `hooks/hooks.json`（可用 plugin.json 的 "hooks" 字段显式指向）；
- hook 支持 `http` 类型：Claude 把事件 JSON POST 到 url——比 settings.json 的
  command+curl 更干净：不产生 shell 子进程、不依赖 curl、卸载即清。

本模块只做"确定性生成"（纯函数 + 落盘），不 import GUI/引擎：
- 一键"生成插件包"由上层（connect 页向导 / CLI）调用；
- 安装走官方 `claude plugin install <dir>`，卸载 `claude plugin uninstall <name>`
  ——不发明私有安装协议。
"""

from __future__ import annotations

import json
from pathlib import Path

from . import hook as hook_channel

PLUGIN_NAME = "experientia"
PLUGIN_DISPLAY = "Experientia Experience Loop"
PLUGIN_DESCRIPTION = (
    "把本地经验飞轮的注入（规则/经验）与实时捕获接到 Claude Code："
    "SessionStart/UserPromptSubmit 注入 + PostToolUse/Stop 轮毕复盘。"
)
PLUGIN_VERSION = "0.1.0"
MANIFEST_DIR = ".claude-plugin"
HOOKS_REL = "hooks/hooks.json"


def plugin_manifest(version: str = PLUGIN_VERSION,
                    display_name: str = PLUGIN_DISPLAY,
                    description: str = PLUGIN_DESCRIPTION) -> dict:
    """plugin.json 内容（字段以官方 plugins-reference 为准，路径以 ./ 开头）。"""
    return {
        "name": PLUGIN_NAME,
        "displayName": display_name,
        "version": version,
        "description": description,
        "author": {"name": "Experientia"},
        "hooks": f"./{HOOKS_REL}",
    }


def hooks_config(port: int = hook_channel.LOCAL_API_PORT,
                 agent: str | None = None,
                 key: str | None = None) -> dict:
    """插件 hooks/hooks.json：事件 → http hook（POST 事件 JSON 到本地 API）。

    与 settings.json 通道同一注册表（HOOK_CLIENTS 事件 → /api/hooks slug），
    四个事件各自直达端点；引擎端 fail-open（空 dict + 0 退出），不阻塞 agent。
    key：事件通道防伪令牌，以 ?key= 查询参数附在 url 上——http hook 同样
    无法携带 Bearer token。
    """
    client = hook_channel.HOOK_CLIENTS[hook_channel._client(agent)]
    events: dict[str, list] = {}
    for pascal, endpoint in client["events"]:
        url = f"http://127.0.0.1:{port}/api/hooks/{endpoint}"
        if key:
            url = f"{url}?key={key}"
        events[pascal] = [{
            "hooks": [{
                "type": "http",
                "url": url,
            }],
        }]
    return {"hooks": events}


def write_plugin_package(target_dir: str | Path,
                         port: int = hook_channel.LOCAL_API_PORT,
                         version: str = PLUGIN_VERSION,
                         key: str | None = None) -> Path:
    """把完整插件包写到 target_dir（幂等覆盖）。

    目录结构：
        <target_dir>/
          .claude-plugin/plugin.json
          hooks/hooks.json
    返回插件根目录（可交给 `claude plugin install <dir>`）。
    """
    root = Path(target_dir)
    manifest_p = root / MANIFEST_DIR / "plugin.json"
    hooks_p = root / HOOKS_REL
    manifest_p.parent.mkdir(parents=True, exist_ok=True)
    hooks_p.parent.mkdir(parents=True, exist_ok=True)
    manifest_p.write_text(
        json.dumps(plugin_manifest(version=version), ensure_ascii=False, indent=2),
        encoding="utf-8")
    hooks_p.write_text(
        json.dumps(hooks_config(port, key=key), ensure_ascii=False, indent=2),
        encoding="utf-8")
    return root
