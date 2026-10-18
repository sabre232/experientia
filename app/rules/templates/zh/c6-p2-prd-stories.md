---
id: c6-p2-prd-stories
name: 用户故事（含验收标准）
category: c6
priority: p2
layer: structure
trigger_default: smart
tags: product
keywords: 用户故事; 验收标准
description: 标准句式 + Given-When-Then 验收
source: built-in
from: prd-stories
---

写用户故事时遵守：

标准句式：
作为 [角色]，我想要 [能力]，以便 [价值/收益]。
- 角色具体（不是「用户」，而是「新注册 3 天内的免费用户」）。
- 价值要真实，NEVER 写「提升体验」这类空话。

验收标准（每条故事必备）：
用 Given-When-Then：
- Given [前置状态]，When [操作]，Then [可观察结果]。
- 覆盖正常路径 + 至少一个异常/边界（空、失败、无权限）。

拆分纪律：
- 一个故事一个可独立交付的能力；太大就拆，太小就合。
- 故事之间标注依赖关系（A 依赖 B 先做）。

NEVER：NEVER 把实现方案写进故事（故事讲「要什么」，不讲「怎么做」）。
