---
id: c4-p3-readme
name: README 维护
category: c4
priority: p3
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: README; 文档; 同步
description: README 与代码同步：装/跑/测三命令永远可复制执行
source: built-in
---

## 规则

- README 必含三块：安装、运行、测试；三块里的命令必须与仓库实际一致（CI 配置是事实来源）。
- 改命令/参数/目录结构时，同一提交里更新 README——命令和文档分开提交视为未完成。
- 新人视角检查：只读 README 能否在 10 分钟内跑起本地环境；不能就补缺的步骤。
- 过期章节直接删，不留"待更新"占位。
