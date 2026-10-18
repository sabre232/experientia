---
id: c6-p1-prd-structure
name: PRD 结构
category: c6
priority: p1
layer: structure
trigger_default: always
tags: product
keywords: PRD; 需求; 产品
description: 背景目标→方案→边界→度量
source: built-in
from: prd-structure
---

写 PRD 时按此结构，缺项要显式写「无/不适用」：

1. 背景与问题：为什么做，用户痛点 + 现状数据。
2. 目标与非目标：本期目标（可量化）；明确「不做什么」，防止范围蔓延。
3. 用户与场景：目标用户、核心场景（用户故事形式）。
4. 方案：功能列表 + 交互流程 + 关键界面说明；每个功能给优先级（P0/P1/P2）。
5. 边界与异常：空态、错误态、权限、并发、数据边界。
6. 度量：上线后看什么指标判定成功。
7. 依赖与风险：跨团队依赖、技术风险、回滚方案。

纪律：
- 每个 P0 功能必须有验收标准。
- 假设（未验证的）单独标注，NEVER 把假设写成事实。
