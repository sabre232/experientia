"""统一代理层 localhost:8100（M3 里程碑）。

路由 / 自动注入（含三级压缩 ladder）/ 请求级记录 /
上下文感知（Agent/API/任务/Session 自动识别，-15.6）/
规则通道与硬钩子重注入。
协议：OpenAI 兼容 /v1/chat/completions + Anthropic 原生 /v1/messages。
降级：fail-open，注入超时跳过不阻塞转发。
"""

from .detect import agent_names, agent_display_name, detect_agent

__all__ = ["agent_names", "agent_display_name", "detect_agent"]