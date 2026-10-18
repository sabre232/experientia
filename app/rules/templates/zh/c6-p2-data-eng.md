---
id: c6-p2-data-eng
name: 数据工程
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: data; engineering
keywords: 数据; 管道; 批处理
description: 幂等管道 + 数据质量断言 + 口径文档
source: built-in
from: eng-data
---

数据管道/批处理遵守：

幂等与可重入：
- 任务重跑结果一致；按分区/日期增量处理，NEVER 整表无脑覆盖。
- 失败可从断点恢复；NEVER 假设任务只跑一次。

数据质量：
- 关键表加断言（非空、唯一、行数波动阈值）；异常先告警再继续或中止，NEVER 静默吞掉脏数据。
- 口径（去重规则、时间窗、币种/时区）写成文档，NEVER 让口径只存在于某段 SQL 里。

安全：
- 敏感字段（PII）管道内最小化；中间产物同样脱敏。
- 大查询先看数据量与索引，NEVER 在生产库跑全表扫。
