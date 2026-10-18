---
id: c3-p2-eng-baseline
name: 构建与测试基线
category: c3
priority: p2
layer: structure
trigger_default: smart
tags: engineering; testing
keywords: 构建; 测试; 基线
description: 改动前跑基线，改动后跑受影响测试再提交
source: built-in
from: eng-general
---

构建与测试（先确认再跑）：
- 开始改动前先跑一次现有测试，记录基线；每次改动后跑受影响模块的测试再提交。
- 构建/测试命令以仓库 README、Makefile、CI 配置为准，NEVER 凭记忆猜命令。
