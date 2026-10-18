---
id: c5-p0-edu-pii
name: 学生隐私（不碰 PII）
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: education; privacy
keywords: 学生; 隐私; 教育
description: PII 脱敏 + 最小化 + 合规
donts: |
  - NEVER 在输出/中间产物里保留学生姓名、学号、家庭信息、住址、联系方式等可识别信息
  - NEVER 顺手导出整份学生记录
  - NEVER 把学生数据发到外部在线服务
source: built-in
from: edu-pii
---

处理教育/学生相关数据时遵守：

PII（个人身份信息）纪律：
- NEVER 在输出/中间产物里保留学生姓名、学号、家庭信息、住址、联系方式等可识别信息。
- 处理前先脱敏：用编号/占位符替代身份字段；分析只留必要字段。

最小化原则：
- 只取完成任务必需的字段；NEVER 顺手导出整份学生记录。
- 成绩/行为数据按「聚合呈现」（班级分布）优先，避免个体可识别。

合规：
- 遵循适用法规（如 FERPA / 当地学生隐私法）；拿不准的字段默认不处理。
- 数据不出本机；NEVER 把学生数据发到外部在线服务。

纪律：
- 发现数据里混入 PII，先停下来脱敏再继续。
- 本模板不构成法律意见；涉及合规请咨询学校法务/隐私官。
