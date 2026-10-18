---
id: c6-p1-prd-decision
name: 决策矩阵
category: c6
priority: p1
layer: structure
trigger_default: always
tags: product
keywords: 决策; 选型; 权衡
description: 选项×维度加权打分 + 显式假设
source: built-in
from: prd-decision
---

做方案权衡/选型时遵守：

结构：
- 列出 2-4 个候选方案（含「什么都不做」作基线）。
- 评估维度 3-6 个（如成本、风险、速度、可维护性），每个维度标权重（和=100）。
- 矩阵打分（1-5），加权求和，标出推荐项。

纪律：
- 每个打分给一句依据；「拍脑袋」的维度要显式标注主观。
- 权重本身要论证（为什么这个维度更重），NEVER 默认均分。
- 列出关键假设（哪些打分依赖未验证前提），假设变则结论要重算。

输出：
- 推荐项 + 一句话理由 + 主要风险 + 「什么情况下该改选」的触发条件。
- NEVER 只给分数不给推理。
