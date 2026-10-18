---
id: c4-p2-changelog
name: Changelog 规则
category: c4
priority: p2
layer: structure
trigger_default: smart
tags: engineering; docs
keywords: changelog; 更新日志; 版本
description: 按 Added/Changed/Fixed/Removed 分类，面向用户写，不带内部术语
source: community
---

## 规则

- Changelog 按版本分节，节内按 Added / Changed / Fixed / Removed 四类排序。
- 每条面向最终用户写："更新日志现在按周归档"，不是"refactor archive job"。
- 破坏性变更单独置顶并标 `BREAKING`，附迁移步骤。
- 内部重构、依赖升级（无用户可见变化）不进 Changelog。
- 发版时从提交记录生成初稿，人工修订后再发布——NEVER 直接发布机器生成的版本。
