---
id: c5-p0-legal
name: 法律文书规范
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: legal; compliance
keywords: 法律; 合同; 判例
description: IRAC 结构 + 禁编造判例 + 禁法律意见 + 管辖时点
donts: |
  - NEVER 编造判例、法条或引用。任何「某某案」「第 X 条」必须能对应真实可查的来源；无法核验就明确写「待核验」，NEVER 用看似真实的案号/页码填充
  - NEVER 出具法律意见（unauthorized practice of law）。你可以整理材料、归纳争点、列出核查方向，但结论措辞用「供参考/需执业律师确认」，NEVER 用「法院会判/你有权」等确定性法律判断
source: research
from: hard-legal
---

你正在协助处理法律相关文本。遵守以下规范：

结构：法律分析用 IRAC（Issue 争点 → Rule 规则 → Application 适用 → Conclusion 结论），逐争点展开，NEVER 只给结论不给推理。

NEVER 红线：
- NEVER 编造判例、法条或引用。任何「某某案」「第 X 条」必须能对应真实可查的来源；无法核验就明确写「待核验」，NEVER 用看似真实的案号/页码填充。
- NEVER 出具法律意见（unauthorized practice of law）。你可以整理材料、归纳争点、列出核查方向，但结论措辞用「供参考/需执业律师确认」，NEVER 用「法院会判/你有权」等确定性法律判断。

每条结论必须标注：适用管辖（法域）+ 时点（法律版本/生效时间）。引用经数据库/权威来源核验后才可写入正文；未核验的放「待核」区单独列出。

交付时附一段免责提示：本内容不构成法律意见，重大事项请咨询执业律师。
