---
id: c4-p1-pr-description
name: PR 描述规范
category: c4
priority: p1
layer: structure
trigger_default: always
tags: engineering; git
keywords: PR; 合并请求; 描述
description: 变更摘要 + 动机 + 测试计划 + 影响范围，四段缺一不可
source: community
---

## 规则

- PR 描述固定四段：变更摘要（1-3 句）、动机（解决什么问题/对应 issue）、测试计划（怎么验证的）、影响范围（哪些模块/用户受影响）。
- 摘要写结论不写过程；贴关键 diff 片段或截图，不贴整个 diff。
- 影响范围涉及配置/数据迁移/接口变更时，必须写明回滚方式。
- 关联 issue 用 `Fixes #123` 自动关闭。
- NEVER 开空描述 PR（"see diff" 不算描述）。

## 示例

✅
摘要：注入块超预算时改为按行截断。
动机：整块丢弃导致低优先级规则全失效（#42）。
测试：新增 budget 截断单测 2 条；手动验证 3 类规则组合。
影响：仅 proxy/inject.py；无数据迁移。
