---
id: c3-p2-deploy
name: 部署运维
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: 部署; 上线; 运维
description: 部署前确认点 + 回滚预案 + 变更留痕
source: built-in
from: eng-deploy
---

部署/运维遵守：

部署前必须输出确认点并等确认（硬约束）：
- 列出：影响范围（哪些服务/环境）、数据迁移（有则列出步骤）、预计停机时间、回滚方案。
- 涉及生产/不可逆操作时，停下来等明确确认，NEVER 自动执行。

回滚预案：
- 每次变更先想「怎么回滚」；没有安全回滚路径就先做备份/快照。
- 数据迁移写可重入脚本（重跑不重复生效）。

变更留痕：
- 记录变更内容、执行人、时间；NEVER 无痕改生产配置。
- 密钥/证书不进代码库，走密钥管理；NEVER 在日志/截图里暴露。

NEVER：NEVER 直接在生产库跑未经演练的 SQL；NEVER 同时改多个相互依赖的服务。
